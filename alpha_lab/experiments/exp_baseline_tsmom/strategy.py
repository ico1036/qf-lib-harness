"""12-1 time-series momentum baseline (mirrors tsmom_alpha_model.py).

# alpha-meta
# lever:        12-1 momentum (252d lookback, 21d skip)
# base:         template
# hypothesis:   trailing 12m return ex-most-recent month predicts next month
#               cross-section. Classic Jegadeesh-Titman 1993 + Asness skip.
"""
from __future__ import annotations

import pandas as pd

from alpha_lab.core import TrialContext


REBAL = "M"
TOP_N = 30
WEIGHT_SCHEME = "equal"
LOOKBACK_DAYS = 252


def signal(ctx: TrialContext) -> pd.DataFrame:
    px = ctx.adj_close
    # 12-1 momentum: return from t-252 to t-21, computed at t.
    # pct_change(252) at row t → (close_t / close_{t-252}) - 1.
    # Then .shift(21) so row t holds the value computed at t-21 → references
    # close_{t-21} / close_{t-273}, i.e. the 12-1 trailing return as of
    # 21 trading days ago. The pipeline reads the most recent row strictly
    # before the rebal date, so this is PIT-safe.
    return px.pct_change(LOOKBACK_DAYS).shift(21)
