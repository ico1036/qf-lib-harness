"""TS-Momentum AlphaModel.

For each ticker independently, look at trailing return over (lookback - skip)
window and decide LONG / SHORT / OUT based on its sign and an optional threshold.
"""
from datetime import datetime

from qf_lib.backtesting.alpha_model.alpha_model import AlphaModel
from qf_lib.backtesting.alpha_model.exposure_enum import Exposure
from qf_lib.common.enums.frequency import Frequency
from qf_lib.common.enums.price_field import PriceField
from qf_lib.common.tickers.tickers import Ticker
from qf_lib.data_providers.data_provider import DataProvider


class TSMomentumAlphaModel(AlphaModel):
    """Time-series momentum model.

    Parameters
    ----------
    lookback_days : int
        Length of the formation window in trading days (~252 = 12 months).
    skip_days : int
        How many recent days to skip from the end of the window (~21 = 1 month;
        classic 12-1 momentum to avoid short-term reversal).
    threshold : float
        Absolute return threshold below which the model returns OUT
        (e.g., 0.02 means require |trailing return| > 2% to take a position).
    risk_estimation_factor : float
        Forwarded to base class for ATR-based stop-loss sizing.
    data_provider : DataProvider
        Data source; must expose historical_price().
    """

    def __init__(
        self,
        lookback_days: int,
        skip_days: int,
        threshold: float,
        risk_estimation_factor: float,
        data_provider: DataProvider,
    ):
        super().__init__(risk_estimation_factor, data_provider)
        if lookback_days <= skip_days + 5:
            raise ValueError("lookback_days must exceed skip_days by a margin")
        if threshold < 0:
            raise ValueError("threshold must be non-negative")
        self.lookback_days = lookback_days
        self.skip_days = skip_days
        self.threshold = threshold

    def calculate_exposure(
        self,
        ticker: Ticker,
        current_exposure: Exposure,
        current_time: datetime,
        frequency: Frequency,
    ) -> Exposure:
        bars_needed = self.lookback_days + 1
        close_tms = self.data_provider.historical_price(
            ticker, PriceField.Close, bars_needed, current_time, frequency
        )
        if close_tms is None or len(close_tms) < self.lookback_days:
            return Exposure.OUT

        end_price = close_tms.iloc[-(self.skip_days + 1)]
        start_price = close_tms.iloc[0]
        if start_price <= 0:
            return Exposure.OUT

        trailing_ret = end_price / start_price - 1.0
        if abs(trailing_ret) < self.threshold:
            return Exposure.OUT
        return Exposure.LONG if trailing_ret > 0 else Exposure.SHORT

    def __hash__(self):
        return hash(
            (
                self.__class__.__name__,
                self.lookback_days,
                self.skip_days,
                self.threshold,
                self.risk_estimation_factor,
            )
        )
