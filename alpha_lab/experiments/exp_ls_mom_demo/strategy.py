"""Dollar-neutral 12-1 momentum long/short — demo of WEIGHT_SCHEME="long_short".
# alpha-meta
# lever:        12-1 momentum, cross-sectional long/short
# base:         template (baseline 12-1 momentum, but long_short instead of equal)
# hypothesis:   momentum is a spread factor — going short the bottom-N losers as
#               well as long the top-N winners should harvest the full cross-
#               sectional spread and strip out broad market beta (dollar-neutral).
"""
from __future__ import annotations

import pandas as pd

from alpha_lab.core import TrialContext


REBAL = "M"                    # "M" | "W" | "Q"
TOP_N = 30                     # int in [5, 200] — 30 long + 30 short
WEIGHT_SCHEME = "long_short"   # top-N long + bottom-N short, each ±1/(2*TOP_N)
LOOKBACK_DAYS = 252            # informational


def signal(ctx: TrialContext) -> pd.DataFrame:
    """Return DataFrame[date × ticker] of scores. Higher = more bullish.

    Same 12-1 momentum score as the baseline; only WEIGHT_SCHEME differs.
    The pipeline longs the top-N scores and shorts the bottom-N.
    """
    px = ctx.adj_close                          # date × ticker
    return px.pct_change(LOOKBACK_DAYS).shift(21)  # 12-1 momentum
