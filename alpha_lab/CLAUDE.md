# CLAUDE.md — `alpha_lab/` package

Long-only price-only alpha generation harness over this repo's US equity
OHLCV (`data/prices.parquet`, built by the data pipeline). One iter you copy a
template, edit the body, run it, log the row. **NEVER STOP** until the human
halts or `sharpe_is > 1.5`.

## ⛔ HARD RULE — NO LOOK-AHEAD

The pipeline AST-checks every strategy.py before import. Violations are
hard-rejected (SystemExit) with the row written to the ledger as `crash`:

1. **No file IO.** `pd.read_parquet`, `pd.read_csv`, `open()`, etc. are
   rejected. All data flows through `ctx`.
2. **No negative shift.** `something.shift(-N)` (literal negative) is
   rejected — that's a future-bar reference.
3. **No leaderboard whitelists.** If you find yourself wanting to write
   `WHITELIST = ["AAPL", "MSFT", ...]` at module scope, stop — you're
   building in your knowledge of which tickers won. Read the ledger,
   pick a different lever.

These are the cheap mechanical defenses. Past those, look-ahead is on you:
no full-window statistics, no regime-aware constants computed from
hindsight, no "I noticed 2020 was bad so let me filter that range".

## The contract — one function

`experiments/exp_<name>/strategy.py` exposes:

```python
def signal(ctx: TrialContext) -> pd.DataFrame:
    """date × ticker scores. Higher = bullish. NaN = exclude."""
```

Plus four module constants the pipeline reads:

| Name | Allowed | Meaning |
|---|---|---|
| `REBAL` | `"M"` / `"W"` / `"Q"` | Rebalance frequency |
| `TOP_N` | int [5, 200] | Names held each rebal (equal-weight 1/TOP_N) |
| `WEIGHT_SCHEME` | `"equal"` | Only equal-weight long-only is wired |
| `LOOKBACK_DAYS` | int ≥ 1 | Informational; signal uses its own windows |

`ctx` (from `alpha_lab.core.TrialContext`):

| field | shape | content |
|---|---|---|
| `ctx.adj_close` | date × ticker | auto-adjusted close (use this for returns) |
| `ctx.open` / `high` / `low` | date × ticker | raw OHL |
| `ctx.volume` | date × ticker | share volume |
| `ctx.dollar_volume` | date × ticker | adj_close × volume |
| `ctx.universe` | tuple[str] | the fixed pool (top-300 by all-time ADV, history-filtered) |

The window `ctx.adj_close.index` is `2015-01-01 ~ OS_END`. IS/OS dates are
locked in `core.py` and not visible to the strategy — pipeline slices the
equity curve afterward.

## File constraints

