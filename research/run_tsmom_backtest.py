"""Driver for TS-momentum backtest using qf-lib's full BacktestTradingSession.

Output (trade logs, stats CSV/Excel, EOD series) is auto-generated under
research/us_universe/output/backtesting/. PDF tearsheet is stubbed (system
cairo/pango not installed); install via brew to enable real PDFs.
"""
import logging
import os
from datetime import datetime
from pathlib import Path

# Set qf-lib starting dir before any qf-lib import (used to resolve relative
# paths in settings.json such as output_directory).
_HERE = Path(__file__).parent.resolve()
os.environ.setdefault("QF_STARTING_DIRECTORY", str(_HERE))

from alpha_lab import _weasyprint_stub  # noqa: F401  — must precede any qf-lib import

import matplotlib
matplotlib.use("Agg")  # headless

import pandas as pd

from qf_lib.common.utils.logging.logging_config import setup_logging
setup_logging(logging.INFO)

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

from config import PRICES_PATH
from alpha_lab.parquet_data_provider import build_data_provider
from tsmom_alpha_model import TSMomentumAlphaModel


# ----- backtest knobs -----
START_DATE = datetime(2018, 1, 1)
END_DATE = datetime(2024, 12, 31)
UNIVERSE_SIZE = 300
LOOKBACK_DAYS = 252
SKIP_DAYS = 21
THRESHOLD = 0.05
RISK_FACTOR = 1.5
PER_POSITION_PCT = 1.0 / UNIVERSE_SIZE   # equal weight per name
BACKTEST_NAME = "TSMom 12-1 Top300 demo"


def select_universe(parquet_path: Path, n: int, min_history_before: datetime,
                    min_bars: int) -> list[str]:
    """Top-N tickers by all-time mean ADV, restricted to those with at least
    `min_bars` daily bars before `min_history_before`."""
    df = pd.read_parquet(parquet_path, columns=["date", "ticker", "dollar_volume"])
    df["date"] = pd.to_datetime(df["date"])
    pre = df[df["date"] < min_history_before]
    eligible = pre.groupby("ticker").size()
    eligible = eligible[eligible >= min_bars].index
    df = df[df["ticker"].isin(eligible)]
    avg = df.groupby("ticker")["dollar_volume"].mean()
    return avg.nlargest(n).index.tolist()


def main() -> None:
    print(f"Universe: top {UNIVERSE_SIZE} by all-time ADV (history-filtered)")
    universe = select_universe(
        PRICES_PATH,
        UNIVERSE_SIZE,
        min_history_before=START_DATE,
        min_bars=LOOKBACK_DAYS + SKIP_DAYS + 5,
    )
    print("  ", ", ".join(universe[:10]), "...")

    print("Building data provider ...")
    # Pad start by ~1.5 years so qf-lib's data preloading + 12m signal warmup
    # window has data available before the backtest begins.
    data_start = datetime(START_DATE.year - 2, START_DATE.month, START_DATE.day)
    data_provider = build_data_provider(
        PRICES_PATH,
        start_date=data_start,
        end_date=END_DATE,
        tickers_subset=universe,
    )

    settings_path = _HERE.parent / "config_files" / "settings.json"   # config_files at repo root
    secret_path = _HERE.parent / "config_files" / "secret_settings.json"
    settings = Settings(str(settings_path), str(secret_path))
    pdf_exporter = PDFExporter(settings)
    excel_exporter = ExcelExporter(settings)

    sb = BacktestTradingSessionBuilder(settings, pdf_exporter, excel_exporter)
    sb.set_data_provider(data_provider)
    sb.set_backtest_name(BACKTEST_NAME)
    sb.set_position_sizer(FixedPortfolioPercentagePositionSizer, fixed_percentage=PER_POSITION_PCT)
    sb.set_commission_model(IBCommissionModel)
    sb.set_frequency(Frequency.DAILY)

    print("Building session ...")
    ts = sb.build(START_DATE, END_DATE)

    model = TSMomentumAlphaModel(
        lookback_days=LOOKBACK_DAYS,
        skip_days=SKIP_DAYS,
        threshold=THRESHOLD,
        risk_estimation_factor=RISK_FACTOR,
        data_provider=ts.data_provider,
    )
    model_tickers = [YFinanceTicker(t) for t in universe]
    model_tickers_dict = {model: model_tickers}

    ts.use_data_preloading(model_tickers)

    strategy = AlphaModelStrategy(ts, model_tickers_dict, use_stop_losses=False)
    CalculateAndPlaceOrdersRegularEvent.set_daily_default_trigger_time()
    CalculateAndPlaceOrdersRegularEvent.exclude_weekends()
    strategy.subscribe(CalculateAndPlaceOrdersRegularEvent)

    print("Starting backtest ...")
    ts.start_trading()

    eod = ts.portfolio.portfolio_eod_series()
    daily_log = eod.to_log_returns()
    print(f"\nFinal value: {eod.iloc[-1]:.2f}")
    print(f"Mean daily log return:  {daily_log.mean():.6f}")
    print(f"Std of daily log return: {daily_log.std():.6f}")
    print(f"\nTearsheet & logs -> {_HERE / 'output' / 'backtesting'}")


if __name__ == "__main__":
    main()
