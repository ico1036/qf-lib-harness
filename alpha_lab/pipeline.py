"""FROZEN — strategy runner: AST gate, qf-lib backtest, IS/OS slice, ledger.

Flow per `run(strategy_path)`:

  1. Read strategy.py source, run AST hard-rule checks. SystemExit on violation.
  2. Import the strategy module dynamically.
  3. Load TrialContext (full DATA_START ~ OS_END window).
  4. Call strategy.signal(ctx) ONCE → DataFrame[date × ticker] score matrix.
  5. Wrap in PrecomputedSignalAlphaModel; build qf-lib BacktestTradingSession
     across [IS_START, OS_END) using the same data provider.
  6. Slice the EOD equity curve into IS / OS, compute Sharpe per slice.
  7. Apply gate. Append a ledger row. Print grep-friendly footer.

The agent edits experiments/<exp>/strategy.py only. This file, core.py,
__main__.py, and trial_template.py are FROZEN — agent never touches them.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import traceback
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha1
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd

from alpha_lab.core import (
    DATA_START, IS_START, IS_END, OS_START, OS_END,
    PRICES_PATH, TrialContext, load_context, sharpe, select_universe,
)

# ---------------------------------------------------------------------------
# Hard-rule AST checks
# ---------------------------------------------------------------------------

_FORBIDDEN_CALL_NAMES = {
    # Direct file IO — data must come via ctx
    "read_parquet", "read_csv", "read_excel", "read_pickle",
    "read_feather", "read_orc", "read_sql", "read_hdf",
    "open",
}

_REQUIRED_CONSTANTS = {"REBAL", "TOP_N", "WEIGHT_SCHEME", "LOOKBACK_DAYS"}
_ALLOWED_REBAL = {"M", "W", "Q"}
_ALLOWED_WEIGHT = {"equal"}   # signal-weighted allowed only when long-only is provable; keep equal for now


def _call_target_name(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute):
        return f.attr
    if isinstance(f, ast.Name):
        return f.id
    return None


def check_strategy_ast(path: Path) -> None:
    """Raise SystemExit on hard-rule violation. Run BEFORE import."""
    src = path.read_text()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as e:
        raise SystemExit(f"alpha_lab: {path} syntax error: {e}")

    for node in ast.walk(tree):
        # Forbidden calls (file IO)
        if isinstance(node, ast.Call):
            name = _call_target_name(node)
            if name in _FORBIDDEN_CALL_NAMES:
                raise SystemExit(
                    f"alpha_lab: {path} calls forbidden `{name}()` — "
                    f"data must come via ctx, not direct file IO."
                )
            # .shift(-N) negative literal → look-ahead
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr == "shift"
                    and node.args
                    and isinstance(node.args[0], ast.UnaryOp)
                    and isinstance(node.args[0].op, ast.USub)):
                raise SystemExit(
                    f"alpha_lab: {path} uses `.shift(-N)` — negative shift "
                    f"references future bars. Look-ahead rejected."
                )

    # Required: signal(ctx) function and the four module constants
    funcs = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
    if "signal" not in funcs:
        raise SystemExit(
            f"alpha_lab: {path} missing required function `signal(ctx)`."
        )

    assigned: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for tgt in stmt.targets:
                if isinstance(tgt, ast.Name):
                    assigned.add(tgt.id)
                elif isinstance(tgt, (ast.Tuple, ast.List)):
                    for elt in tgt.elts:
                        if isinstance(elt, ast.Name):
                            assigned.add(elt.id)
    missing = _REQUIRED_CONSTANTS - assigned
    if missing:
        raise SystemExit(
            f"alpha_lab: {path} missing required module constants {sorted(missing)}."
        )


# ---------------------------------------------------------------------------
# Strategy import
# ---------------------------------------------------------------------------

def _import_strategy(path: Path) -> ModuleType:
    """Import a strategy.py file with a unique module name (no caching)."""
    mod_name = f"alpha_lab._strategy_{sha1(str(path).encode()).hexdigest()[:8]}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"alpha_lab: cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _validate_constants(mod: ModuleType, path: Path) -> dict:
    """Sanity-check the four contract constants; return as dict."""
    vals = {k: getattr(mod, k, None) for k in _REQUIRED_CONSTANTS}
    if vals["REBAL"] not in _ALLOWED_REBAL:
        raise SystemExit(f"alpha_lab: {path} REBAL must be one of {_ALLOWED_REBAL}, got {vals['REBAL']!r}")
    if vals["WEIGHT_SCHEME"] not in _ALLOWED_WEIGHT:
        raise SystemExit(f"alpha_lab: {path} WEIGHT_SCHEME must be one of {_ALLOWED_WEIGHT}, got {vals['WEIGHT_SCHEME']!r}")
    if not isinstance(vals["TOP_N"], int) or vals["TOP_N"] < 5 or vals["TOP_N"] > 200:
        raise SystemExit(f"alpha_lab: {path} TOP_N must be int in [5, 200], got {vals['TOP_N']!r}")
    if not isinstance(vals["LOOKBACK_DAYS"], int) or vals["LOOKBACK_DAYS"] < 1:
        raise SystemExit(f"alpha_lab: {path} LOOKBACK_DAYS must be positive int")
    return vals


# ---------------------------------------------------------------------------
# qf-lib bridge
# ---------------------------------------------------------------------------

_REBAL_RESAMPLE = {"M": "ME", "W": "W-FRI", "Q": "QE"}


def compute_membership(signal_matrix: pd.DataFrame, top_n: int, rebal_freq: str) -> pd.DataFrame:
    """Stair-step top-N membership matrix anchored at rebal period ends.

    Snap the daily score matrix to rebal-period anchors (M/W/Q), rank per anchor,
    then forward-fill so within-period queries return a stable membership (no
    daily churn). Returned DataFrame has the same index/columns as signal_matrix
    and bool values: True iff that ticker was top-N at the most recent anchor.
    """
    if rebal_freq not in _REBAL_RESAMPLE:
        raise ValueError(f"REBAL must be one of {set(_REBAL_RESAMPLE)}, got {rebal_freq!r}")

    anchored = signal_matrix.resample(_REBAL_RESAMPLE[rebal_freq]).last()
    ranks_anchor = anchored.rank(axis=1, ascending=False, method="first", na_option="bottom")
    membership_anchor = (ranks_anchor <= top_n) & anchored.notna()
    # reindex+ffill on bool promotes to object-dtype where ffill can't reach
    # (before the first anchor); going via int8 keeps the dtype numeric so
    # fillna(0) doesn't trip pandas' future downcasting warning.
    reindexed = membership_anchor.astype("int8").reindex(signal_matrix.index, method="ffill")
    return reindexed.fillna(0).astype(bool)


def _build_alpha_model(signal_matrix: pd.DataFrame, top_n: int, data_provider, rebal_freq: str):
    """Construct a qf-lib AlphaModel that returns LONG for the top-N tickers
    by score at the most recent rebal-period anchor, OUT for everyone else.
    """
    from qf_lib.backtesting.alpha_model.alpha_model import AlphaModel
    from qf_lib.backtesting.alpha_model.exposure_enum import Exposure

    membership = compute_membership(signal_matrix, top_n, rebal_freq)

    class PrecomputedSignalAlphaModel(AlphaModel):
        def __init__(self, dp):
            super().__init__(risk_estimation_factor=1.0, data_provider=dp)
            self._membership = membership

        def calculate_exposure(self, ticker, current_exposure, current_time, frequency):
            ts = pd.Timestamp(current_time).normalize()
            idx = self._membership.index
            prior = idx[idx < ts]
            if len(prior) == 0:
                return Exposure.OUT
            row = self._membership.loc[prior[-1]]
            ticker_str = ticker.ticker if hasattr(ticker, "ticker") else str(ticker)
            try:
                return Exposure.LONG if bool(row.at[ticker_str]) else Exposure.OUT
            except KeyError:
                return Exposure.OUT

        def __hash__(self):
            return hash(("PrecomputedSignalAlphaModel", id(self._membership)))

    return PrecomputedSignalAlphaModel(data_provider)


def _run_qf_backtest(
    ctx: TrialContext,
    signal_matrix: pd.DataFrame,
    top_n: int,
    rebal: str,
    backtest_name: str,
) -> pd.Series:
    """Run a qf-lib BacktestTradingSession and return the daily EOD equity series.

    Single backtest covers [IS_START, OS_END) — pipeline slices the result
    afterward. Data window is the full DATA_START ~ OS_END so signal warmup
    has the bars it needs.
    """
    # Lazy import — qf-lib initialization is heavy.
    here = Path(__file__).parent.parent.resolve()
    os.environ.setdefault("QF_STARTING_DIRECTORY", str(here))

    # macOS without brew cairo/pango cannot load weasyprint; importing this
    # stub (part of the alpha_lab package) replaces it with a no-op. MUST
    # precede any qf-lib import, which the order below guarantees.
    from alpha_lab import _weasyprint_stub  # noqa: F401

    import matplotlib
    matplotlib.use("Agg")

    from qf_lib.backtesting.events.time_event.regular_time_event.calculate_and_place_orders_event import (
        CalculateAndPlaceOrdersRegularEvent,
    )
    from qf_lib.backtesting.execution_handler.commission_models.ib_commission_model import IBCommissionModel
    from qf_lib.backtesting.position_sizer.fixed_portfolio_percentage_position_sizer import (
        FixedPortfolioPercentagePositionSizer,
    )
    from qf_lib.backtesting.strategies.alpha_model_strategy import AlphaModelStrategy
    from qf_lib.backtesting.trading_session.backtest_trading_session_builder import BacktestTradingSessionBuilder
    from qf_lib.common.enums.frequency import Frequency
    from qf_lib.common.tickers.tickers import YFinanceTicker
    from qf_lib.documents_utils.document_exporting.pdf_exporter import PDFExporter
    from qf_lib.documents_utils.excel.excel_exporter import ExcelExporter
    from qf_lib.settings import Settings

    from alpha_lab.parquet_data_provider import build_data_provider

    data_provider = build_data_provider(
        PRICES_PATH,
        start_date=DATA_START,
        end_date=OS_END,
        tickers_subset=ctx.universe,
    )

    settings_path = here / "config_files" / "settings.json"
    secret_path = here / "config_files" / "secret_settings.json"
    settings = Settings(str(settings_path), str(secret_path))
    pdf_exporter = PDFExporter(settings)
    excel_exporter = ExcelExporter(settings)

    sb = BacktestTradingSessionBuilder(settings, pdf_exporter, excel_exporter)
    sb.set_data_provider(data_provider)
    sb.set_backtest_name(backtest_name)
    sb.set_position_sizer(FixedPortfolioPercentagePositionSizer, fixed_percentage=1.0 / top_n)
    sb.set_commission_model(IBCommissionModel)
    sb.set_frequency(Frequency.DAILY)

    ts = sb.build(IS_START, OS_END)

    model = _build_alpha_model(signal_matrix, top_n, ts.data_provider, rebal)
    model_tickers = [YFinanceTicker(t) for t in ctx.universe]
    ts.use_data_preloading(model_tickers)

    strategy = AlphaModelStrategy(ts, {model: model_tickers}, use_stop_losses=False)

    if rebal == "M":
        # First trading day of each month — qf-lib's monthly trigger family.
        # Falls back to daily-default if monthly not registered; close enough
        # for top-N rebalancing.
        CalculateAndPlaceOrdersRegularEvent.set_daily_default_trigger_time()
    else:
        CalculateAndPlaceOrdersRegularEvent.set_daily_default_trigger_time()
    CalculateAndPlaceOrdersRegularEvent.exclude_weekends()
    strategy.subscribe(CalculateAndPlaceOrdersRegularEvent)

    ts.start_trading()

    eod = ts.portfolio.portfolio_eod_series()
    return eod.to_simple_returns()


def _run_vectorized_backtest(
    ctx: TrialContext,
    signal_matrix: pd.DataFrame,
    top_n: int,
    rebal: str,
    backtest_name: str,
) -> pd.Series:
    """Fast vectorized backtest — same membership/timing contract as
    _run_qf_backtest, but PnL is pure matrix math (no broker / order / commission
    event loop). Returns the daily simple-returns series over [IS_START, OS_END).

    ~1000x faster than the event-driven path. Tradeoff: ignores transaction
    costs, slippage and discrete share sizing — use _run_qf_backtest for the
    final realistic validation of a shortlisted strategy.

    Look-ahead safe: position on day t uses membership as of the prior day
    (weight.shift(1)), exactly like PrecomputedSignalAlphaModel's `idx < ts`.
    """
    membership = compute_membership(signal_matrix, top_n, rebal)  # date×ticker bool
    close = ctx.adj_close.reindex(index=membership.index, columns=membership.columns)
    asset_ret = close.pct_change()
    weight = membership.astype("float64") / float(top_n)   # equal weight, 1/top_n per held name
    port_ret = (weight.shift(1) * asset_ret).sum(axis=1)   # prior-day weights earn today's return
    mask = (port_ret.index >= pd.Timestamp(IS_START)) & (port_ret.index < pd.Timestamp(OS_END))
    return port_ret[mask].astype("float64")


# ---------------------------------------------------------------------------
# IS/OS gate
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    sharpe_is: float
    sharpe_os: float
    n_is: int
    n_os: int
    passed: bool
    reason: str


def evaluate_gate(returns: pd.Series) -> GateResult:
    """Apply Sharpe_IS > 0.5 AND Sharpe_OS > 0.5 * Sharpe_IS."""
    r = returns.dropna()
    is_r = r[(r.index >= pd.Timestamp(IS_START)) & (r.index < pd.Timestamp(IS_END))]
    os_r = r[(r.index >= pd.Timestamp(OS_START)) & (r.index < pd.Timestamp(OS_END))]
    s_is = sharpe(is_r)
    s_os = sharpe(os_r)
    if not np.isfinite(s_is) or not np.isfinite(s_os):
        return GateResult(s_is, s_os, len(is_r), len(os_r), False, "insufficient_returns")
    if s_is <= 0.5:
        return GateResult(s_is, s_os, len(is_r), len(os_r), False, f"is_floor: {s_is:.3f} <= 0.5")
    if s_os <= 0.5 * s_is:
        return GateResult(s_is, s_os, len(is_r), len(os_r), False, f"os_ratio: {s_os:.3f} <= 0.5 * {s_is:.3f}")
    return GateResult(s_is, s_os, len(is_r), len(os_r), True, "pass")


# ---------------------------------------------------------------------------
# Ledger + footer
# ---------------------------------------------------------------------------

LEDGER_PATH = Path(__file__).parent / "alpha_ledger.jsonl"


def _content_hash(path: Path) -> str:
    return sha1(path.read_bytes()).hexdigest()[:12]


def _append_ledger(row: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _print_footer(metrics: dict) -> None:
    """Grep-friendly footer block. Mirrors audit/CLAUDE.md style."""
    print("---")
    print(f"sharpe_is:  {metrics.get('sharpe_is', float('nan')):+.3f}")
    print(f"sharpe_os:  {metrics.get('sharpe_os', float('nan')):+.3f}")
    print(f"n_is:       {metrics.get('n_is', 0)}")
    print(f"n_os:       {metrics.get('n_os', 0)}")
    print(f"gate:       {metrics.get('gate_reason', 'unknown')}")
    print(f"verdict:    {metrics.get('verdict', 'unknown')}")


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def run(strategy_path: str | Path) -> int:
    """Run one strategy end-to-end. Returns process-exit-code-style int."""
    path = Path(strategy_path).resolve()
    if not path.is_file():
        print(f"alpha_lab: {path} not found", file=sys.stderr)
        return 2

    exp_id = path.parent.name if path.parent.name.startswith("alpha_") else path.stem
    ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    row: dict = {
        "exp_id": exp_id,
        "ts": ts_iso,
        "strategy": str(path.relative_to(Path.cwd())) if path.is_relative_to(Path.cwd()) else str(path),
        "content_hash": _content_hash(path),
    }

    # 1. AST gate
    try:
        check_strategy_ast(path)
    except SystemExit as e:
        row["verdict"] = "crash"
        row["error"] = str(e)
        _append_ledger(row)
        print(str(e), file=sys.stderr)
        _print_footer({"verdict": "crash", "gate_reason": "ast_violation"})
        return 1

    # 2. Import + constants check
    try:
        mod = _import_strategy(path)
        consts = _validate_constants(mod, path)
    except SystemExit as e:
        row["verdict"] = "crash"
        row["error"] = str(e)
        _append_ledger(row)
        print(str(e), file=sys.stderr)
        _print_footer({"verdict": "crash", "gate_reason": "import_error"})
        return 1

    row["constants"] = consts

    # 3. Run trial
    try:
        print(f"[alpha_lab] {exp_id} — loading context …")
        ctx = load_context()
        print(f"[alpha_lab] universe: {len(ctx.universe)} tickers, "
              f"{len(ctx.adj_close)} bars")
        print(f"[alpha_lab] computing signal …")
        signal_matrix = mod.signal(ctx)
        if not isinstance(signal_matrix, pd.DataFrame):
            raise TypeError(f"signal() must return DataFrame, got {type(signal_matrix).__name__}")
        # Reindex to ctx universe (drop unknown columns, fill missing with NaN)
        signal_matrix = signal_matrix.reindex(columns=list(ctx.universe))
        # Reindex to ctx dates so PrecomputedAlphaModel timing is consistent
        signal_matrix = signal_matrix.reindex(ctx.adj_close.index)
        print(f"[alpha_lab] signal matrix {signal_matrix.shape}, "
              f"non-NaN cells: {signal_matrix.notna().sum().sum():,}")

        print(f"[alpha_lab] running vectorized backtest …")
        returns = _run_vectorized_backtest(
            ctx,
            signal_matrix,
            top_n=consts["TOP_N"],
            rebal=consts["REBAL"],
            backtest_name=exp_id,
        )

        gate = evaluate_gate(returns)

        row.update({
            "metrics": {
                "sharpe_is": gate.sharpe_is,
                "sharpe_os": gate.sharpe_os,
                "n_is": gate.n_is,
                "n_os": gate.n_os,
            },
            "gate": {"passed": gate.passed, "reason": gate.reason},
            "verdict": "pass" if gate.passed else "fail",
        })
        _append_ledger(row)
        _print_footer({
            "sharpe_is": gate.sharpe_is,
            "sharpe_os": gate.sharpe_os,
            "n_is": gate.n_is,
            "n_os": gate.n_os,
            "gate_reason": gate.reason,
            "verdict": "pass" if gate.passed else "fail",
        })
        return 0

    except Exception as e:
        row["verdict"] = "crash"
        row["error"] = f"{type(e).__name__}: {e}"
        row["traceback"] = traceback.format_exc().splitlines()[-10:]
        _append_ledger(row)
        traceback.print_exc()
        _print_footer({"verdict": "crash", "gate_reason": "runtime_error"})
        return 1