EDITABLE (agent-controlled):
- `experiments/exp_<new_name>/strategy.py` (this iter's work)

FROZEN (human-controlled, do not edit):
- `alpha_lab/core.py` (TrialContext, dates, pool selection)
- `alpha_lab/pipeline.py` (AST gate, qf-lib bridge, IS/OS slice, ledger)
- `alpha_lab/__main__.py` (CLI)
- `alpha_lab/trial_template.py` (the template — copy from it, don't edit)
- `alpha_lab/CLAUDE.md` (this file — surface change requests to user)
- past `experiments/exp_<id>/` dirs (immutable record)

## IS/OS gate (lock — do not tune)

The pipeline runs ONE **vectorized** backtest from `IS_START` to `OS_END`
(`_run_vectorized_backtest`: prior-day top-N membership × daily returns, pure
matrix PnL — no broker/order/commission loop), then slices the daily simple
returns:

> **Backtest engine.** The loop uses the vectorized path by default (~1000×
> faster than the old event-driven `BacktestTradingSession`). It is look-ahead
> safe (positions use the prior day's membership) but **ignores transaction
> costs / slippage**, so reported Sharpe is slightly optimistic. The
> event-driven path is kept as `_run_qf_backtest` for cost-realistic
> validation of a shortlisted strategy. The strategy contract is unchanged —
> `signal(ctx)` still returns a `date × ticker` score matrix.

```
IS = [2016-01-04, 2023-01-03)
OS = [2023-01-03, 2026-04-01)

PASS = (Sharpe_IS > 0.5) AND (Sharpe_OS > 0.5 × Sharpe_IS)
```

- `0.5` IS floor ≈ statistical significance over a 7-yr window
- `0.5×` OS ratio ≈ "expect ≤ 50% degradation IS→OS" industry norm

The gate result is `pass` or `fail`. A `crash` is when the strategy raised
an exception or violated AST rules. All three append a ledger row so the
loop never blindly re-picks them.

## Single yardstick: Sharpe_IS

`sharpe_is` is the metric that ranks "better than current best". `sharpe_os`
is binary in the gate — it qualifies a trial but doesn't rank. Don't invent
a composite score. If `sharpe_is` did not move past prior best by ≥ 1e-3,
the iter didn't work; try a different lever.

## Output format

After `python -m alpha_lab run --strategy <path>` finishes, the run log
ends with a grep-friendly footer:

```
sharpe_is:  +0.834
sharpe_os:  +0.421
n_is:       1758
n_os:       567
gate:       pass
verdict:    pass
```

Extract:

```bash
grep "^sharpe_is:\|^verdict:" run.log
```

## Ledger schema

`alpha_lab/alpha_ledger.jsonl`, append-only, one JSON per line:

```json
{
  "exp_id": "alpha_v2_volsizing",
  "ts": "2026-05-08T01:23:45+00:00",
  "strategy": "alpha_lab/experiments/alpha_v2_volsizing/strategy.py",
  "content_hash": "2b1f36cc1234",
  "constants": {"REBAL": "M", "TOP_N": 30, "WEIGHT_SCHEME": "equal", "LOOKBACK_DAYS": 252},
  "metrics": {"sharpe_is": 0.834, "sharpe_os": 0.421, "n_is": 1758, "n_os": 567},
  "gate":    {"passed": true, "reason": "pass"},
  "verdict": "pass"
}
```

`alpha-meta` block in strategy.py docstring:

```python
"""<one-line description>.
# alpha-meta
# lever:        <free-form — momentum, low-vol, lottery, mean-rev, ...>
# base:         <parent exp_name, or 'template'>
# hypothesis:   <which axis, which direction, why>
"""
```

## The experiment loop

LOOP FOREVER:

1. Look at the ledger state — `python -m alpha_lab status --last 20` shows
   recent rows + their verdict + lever. Read 1-2 candidate
   `experiments/exp_<id>/strategy.py` bodies if you might base off them.
2. Decide what to try. The price-only factor families that fit here:
   momentum (12-1, 6-1), short-term reversal (1w, 1m), volatility
   (idiosyncratic / total / low-vol), liquidity (Amihud, turnover, ADV
   rank), lottery (MAX-K mean), beta, skewness/kurtosis, 52w-high distance,
   range (HL/C), volume shock, drawdown depth — and combinations of these.
3. Pick a base — current best, a near-miss, the template, or from-scratch.
   Default-to-best every iter is the lock-in pattern; spread the lever axis.
4. Edit `experiments/exp_<name>/strategy.py` directly — `mkdir`, `cp` from
   `alpha_lab/trial_template.py`, modify the body. Update the alpha-meta
   header so future you can grep the lever.
5. Run:
   ```
   uv run python -m alpha_lab run --strategy alpha_lab/experiments/exp_<name>/strategy.py > run.log 2>&1
   ```
   Redirect — do NOT tee or flood your context.
6. Read out: `grep "^sharpe_is:\|^verdict:" run.log`. If `verdict: crash`,
   tail run.log for the trace; small fix → retry, fundamentally broken →
   move on (the crash row is already in the ledger).
7. Loop back to step 1. **No lessons file.** The diff (git) and the metric
   (ledger) are the lesson. If you want to record reasoning, put it in the
   strategy.py alpha-meta `# hypothesis:` slot — that stays attached to
   the code it explains.

**NEVER STOP.** Once the loop has begun, do NOT pause to ask the human if
you should continue. If you run out of ideas: read the last 30 ledger rows
for unexplored lever axes, try combining previous near-misses, try **more
radical changes** — replace the score expression wholesale, swap the
selection rule, redefine the rebal cadence. The loop runs until the human
interrupts or `sharpe_is > 1.5`.

## Commands

```bash
# Run one strategy
uv run python -m alpha_lab run --strategy alpha_lab/experiments/exp_<name>/strategy.py

# Recent ledger rows
uv run python -m alpha_lab status --last 20
```

## Baseline (do not change)

Unmodified template (12-1 momentum, monthly rebal, top-30 equal-weight):
the floor any change should beat. Run it once at the start of a fresh
ledger to establish the baseline row.
