"""TS-Momentum AlphaModel — precompute-cached variant (strategy-side fix).

Same signal as TSMomentumAlphaModel, but instead of calling
data_provider.historical_price() per (ticker, bar), it precomputes the FULL
exposure panel once (vectorized), then calculate_exposure() is an O(1) asof
lookup. Look-ahead safe: exposure at date t uses only close[t-lookback..t-skip].
"""
from datetime import datetime
import numpy as np
import pandas as pd
from qf_lib.backtesting.alpha_model.alpha_model import AlphaModel
from qf_lib.backtesting.alpha_model.exposure_enum import Exposure
from qf_lib.common.enums.frequency import Frequency
from qf_lib.common.tickers.tickers import Ticker
from qf_lib.data_providers.data_provider import DataProvider
from config import PRICES_PATH

_EXPO_MAP = {1.0: Exposure.LONG, -1.0: Exposure.SHORT, 0.0: Exposure.OUT}


class TSMomentumAlphaModelCached(AlphaModel):
    def __init__(self, lookback_days, skip_days, threshold,
                 risk_estimation_factor, data_provider: DataProvider):
        super().__init__(risk_estimation_factor, data_provider)
        self.lookback_days = lookback_days
        self.skip_days = skip_days
        self.threshold = threshold
        self._expo = None  # date x ticker DataFrame of {-1,0,1}

    def _ensure_precomputed(self):
        if self._expo is not None:
            return
        df = pd.read_parquet(PRICES_PATH, columns=["date", "ticker", "Close"])
        df["date"] = pd.to_datetime(df["date"])
        close = df.pivot(index="date", columns="ticker", values="Close").sort_index()
        trail = close.shift(self.skip_days) / close.shift(self.lookback_days) - 1.0
        expo = np.sign(trail).where(trail.abs() >= self.threshold, 0.0)
        self._expo = expo
        self._idx = expo.index

    def calculate_exposure(self, ticker: Ticker, current_exposure: Exposure,
                           current_time: datetime, frequency: Frequency) -> Exposure:
        self._ensure_precomputed()
        t = ticker.as_string()
        if t not in self._expo.columns:
            return Exposure.OUT
        col = self._expo[t]
        # asof: latest exposure at or before current_time (PIT-safe by construction)
        pos = self._idx.searchsorted(pd.Timestamp(current_time), side="right") - 1
        if pos < 0:
            return Exposure.OUT
        v = col.iloc[pos]
        if pd.isna(v):
            return Exposure.OUT
        return _EXPO_MAP[float(v)]

    def __hash__(self):
        return hash((self.__class__.__name__, self.lookback_days,
                     self.skip_days, self.threshold, self.risk_estimation_factor))
