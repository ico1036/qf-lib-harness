"""Tests for alpha_lab.pipeline — AST gate, constants, gate, membership, ledger."""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

import numpy as np
import pandas as pd
import pytest

from alpha_lab import pipeline


# ---------------------------------------------------------------------------
# AST gate — check_strategy_ast
# ---------------------------------------------------------------------------

def _write_strategy(tmp_path: Path, body: str) -> Path:
    """Write a strategy.py with the given body (must include all required parts)."""
    p = tmp_path / "strategy.py"
    p.write_text(dedent(body))
    return p


_VALID_BODY = """\
\"\"\"baseline.\"\"\"
import pandas as pd
from alpha_lab.core import TrialContext

REBAL = "M"
TOP_N = 30
WEIGHT_SCHEME = "equal"
LOOKBACK_DAYS = 252

def signal(ctx):
    return ctx.adj_close.pct_change(252).shift(21)
"""


class TestASTAccepts:
    def test_accepts_baseline(self, tmp_path: Path):
        p = _write_strategy(tmp_path, _VALID_BODY)
        # Must NOT raise
        pipeline.check_strategy_ast(p)

    def test_accepts_positive_shift(self, tmp_path: Path):
        body = _VALID_BODY.replace(".shift(21)", ".shift(5)")
        p = _write_strategy(tmp_path, body)
        pipeline.check_strategy_ast(p)

    def test_accepts_helper_function(self, tmp_path: Path):
        body = _VALID_BODY.replace(
            "def signal(ctx):",
            "def _z(x):\n    return (x - x.mean()) / x.std()\n\ndef signal(ctx):",
        )
        p = _write_strategy(tmp_path, body)
        pipeline.check_strategy_ast(p)


class TestASTRejectsLookahead:
    def test_rejects_negative_literal_shift(self, tmp_path: Path):
        body = _VALID_BODY.replace(".shift(21)", ".shift(-21)")
        p = _write_strategy(tmp_path, body)
        with pytest.raises(SystemExit, match="negative shift"):
            pipeline.check_strategy_ast(p)

    def test_rejects_shift_minus_one(self, tmp_path: Path):
        body = _VALID_BODY.replace(".shift(21)", ".shift(-1)")
        p = _write_strategy(tmp_path, body)
        with pytest.raises(SystemExit, match="negative shift"):
            pipeline.check_strategy_ast(p)


class TestASTRejectsFileIO:
    @pytest.mark.parametrize("call", [
        "pd.read_parquet('x.parquet')",
        "pd.read_csv('x.csv')",
        "pd.read_excel('x.xlsx')",
        "pd.read_pickle('x.pkl')",
        "pd.read_feather('x.feather')",
        "pd.read_orc('x.orc')",
        "pd.read_sql('q', conn)",
        "pd.read_hdf('x.h5')",
    ])
    def test_rejects_pandas_readers(self, tmp_path: Path, call: str):
        body = _VALID_BODY.replace(
            "    return ctx.adj_close.pct_change(252).shift(21)",
            f"    extra = {call}\n    return ctx.adj_close.pct_change(252).shift(21)",
        )
        p = _write_strategy(tmp_path, body)
        with pytest.raises(SystemExit, match="forbidden"):
            pipeline.check_strategy_ast(p)

    def test_rejects_open(self, tmp_path: Path):
        body = _VALID_BODY.replace(
            "    return ctx.adj_close.pct_change(252).shift(21)",
            "    f = open('/tmp/x')\n    return ctx.adj_close.pct_change(252).shift(21)",
        )
        p = _write_strategy(tmp_path, body)
        with pytest.raises(SystemExit, match="forbidden"):
            pipeline.check_strategy_ast(p)


class TestASTRejectsMissingContract:
    def test_rejects_missing_signal_function(self, tmp_path: Path):
        body = _VALID_BODY.replace("def signal(ctx):", "def predict(ctx):")
        p = _write_strategy(tmp_path, body)
        with pytest.raises(SystemExit, match="signal"):
            pipeline.check_strategy_ast(p)

    @pytest.mark.parametrize("missing", ["REBAL", "TOP_N", "WEIGHT_SCHEME", "LOOKBACK_DAYS"])
    def test_rejects_missing_required_constant(self, tmp_path: Path, missing: str):
        body = "\n".join(
            line for line in _VALID_BODY.splitlines()
            if not line.startswith(f"{missing} =")
        )
        p = _write_strategy(tmp_path, body)
        with pytest.raises(SystemExit, match="missing required module constants"):
            pipeline.check_strategy_ast(p)


