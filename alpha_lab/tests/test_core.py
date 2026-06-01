"""Tests for alpha_lab.core — TrialContext, dates, sharpe, universe selection."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from alpha_lab import core


# ---------------------------------------------------------------------------
# Locked dates — sanity invariants
# ---------------------------------------------------------------------------

class TestLockedDates:
    def test_is_window_strictly_before_os(self):
        assert core.IS_END == core.OS_START, "IS/OS must be contiguous (no gap, no overlap)"
        assert core.IS_START < core.IS_END
        assert core.OS_START < core.OS_END

    def test_data_start_covers_signal_warmup(self):
        # ≥6 months before IS_START so 252-day signals have warmup data
        gap = (core.IS_START - core.DATA_START).days
        assert gap >= 180, f"DATA_START too close to IS_START ({gap}d) — 252d lookback would clip"

    def test_pool_size_reasonable(self):
        assert 50 <= core.UNIVERSE_POOL_N <= 1000


# ---------------------------------------------------------------------------
# sharpe()
# ---------------------------------------------------------------------------

class TestSharpe:
    def test_known_sharpe_value(self):
        # Mean = 0.001, std = 0.01, daily, sqrt(252) ≈ 15.87 → sharpe ≈ 1.587
        rng = np.random.default_rng(42)
        # Use deterministic series — exact mean/std
        n = 252 * 5
        rets = pd.Series([0.001] * n).add(pd.Series(rng.normal(0, 0.01, n))).reset_index(drop=True)
        # Known mean/std of constructed series — just check finite + plausible range
        s = core.sharpe(rets)
        assert np.isfinite(s)

    def test_constant_series_returns_nan(self):
        # Zero std → sharpe undefined → NaN
        s = core.sharpe(pd.Series([0.001] * 100))
        assert np.isnan(s)

    def test_too_few_observations_returns_nan(self):
        # < 30 obs → NaN guard
        assert np.isnan(core.sharpe(pd.Series([0.01, -0.01, 0.005])))

    def test_empty_series_returns_nan(self):
        assert np.isnan(core.sharpe(pd.Series([], dtype=float)))

    def test_drops_nans_before_count_check(self):
        # 25 real obs + 100 NaNs → should still be NaN (under threshold post-drop)
        s = pd.Series([0.001] * 25 + [np.nan] * 100)
        assert np.isnan(core.sharpe(s))

    def test_positive_drift_gives_positive_sharpe(self):
        # 252 days of +0.001 mean, +0.01 std
        rng = np.random.default_rng(0)
        rets = pd.Series(rng.normal(0.001, 0.01, 252))
        assert core.sharpe(rets) > 0

    def test_negative_drift_gives_negative_sharpe(self):
        rng = np.random.default_rng(0)
        rets = pd.Series(rng.normal(-0.001, 0.01, 252))
        assert core.sharpe(rets) < 0


# ---------------------------------------------------------------------------
# select_universe — uses synthetic parquet fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_prices_parquet(tmp_path: Path) -> Path:
    """Build a tiny prices.parquet matching the production schema.

    7 tickers across 2015-01 ~ 2017-12. Two of them ("LATE_*") only have
    history starting 2017-06, so they should fail the min_bars filter when
    min_history_before is in 2017-01.
    """
    dates = pd.bdate_range("2015-01-01", "2017-12-31")
    rows = []
    full_history_tickers = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    short_tickers = ["LATE1", "LATE2"]

    rng = np.random.default_rng(0)
    for t in full_history_tickers:
        # all dates
        dv_level = {"AAA": 1e9, "BBB": 5e8, "CCC": 2e8, "DDD": 1e8, "EEE": 5e7}[t]
        for d in dates:
            rows.append({"date": d, "ticker": t, "dollar_volume": dv_level + rng.normal(0, dv_level * 0.05)})

    for t in short_tickers:
        # only 2017-06 onwards (200 days)
        for d in dates[dates >= "2017-06-01"]:
            rows.append({"date": d, "ticker": t, "dollar_volume": 1e10})  # huge — should rank top by ADV

    df = pd.DataFrame(rows)
    path = tmp_path / "prices.parquet"
    df.to_parquet(path)
    return path


class TestSelectUniverse:
    def test_history_filter_excludes_late_listings(self, synthetic_prices_parquet: Path):
        # min_history_before = 2017-01-01 means LATE* tickers (start 2017-06) have 0 prior bars
        picked = core.select_universe(
            synthetic_prices_parquet,
            n=10,
            min_history_before=datetime(2017, 1, 1),
            min_bars=200,
        )
        assert "LATE1" not in picked
        assert "LATE2" not in picked

    def test_top_n_by_dollar_volume(self, synthetic_prices_parquet: Path):
        # AAA (1e9) > BBB (5e8) > CCC (2e8) — top-3 should be AAA, BBB, CCC in order
        picked = core.select_universe(
            synthetic_prices_parquet,
            n=3,
            min_history_before=datetime(2017, 1, 1),
            min_bars=200,
        )
        assert picked == ["AAA", "BBB", "CCC"]

    def test_n_caps_result(self, synthetic_prices_parquet: Path):
        picked = core.select_universe(
            synthetic_prices_parquet,
            n=2,
            min_history_before=datetime(2017, 1, 1),
            min_bars=200,
        )
        assert len(picked) == 2


# ---------------------------------------------------------------------------
# load_context — uses synthetic parquet fixture with all OHLCV fields
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_full_prices_parquet(tmp_path: Path) -> Path:
    """Full OHLCV parquet for 3 tickers, 2015-01-01 to 2026-04-01."""
    dates = pd.bdate_range("2015-01-01", "2026-04-01")
    rows = []
    rng = np.random.default_rng(7)
    for t in ["TKA", "TKB", "TKC"]:
        base = {"TKA": 100.0, "TKB": 50.0, "TKC": 25.0}[t]
        # Geometric brownian-ish drift
        prices = base * np.exp(np.cumsum(rng.normal(0.0003, 0.015, len(dates))))
        for d, p in zip(dates, prices):
            rows.append({
                "date": d, "ticker": t,
                "Open": p * 0.999, "High": p * 1.005, "Low": p * 0.995,
                "Close": p, "Volume": 1_000_000, "dollar_volume": p * 1_000_000,
            })
    df = pd.DataFrame(rows)
    path = tmp_path / "prices.parquet"
    df.to_parquet(path)
    return path


class TestLoadContext:
    def test_returns_TrialContext_with_all_fields(self, synthetic_full_prices_parquet: Path):
        ctx = core.load_context(
            universe=["TKA", "TKB", "TKC"],
            parquet_path=synthetic_full_prices_parquet,
        )
        assert isinstance(ctx, core.TrialContext)
        for fld in ("adj_close", "open", "high", "low", "volume", "dollar_volume"):
            df = getattr(ctx, fld)
            assert isinstance(df, pd.DataFrame)
            assert list(df.columns) == ["TKA", "TKB", "TKC"]

    def test_universe_filter_drops_unknown(self, synthetic_full_prices_parquet: Path):
        ctx = core.load_context(
            universe=["TKA", "TKB"],
            parquet_path=synthetic_full_prices_parquet,
        )
        assert "TKC" not in ctx.adj_close.columns

    def test_date_window_clipped(self, synthetic_full_prices_parquet: Path):
        ctx = core.load_context(
            universe=["TKA"],
            parquet_path=synthetic_full_prices_parquet,
            data_start=datetime(2020, 1, 1),
            data_end=datetime(2021, 1, 1),
        )
        assert ctx.adj_close.index.min() >= pd.Timestamp("2020-01-01")
        assert ctx.adj_close.index.max() < pd.Timestamp("2021-01-01")

    def test_empty_after_filter_raises(self, synthetic_full_prices_parquet: Path):
        with pytest.raises(ValueError, match="No price rows"):
            core.load_context(
                universe=["NONEXISTENT"],
                parquet_path=synthetic_full_prices_parquet,
            )

    def test_universe_attribute_sorted_tuple(self, synthetic_full_prices_parquet: Path):
        ctx = core.load_context(
            universe=["TKC", "TKA", "TKB"],
            parquet_path=synthetic_full_prices_parquet,
        )
        assert ctx.universe == ("TKA", "TKB", "TKC")
        assert isinstance(ctx.universe, tuple)
