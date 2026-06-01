# qf-lib-harness

Write a price-only US-equity strategy, run it through a look-ahead-proof IS/OS
gate, read the verdict. That's one iteration.

## 0. Setup (once)

```bash
uv sync                       # installs qf-lib (pinned) + deps
```

You need `data/prices.parquet`. Either point `data/` at an existing dataset, or
build it: `uv run python 1_fetch_universe.py && uv run python 2_download_prices.py && uv run python 3_build_universe.py`.

## 1. Start a new strategy

Copy the template into a new experiment folder:

```bash
mkdir -p alpha_lab/experiments/exp_myidea
cp alpha_lab/trial_template.py alpha_lab/experiments/exp_myidea/strategy.py
```

## 2. Write your signal

Edit `alpha_lab/experiments/exp_myidea/strategy.py`. You only touch two things:

```python
# 4 required constants
REBAL = "M"              # rebalance: "M" | "W" | "Q"
TOP_N = 30               # names held each rebal (5–200), equal-weight
WEIGHT_SCHEME = "equal"  # only "equal" is wired
LOOKBACK_DAYS = 252      # informational

def signal(ctx) -> pd.DataFrame:
    # return date × ticker scores. higher = more bullish. NaN = exclude.
    px = ctx.adj_close
    return px.pct_change(LOOKBACK_DAYS).shift(21)   # ← your idea here
```

`ctx` gives you (all date × ticker): `ctx.adj_close`, `ctx.open/high/low`,
`ctx.volume`, `ctx.dollar_volume`, and `ctx.universe`.

**Two hard rules** (rejected automatically before running):
- No future bars — `.shift(-N)` is forbidden.
- No file reads — `pd.read_*` / `open()` forbidden. Data comes only from `ctx`.

## 3. Run it

```bash
uv run python -m alpha_lab run --strategy alpha_lab/experiments/exp_myidea/strategy.py
```

## 4. Read the result

```bash
uv run python -m alpha_lab status
```

```
PASS = Sharpe_IS > 0.5  AND  Sharpe_OS > 0.5 × Sharpe_IS
```

Every run appends a row to `alpha_lab/alpha_ledger.jsonl`. Keep iterating: copy
a new `exp_<name>`, change the signal, run, compare.

---

Full contract (the `signal` API, ctx fields, IS/OS dates): `alpha_lab/CLAUDE.md`.