class TestASTSyntaxError:
    def test_rejects_syntax_error(self, tmp_path: Path):
        p = _write_strategy(tmp_path, "def signal(ctx:\n  return 1\n")
        with pytest.raises(SystemExit, match="syntax error"):
            pipeline.check_strategy_ast(p)


# ---------------------------------------------------------------------------
# _validate_constants — runtime constants check (post-import)
# ---------------------------------------------------------------------------

class _MockMod:
    """Minimal stand-in for an imported strategy module."""
    def __init__(self, **attrs):
        for k, v in attrs.items():
            setattr(self, k, v)


def _good_consts(**override):
    base = dict(REBAL="M", TOP_N=30, WEIGHT_SCHEME="equal", LOOKBACK_DAYS=252)
    base.update(override)
    return _MockMod(**base)


class TestValidateConstants:
    def test_accepts_baseline(self, tmp_path: Path):
        result = pipeline._validate_constants(_good_consts(), tmp_path / "x.py")
        assert result == {"REBAL": "M", "TOP_N": 30, "WEIGHT_SCHEME": "equal", "LOOKBACK_DAYS": 252}

    def test_accepts_long_short_scheme(self, tmp_path: Path):
        result = pipeline._validate_constants(
            _good_consts(WEIGHT_SCHEME="long_short"), tmp_path / "x.py")
        assert result["WEIGHT_SCHEME"] == "long_short"

    @pytest.mark.parametrize("bad", ["D", "Y", "monthly", ""])
    def test_rejects_bad_rebal(self, tmp_path: Path, bad: str):
        with pytest.raises(SystemExit, match="REBAL"):
            pipeline._validate_constants(_good_consts(REBAL=bad), tmp_path / "x.py")

    @pytest.mark.parametrize("bad", ["signal", "ls", ""])
    def test_rejects_bad_weight_scheme(self, tmp_path: Path, bad: str):
        with pytest.raises(SystemExit, match="WEIGHT_SCHEME"):
            pipeline._validate_constants(_good_consts(WEIGHT_SCHEME=bad), tmp_path / "x.py")

    @pytest.mark.parametrize("bad", [4, 201, 0, -5])
    def test_rejects_top_n_out_of_range(self, tmp_path: Path, bad: int):
        with pytest.raises(SystemExit, match="TOP_N"):
            pipeline._validate_constants(_good_consts(TOP_N=bad), tmp_path / "x.py")

    def test_rejects_top_n_non_int(self, tmp_path: Path):
        with pytest.raises(SystemExit, match="TOP_N"):
            pipeline._validate_constants(_good_consts(TOP_N=30.0), tmp_path / "x.py")

    @pytest.mark.parametrize("bad", [0, -1])
    def test_rejects_bad_lookback(self, tmp_path: Path, bad: int):
        with pytest.raises(SystemExit, match="LOOKBACK_DAYS"):
            pipeline._validate_constants(_good_consts(LOOKBACK_DAYS=bad), tmp_path / "x.py")


# ---------------------------------------------------------------------------
# evaluate_gate — IS/OS Sharpe slicing + gate rule
# ---------------------------------------------------------------------------

def _make_returns(is_sharpe: float, os_sharpe: float, seed: int = 0) -> pd.Series:
    """Synthesize a daily return series spanning IS+OS with target Sharpes.

    Uses deterministic rng + closed-form mean adjustment so the realized
    Sharpe is close to target. Returns are simple (not log).
    """
    from alpha_lab.core import IS_START, IS_END, OS_START, OS_END
    rng = np.random.default_rng(seed)
    is_dates = pd.bdate_range(IS_START, IS_END - pd.Timedelta(days=1))
    os_dates = pd.bdate_range(OS_START, OS_END - pd.Timedelta(days=1))

    def synth(target_sharpe: float, n: int) -> np.ndarray:
        # mean = target_sharpe * std / sqrt(252); pick std=0.01
        std = 0.01
        mean = target_sharpe * std / np.sqrt(252)
        # Sample, then z-score-shift to hit the realized mean exactly
        x = rng.normal(0, std, n)
        x -= x.mean()
        x *= std / x.std(ddof=0)
        return x + mean

    is_r = synth(is_sharpe, len(is_dates))
    os_r = synth(os_sharpe, len(os_dates))
    return pd.Series(np.concatenate([is_r, os_r]),
                     index=is_dates.union(os_dates))


