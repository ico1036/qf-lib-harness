"""Alpha #101 from Kakushadze (2015), "101 Formulaic Alphas".

Source formula (Appendix A.1):
    ((close - open) / ((high - low) + .001))

Per the paper (p.4), Alpha #101 is the canonical *delay-1 momentum* example:
"if the stock runs up intraday (close > open and high > low), the next day
one takes a long position." The signal at time t is computed from t's own
OHLC and the position is taken at t+1 — handled by alpha_lab's pipeline,
which uses the most recent signal row strictly before the rebal timestamp.

Caveat — horizon mismatch
-------------------------
The paper's 101 alphas have an average holding period of 0.6-6.4 days
(daily-rebal regime). We're running a MONTHLY rebalance here so the score
at month-end is a single intraday measurement of one day. Cross-sectional
ranking still works in principle but most of the per-day signal washes out
across 21 trading days of holding. This trial is for *pipeline validation*
(end-to-end run + qf-lib timing), not Sharpe maximization.

Citation: Kakushadze, Z. "101 Formulaic Alphas." Wilmott Magazine, 2016.
arXiv:1601.00991. Formulae and code are property of WorldQuant LLC, used
here under the paper's express permission for replication and research.

# alpha-meta
# lever:        Alpha#101 — intraday close-vs-open over range
# base:         template
# hypothesis:   stocks that closed strong relative to their daily range
#               continue trending; cross-section selects the strongest
#               of those at month-end. Pipeline-validation trial.
"""
from __future__ import annotations

import pandas as pd

from alpha_lab.core import TrialContext


REBAL = "M"
TOP_N = 30
WEIGHT_SCHEME = "equal"
LOOKBACK_DAYS = 1   # Alpha#101 is purely intraday — no historical lookback


def signal(ctx: TrialContext) -> pd.DataFrame:
    """((close - open) / ((high - low) + .001))

    Higher score = closed near the intraday high relative to opening near
    the intraday low. Pipeline picks top-TOP_N by descending score at each
    monthly rebal anchor (last business day of each month).
    """
    numerator = ctx.adj_close - ctx.open
    denominator = (ctx.high - ctx.low) + 0.001
    return numerator / denominator
