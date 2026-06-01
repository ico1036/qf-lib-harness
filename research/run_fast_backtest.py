"""Fast backtest harness using FastAlphaModelTester.

Runs parameter sweeps over AlphaModels with IS/OS split.

Usage:
    python run_fast_backtest.py
"""
import os
from datetime import datetime
from itertools import product
from pathlib import Path

_HERE = Path(__file__).parent.resolve()
os.environ.setdefault("QF_STARTING_DIRECTORY", str(_HERE))

from alpha_lab import _weasyprint_stub  # noqa: F401

import matplotlib
matplotlib.use("Agg")

import numpy as np
import pandas as pd

from qf_lib.backtesting.events.time_event.regular_time_event.market_close_event import MarketCloseEvent
from qf_lib.backtesting.events.time_event.regular_time_event.market_open_event import MarketOpenEvent
from qf_lib.backtesting.fast_alpha_model_tester.fast_alpha_models_tester import (
    FastAlphaModelTester,
    FastAlphaModelTesterConfig,
)
from qf_lib.common.enums.frequency import Frequency
from qf_lib.common.tickers.tickers import YFinanceTicker

from config import PRICES_PATH
from alpha_lab.parquet_data_provider import build_data_provider
from tsmom_alpha_model import TSMomentumAlphaModel

# Required for PresetDataProvider look-ahead bias check
MarketOpenEvent.set_trigger_time({"hour": 9, "minute": 30, "second": 0, "microsecond": 0})
MarketCloseEvent.set_trigger_time({"hour": 16, "minute": 0, "second": 0, "microsecond": 0})

# ── backtest knobs ──────────────────────────────────────────────
UNIVERSE_SIZE = 100
IS_START = datetime(2018, 1, 1)
IS_END = datetime(2021, 12, 31)
OS_START = datetime(2022, 1, 1)
OS_END = datetime(2024, 12, 31)
DATA_PAD_YEARS = 2
N_JOBS = 1


# ── universe selection (from run_tsmom_backtest.py) ─────────────
def select_universe(parquet_path, n, min_history_before, min_bars=280):
    df = pd.read_parquet(parquet_path, columns=["date", "ticker", "dollar_volume"])
    df["date"] = pd.to_datetime(df["date"])
    pre = df[df["date"] < min_history_before]
    eligible = pre.groupby("ticker").size()
    eligible = eligible[eligible >= min_bars].index
    df = df[df["ticker"].isin(eligible)]
    avg = df.groupby("ticker")["dollar_volume"].mean()
    return avg.nlargest(n).index.tolist()


def build_configs(model_cls, param_ranges, tested_params):
    """Build FastAlphaModelTesterConfig list from param ranges."""
    keys = list(param_ranges.keys())
    configs = []
    for vals in product(*[param_ranges[k] for k in keys]):
        kwargs = dict(zip(keys, vals))
        configs.append(FastAlphaModelTesterConfig(model_cls, kwargs, tested_params))
    return configs


def compute_metrics(returns_series) -> dict:
    """Sharpe, CAGR, MaxDD from simple returns series."""
    if returns_series is None or returns_series.empty or returns_series.isna().all():
        return {"sharpe": float("nan"), "cagr": float("nan"), "maxdd": float("nan")}
    rets = returns_series.dropna()
    if len(rets) < 2:
        return {"sharpe": float("nan"), "cagr": float("nan"), "maxdd": float("nan")}

    mean_ret = rets.mean()
    std_ret = rets.std()
    sharpe = (mean_ret / std_ret * np.sqrt(252)) if std_ret > 0 else float("nan")

    cumulative = (1 + rets).cumprod()
    total_ret = cumulative.iloc[-1] - 1
    n_years = len(rets) / 252
    cagr = ((1 + total_ret) ** (1 / n_years) - 1) if n_years > 0 else float("nan")

    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    maxdd = drawdown.min()

    return {"sharpe": sharpe, "cagr": cagr, "maxdd": maxdd}


def run_test(configs, tickers, start_date, end_date, data_provider):
    """Run FastAlphaModelTester."""
    qf_tickers = [YFinanceTicker(t) for t in tickers]
    tester = FastAlphaModelTester(
        alpha_model_configs=configs,
        tickers=qf_tickers,
        start_date=start_date,
        end_date=end_date,
        data_provider=data_provider,
        n_jobs=N_JOBS,
        frequency=Frequency.DAILY,
    )
    return tester.test_alpha_models()


def extract_results(summary, period: str) -> list[dict]:
    """Extract per-param metrics from BacktestSummary (portfolio-level only)."""
    rows = []
    seen = set()
    for elem in summary.elements_list:
        if len(elem.tickers) <= 1:
            continue
        key = elem.model_parameters
        if key in seen:
            continue
        seen.add(key)
        metrics = compute_metrics(elem.returns_tms)
        row = {"period": period}
        for name, val in zip(elem.model_parameters_names, elem.model_parameters):
            row[name] = val
        row.update(metrics)
        rows.append(row)
    return rows


def main():
    print("=" * 70)
    print("Fast Backtest Harness")
    print("=" * 70)

    print(f"\nSelecting universe: top {UNIVERSE_SIZE} by ADV ...")
    universe = select_universe(PRICES_PATH, UNIVERSE_SIZE, IS_START, 280)
    print(f"  {len(universe)} tickers: {universe[:5]} ...")

    data_start = datetime(IS_START.year - DATA_PAD_YEARS, IS_START.month, IS_START.day)
    print("Building data provider ...")
    dp = build_data_provider(PRICES_PATH, start_date=data_start, end_date=OS_END, tickers_subset=universe)

    # Build parameter grid
    configs = build_configs(
        TSMomentumAlphaModel,
        param_ranges={
            "lookback_days": [126, 252],
            "skip_days": [21],
            "threshold": [0.0, 0.05],
            "risk_estimation_factor": [1.5],
        },
        tested_params=["lookback_days", "threshold"],
    )
    print(f"  {len(configs)} parameter combinations")

    # IS period
    print(f"\nIS period: {IS_START.date()} -> {IS_END.date()}")
    is_summary = run_test(configs, universe, IS_START, IS_END, dp)
    is_rows = extract_results(is_summary, "IS")

    # OS period (rebuild DP to reset timer)
    dp_os = build_data_provider(PRICES_PATH, start_date=data_start, end_date=OS_END, tickers_subset=universe)
    print(f"OS period: {OS_START.date()} -> {OS_END.date()}")
    os_summary = run_test(configs, universe, OS_START, OS_END, dp_os)
    os_rows = extract_results(os_summary, "OS")

    # Build result dataframe
    df = pd.DataFrame(is_rows + os_rows)
    cols = ["period"] + [c for c in df.columns if c != "period"]
    df = df[cols]

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(df.to_string(index=False, formatters={
        "sharpe": lambda x: f"{x:.2f}",
        "cagr": lambda x: f"{x:.2%}",
        "maxdd": lambda x: f"{x:.2%}",
    }))

    out_path = _HERE / "output" / "fast_backtest_results.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