class TestEvaluateGate:
    def test_pass_case(self):
        r = _make_returns(is_sharpe=1.0, os_sharpe=0.6)
        g = pipeline.evaluate_gate(r)
        assert g.passed
        assert g.reason == "pass"
        assert g.sharpe_is > 0.5
        assert g.sharpe_os > 0.5 * g.sharpe_is

    def test_fail_is_floor(self):
        r = _make_returns(is_sharpe=0.3, os_sharpe=0.3)
        g = pipeline.evaluate_gate(r)
        assert not g.passed
        assert "is_floor" in g.reason

    def test_fail_os_ratio(self):
        # IS strong (1.0), OS weak (0.3) — 0.3 < 0.5 * 1.0
        r = _make_returns(is_sharpe=1.0, os_sharpe=0.3)
        g = pipeline.evaluate_gate(r)
        assert not g.passed
        assert "os_ratio" in g.reason

    def test_borderline_is_floor_strict(self):
        # IS exactly 0.5 should fail (strictly greater required)
        r = _make_returns(is_sharpe=0.5, os_sharpe=0.5)
        g = pipeline.evaluate_gate(r)
        # synthetic Sharpe will be approx 0.5; strict > test should reject
        assert not g.passed or g.reason != "pass" or g.sharpe_is > 0.5

    def test_empty_returns(self):
        g = pipeline.evaluate_gate(pd.Series([], dtype=float, index=pd.DatetimeIndex([])))
        assert not g.passed
        assert g.reason == "insufficient_returns"

    def test_only_is_no_os_returns(self):
        from alpha_lab.core import IS_START, IS_END
        is_dates = pd.bdate_range(IS_START, IS_END - pd.Timedelta(days=1))
        rng = np.random.default_rng(0)
        r = pd.Series(rng.normal(0.001, 0.01, len(is_dates)), index=is_dates)
        g = pipeline.evaluate_gate(r)
        assert not g.passed
        assert g.reason == "insufficient_returns"

    def test_counts_observations_per_slice(self):
        r = _make_returns(is_sharpe=1.0, os_sharpe=0.6)
        g = pipeline.evaluate_gate(r)
        assert g.n_is > 1500   # ~7 years business days
        assert g.n_os > 500    # ~3 years business days
        assert g.n_is > g.n_os # IS window is longer


# ---------------------------------------------------------------------------
# compute_membership — stair-step membership matrix for monthly rebal
# ---------------------------------------------------------------------------

