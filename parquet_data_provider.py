"""Bridge: prices.parquet -> qf-lib PresetDataProvider.

Loads the OHLCV parquet into a QFDataArray and wraps it as a PresetDataProvider
so qf-lib backtests can consume it via set_data_provider().
"""
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence

import numpy as np
import pandas as pd

from qf_lib.common.enums.frequency import Frequency
from qf_lib.common.enums.price_field import PriceField
from qf_lib.common.tickers.tickers import YFinanceTicker
from qf_lib.containers.qf_data_array import QFDataArray
from qf_lib.data_providers.preset_data_provider import PresetDataProvider


FIELD_TO_PRICE_FIELD = {
    "Open": PriceField.Open,
    "High": PriceField.High,
    "Low": PriceField.Low,
    "Close": PriceField.Close,
    "Volume": PriceField.Volume,
}


def load_prices_as_data_array(
    parquet_path: Path,
    tickers_subset: Optional[Iterable[str]] = None,
) -> QFDataArray:
    """Read the long-format prices parquet and return a 3D QFDataArray
    indexed by (date, ticker, field)."""
    df = pd.read_parquet(parquet_path, columns=["date", "ticker", *FIELD_TO_PRICE_FIELD.keys()])
    df["date"] = pd.to_datetime(df["date"])

    if tickers_subset is not None:
        wanted = set(tickers_subset)
        df = df[df["ticker"].isin(wanted)]

    if df.empty:
        raise ValueError("No price rows after filtering.")

    dates = pd.DatetimeIndex(sorted(df["date"].unique()))
    ticker_strs: Sequence[str] = sorted(df["ticker"].unique())
    qf_tickers = [YFinanceTicker(t) for t in ticker_strs]
    fields = list(FIELD_TO_PRICE_FIELD.keys())
    price_fields = [FIELD_TO_PRICE_FIELD[f] for f in fields]

    df = df.set_index(["date", "ticker"])
    arr = np.full((len(dates), len(ticker_strs), len(fields)), np.nan, dtype=np.float64)
    for f_idx, field in enumerate(fields):
        wide = (
            df[field]
            .unstack("ticker")
            .reindex(index=dates, columns=ticker_strs)
        )
        arr[:, :, f_idx] = wide.values

    return QFDataArray.create(
        dates=dates,
        tickers=qf_tickers,
        fields=price_fields,
        data=arr,
    )


def build_data_provider(
    parquet_path: Path,
    start_date: datetime,
    end_date: datetime,
    tickers_subset: Optional[Iterable[str]] = None,
) -> PresetDataProvider:
    """Convenience constructor."""
    arr = load_prices_as_data_array(parquet_path, tickers_subset=tickers_subset)
    return PresetDataProvider(
        data=arr,
        start_date=start_date,
        end_date=end_date,
        frequency=Frequency.DAILY,
    )


if __name__ == "__main__":
    from config import PRICES_PATH

    print("Loading prices.parquet -> QFDataArray ...")
    arr = load_prices_as_data_array(PRICES_PATH)
    print(f"Shape: {arr.shape} (dates, tickers, fields)")
    print(f"Dates: {pd.Timestamp(arr.dates.values[0]).date()} -> "
          f"{pd.Timestamp(arr.dates.values[-1]).date()}")
    print(f"Tickers: {len(arr.tickers.values):,}")
    print(f"Fields: {[f.name for f in arr.fields.values]}")
    print(f"Memory: {arr.nbytes / 1e6:.0f} MB")

    aapl = arr.sel(tickers=YFinanceTicker("AAPL")).to_pandas().tail(3)
    print("\nAAPL last 3 days:")
    print(aapl)
