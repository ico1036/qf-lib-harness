"""FROZEN — TrialContext, data loaders, IS/OS dates.

The agent does NOT edit this file. To extend the data surface, surface a
request to the human. The agent's job is in experiments/<exp>/strategy.py.

Locked windows
--------------
- Data window:  2015-01-01 ~ OS_END  (covers signal warmup + IS + OS)
- IS window:    IS_START ~ IS_END    (loop-visible, agent reads metrics here)
- OS window:    OS_START ~ OS_END    (loop-visible, but tuned-against = drift)

The IS/OS gate (Sharpe_IS > 0.5 AND Sharpe_OS > 0.5 * Sharpe_IS) lives in
pipeline.py; this file only owns the date constants and data loading.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Locked dates and pool size — tuned only by human, never by agent.
# ---------------------------------------------------------------------------

DATA_START = datetime(2015, 1, 1)      # earliest bar fetched (warmup space)
IS_START   = datetime(2017, 1, 3)      # ≥2y warmup so 252d+21d signal history filter passes
IS_END     = datetime(2023, 1, 3)      # IS [IS_START, IS_END), 6 years
OS_START   = datetime(2023, 1, 3)      # OS [OS_START, OS_END), ~3.3 years
OS_END     = datetime(2026, 4, 1)

UNIVERSE_POOL_N = 300                  # eligible pool by all-time ADV (history-filtered)

# Default research data layout (relative to research/us_universe/).
_HERE = Path(__file__).resolve().parents[1]
PRICES_PATH = _HERE / "data" / "prices.parquet"
PIT_UNIVERSE_PATH = _HERE / "data" / "universe_pit_top3000.parquet"


# ---------------------------------------------------------------------------
# Universe selection (lifted from run_tsmom_backtest.select_universe)
# ---------------------------------------------------------------------------

def select_universe(
    parquet_path: Path = PRICES_PATH,
    n: int = UNIVERSE_POOL_N,
    min_history_before: datetime = IS_START,
    min_bars: int = 252 + 21 + 5,
) -> list[str]:
    """Top-N tickers by all-time mean dollar volume, restricted to those with
    at least `min_bars` daily bars before `min_history_before`.

    The history filter is the cheapest mitigation against a pure all-time-ADV
    survivorship bias — without it a ticker that listed yesterday with one
    explosive volume bar could enter. Tickers that delisted before
    `min_history_before` are still excluded (yfinance only serves currently
    listed names anyway).
    """
    df = pd.read_parquet(parquet_path, columns=["date", "ticker", "dollar_volume"])
    df["date"] = pd.to_datetime(df["date"])
    pre = df[df["date"] < min_history_before]
    eligible = pre.groupby("ticker").size()
    eligible = eligible[eligible >= min_bars].index
    df = df[df["ticker"].isin(eligible)]
    avg = df.groupby("ticker")["dollar_volume"].mean()
    return avg.nlargest(n).index.tolist()


# ---------------------------------------------------------------------------
# TrialContext — what the agent's signal() function sees
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrialContext:
    """Read-only data view passed to strategy.signal().

    All matrices share the same DatetimeIndex (DATA_START ~ OS_END, business
    days only) and the same ticker columns (the fixed pool from
    select_universe). NaNs mark unlisted-or-missing days.

    Returns are NOT pre-computed — the agent picks the right shift/lookback.
    All prices are auto-adjusted (split + dividend), so use `adj_close` (alias
    `close` here, since the pipeline downloaded with yfinance auto_adjust=True)
    for return computation.
    """

    adj_close: pd.DataFrame      # date × ticker
    open: pd.DataFrame
    high: pd.DataFrame
    low: pd.DataFrame
    volume: pd.DataFrame
    dollar_volume: pd.DataFrame
    universe: tuple[str, ...]    # the pool — strategy may sub-select


def _pivot(long_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Long → wide pivot, sorted by date."""
    return (
        long_df.pivot(index="date", columns="ticker", values=value_col)
               .sort_index()
    )


def load_context(
    universe: Iterable[str] | None = None,
    parquet_path: Path = PRICES_PATH,
    data_start: datetime = DATA_START,
    data_end: datetime = OS_END,
) -> TrialContext:
    """Load the full IS+OS+warmup window into a TrialContext.

    Slow on first call (~5-30s depending on disk + universe size). Pipeline
    caches across runs in the same session is left to the caller.
    """
    if universe is None:
        universe = select_universe()
    universe = tuple(sorted(universe))

    cols = ["date", "ticker", "Open", "High", "Low", "Close", "Volume", "dollar_volume"]
    df = pd.read_parquet(parquet_path, columns=cols)
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["ticker"].isin(universe)]
    df = df[(df["date"] >= pd.Timestamp(data_start)) & (df["date"] < pd.Timestamp(data_end))]
    if df.empty:
        raise ValueError(
            f"No price rows after universe + date filter "
            f"({data_start.date()} ~ {data_end.date()}, |universe|={len(universe)})."
        )

    return TrialContext(
        adj_close=_pivot(df, "Close"),    # auto_adjust=True per data pipeline
        open=_pivot(df, "Open"),
        high=_pivot(df, "High"),
        low=_pivot(df, "Low"),
        volume=_pivot(df, "Volume"),
        dollar_volume=_pivot(df, "dollar_volume"),
        universe=universe,
    )


def annualization_factor() -> float:
    """Trading days per year — the canonical 252."""
    return 252.0


def sharpe(returns: pd.Series) -> float:
    """Daily-simple-return Sharpe (rf=0). NaN-safe; needs at least 30 obs.

    A constant-or-near-constant series returns NaN (std below 1e-12 is below
    pandas' floating-point noise floor — `==0` would miss it).
    """
    r = returns.dropna()
    if len(r) < 30:
        return float("nan")
    s = r.std(ddof=0)
    if not np.isfinite(s) or s < 1e-12:
        return float("nan")
    return float(r.mean() / s * np.sqrt(annualization_factor()))