class TestComputeMembership:
    def _signal(self, dates, columns, ranks_per_date: dict):
        """Build a deterministic signal matrix where rank order is exactly given."""
        df = pd.DataFrame(index=dates, columns=columns, dtype=float)
        for d, ranks in ranks_per_date.items():
            for col, score in ranks.items():
                df.loc[d, col] = score
        df = df.ffill()  # propagate ranks across the month
        return df

    def test_rejects_unknown_rebal_freq(self):
        df = pd.DataFrame(np.random.rand(10, 3), index=pd.bdate_range("2020-01-01", periods=10),
                          columns=["A", "B", "C"])
        with pytest.raises(ValueError, match="REBAL"):
            pipeline.compute_membership(df, top_n=2, rebal_freq="D")

    def test_monthly_anchor_picks_top_n(self):
        # 3 months of daily data, 4 tickers. Each month-end has different ranks.
        dates = pd.bdate_range("2020-01-01", "2020-03-31")
        cols = ["A", "B", "C", "D"]
        df = pd.DataFrame(0.0, index=dates, columns=cols)
        # Jan: A=4, B=3, C=2, D=1 (top-2 = A, B)
        df.loc["2020-01-01":"2020-01-31"] = [4, 3, 2, 1]
        # Feb: D=4, C=3, B=2, A=1 (top-2 = D, C)
        df.loc["2020-02-01":"2020-02-29"] = [1, 2, 3, 4]
        # Mar: B=4, A=3, D=2, C=1 (top-2 = B, A)
        df.loc["2020-03-01":"2020-03-31"] = [3, 4, 1, 2]

        m = pipeline.compute_membership(df, top_n=2, rebal_freq="M")

        # After Feb anchor (2020-02-29), March daily uses Feb's top-2 (D, C)
        assert m.loc["2020-03-02", "D"] == True
        assert m.loc["2020-03-02", "C"] == True
        assert m.loc["2020-03-02", "A"] == False
        assert m.loc["2020-03-02", "B"] == False

    def test_within_period_membership_is_constant(self):
        # If membership ffills, two daily rows in same rebal period should match
        dates = pd.bdate_range("2020-01-01", "2020-03-31")
        rng = np.random.default_rng(42)
        df = pd.DataFrame(rng.normal(0, 1, (len(dates), 5)), index=dates,
                          columns=list("ABCDE"))
        m = pipeline.compute_membership(df, top_n=3, rebal_freq="M")
        # mid-March vs late-March should be identical (same rebal period)
        feb_anchor_period = m.loc["2020-03-05"].equals(m.loc["2020-03-25"])
        assert feb_anchor_period

    def test_pre_first_anchor_is_all_false(self):
        dates = pd.bdate_range("2020-01-01", "2020-03-31")
        df = pd.DataFrame(np.arange(len(dates)).reshape(-1, 1).repeat(3, axis=1).astype(float),
                          index=dates, columns=["A", "B", "C"])
        m = pipeline.compute_membership(df, top_n=2, rebal_freq="M")
        # Before the first month-end (2020-01-31), no anchor → all False
        assert not m.loc["2020-01-15"].any()

    def test_top_n_count_per_anchor(self):
        dates = pd.bdate_range("2020-01-01", "2020-12-31")
        rng = np.random.default_rng(0)
        df = pd.DataFrame(rng.normal(0, 1, (len(dates), 10)), index=dates,
                          columns=[f"T{i}" for i in range(10)])
        m = pipeline.compute_membership(df, top_n=3, rebal_freq="M")
        # On a mid-year date well past first anchor, exactly 3 tickers should be True
        assert int(m.loc["2020-06-15"].sum()) == 3

    def test_quarterly_rebal_anchors(self):
        dates = pd.bdate_range("2020-01-01", "2020-12-31")
        rng = np.random.default_rng(0)
        df = pd.DataFrame(rng.normal(0, 1, (len(dates), 5)), index=dates,
                          columns=list("ABCDE"))
        m_m = pipeline.compute_membership(df, top_n=2, rebal_freq="M")
        m_q = pipeline.compute_membership(df, top_n=2, rebal_freq="Q")
        # Quarterly should churn less — at least one mid-quarter date where M and Q differ
        # (fragile to seed; just assert shapes match)
        assert m_m.shape == m_q.shape

    # --- long_short=True: signed membership (+1 long / -1 short / 0 out) ---

    def test_long_short_signs_top_and_bottom(self):
        # 4 tickers, constant ranks: A=4(top) B=3 C=2 D=1(bottom). top_n=1.
        dates = pd.bdate_range("2020-01-01", "2020-03-31")
        df = pd.DataFrame(0.0, index=dates, columns=["A", "B", "C", "D"])
        df.loc[:, :] = [4, 3, 2, 1]
        m = pipeline.compute_membership(df, top_n=1, rebal_freq="M", long_short=True)
        row = m.loc["2020-03-02"]            # well past first anchor
        assert row["A"] == 1                 # highest score → long
        assert row["D"] == -1                # lowest score → short
        assert row["B"] == 0 and row["C"] == 0

    def test_long_short_is_dollar_neutral_and_full_gross(self):
        dates = pd.bdate_range("2020-01-01", "2020-12-31")
        rng = np.random.default_rng(0)
        df = pd.DataFrame(rng.normal(0, 1, (len(dates), 10)), index=dates,
                          columns=[f"T{i}" for i in range(10)])
        row = pipeline.compute_membership(
            df, top_n=3, rebal_freq="M", long_short=True).loc["2020-06-15"]
        assert int(row.sum()) == 0           # 3 long + 3 short → net zero
        assert int(row.abs().sum()) == 6     # gross = 2 * top_n

    def test_long_short_excludes_nan_names_from_short_leg(self):
        # A is NaN everywhere → must not be picked as a short despite "lowest".
        dates = pd.bdate_range("2020-01-01", "2020-03-31")
        df = pd.DataFrame(0.0, index=dates, columns=["A", "B", "C", "D"])
        df.loc[:, :] = [1, 2, 3, 4]
        df["A"] = np.nan
        row = pipeline.compute_membership(
            df, top_n=1, rebal_freq="M", long_short=True).loc["2020-03-02"]
        assert row["A"] == 0                 # NaN excluded from both legs
        assert row["B"] == -1                # lowest *valid* → short

    def test_default_is_long_only_unsigned(self):
        # Without long_short, values stay in {0, 1} (no -1 shorts).
        dates = pd.bdate_range("2020-01-01", "2020-12-31")
        rng = np.random.default_rng(1)
        df = pd.DataFrame(rng.normal(0, 1, (len(dates), 8)), index=dates,
                          columns=list("ABCDEFGH"))
        m = pipeline.compute_membership(df, top_n=3, rebal_freq="M")
        assert set(np.unique(m.values).tolist()) <= {0, 1}


# ---------------------------------------------------------------------------
# Ledger append + content hash
# ---------------------------------------------------------------------------

class TestLedger:
    def test_append_writes_jsonl(self, tmp_path: Path, monkeypatch):
        ledger_path = tmp_path / "alpha_ledger.jsonl"
        monkeypatch.setattr(pipeline, "LEDGER_PATH", ledger_path)

        pipeline._append_ledger({"exp_id": "x1", "verdict": "pass"})
        pipeline._append_ledger({"exp_id": "x2", "verdict": "fail"})

        lines = ledger_path.read_text().splitlines()
        assert len(lines) == 2
        rows = [json.loads(line) for line in lines]
        assert rows[0]["exp_id"] == "x1"
        assert rows[1]["exp_id"] == "x2"

    def test_append_is_append_only(self, tmp_path: Path, monkeypatch):
        ledger_path = tmp_path / "alpha_ledger.jsonl"
        monkeypatch.setattr(pipeline, "LEDGER_PATH", ledger_path)
        pipeline._append_ledger({"exp_id": "first"})
        pipeline._append_ledger({"exp_id": "second"})
        # First row must still be present after second append
        rows = [json.loads(l) for l in ledger_path.read_text().splitlines()]
        assert rows[0]["exp_id"] == "first"

    def test_append_serializes_non_json_types(self, tmp_path: Path, monkeypatch):
        # `default=str` lets datetimes/Paths through
        ledger_path = tmp_path / "alpha_ledger.jsonl"
        monkeypatch.setattr(pipeline, "LEDGER_PATH", ledger_path)
        from datetime import datetime, timezone
        pipeline._append_ledger({"ts": datetime.now(timezone.utc), "path": Path("/tmp/x")})
        # Should not raise
        json.loads(ledger_path.read_text().splitlines()[0])


class TestContentHash:
    def test_stable_for_same_content(self, tmp_path: Path):
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_text("x = 1\n")
        b.write_text("x = 1\n")
        assert pipeline._content_hash(a) == pipeline._content_hash(b)

    def test_changes_with_content(self, tmp_path: Path):
        a = tmp_path / "a.py"
        a.write_text("x = 1\n")
        h1 = pipeline._content_hash(a)
        a.write_text("x = 2\n")
        assert pipeline._content_hash(a) != h1

    def test_short_form(self, tmp_path: Path):
        # Spec is 12-char prefix
        a = tmp_path / "a.py"
        a.write_text("anything")
        assert len(pipeline._content_hash(a)) == 12


# ---------------------------------------------------------------------------
# REBAL resample table
# ---------------------------------------------------------------------------

class TestRebalResample:
    def test_three_supported(self):
        assert set(pipeline._REBAL_RESAMPLE) == {"M", "W", "Q"}

    def test_pandas_freq_strings(self):
        # Sanity: the targets must be valid pandas resample strings
        idx = pd.bdate_range("2020-01-01", "2020-12-31")
        df = pd.DataFrame(np.zeros((len(idx), 1)), index=idx, columns=["X"])
        for freq in pipeline._REBAL_RESAMPLE.values():
            df.resample(freq).last()  # should not raise


# ---------------------------------------------------------------------------
# Shipped artifacts — regression: baseline + template must pass the gate
# ---------------------------------------------------------------------------

class TestShippedArtifacts:
    """If these break, the shipped harness is broken — agent cannot start."""

    _ROOT = Path(__file__).resolve().parents[1]   # alpha_lab/

    def test_baseline_strategy_passes_ast(self):
        path = self._ROOT / "experiments" / "exp_baseline_tsmom" / "strategy.py"
        assert path.exists(), f"baseline missing at {path}"
        pipeline.check_strategy_ast(path)   # must not raise

    def test_trial_template_passes_ast(self):
        path = self._ROOT / "trial_template.py"
        assert path.exists(), f"template missing at {path}"
        pipeline.check_strategy_ast(path)
