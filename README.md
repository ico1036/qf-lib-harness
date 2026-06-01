<p align="right">
  <strong>English</strong> ·
  <a href="README_KO.md">한국어</a> ·
  <a href="README_ZH.md">中文</a> ·
  <a href="README_FR.md">Français</a>
</p>

<h1 align="center">qf-lib-harness</h1>

<p align="center">
  <em>Autonomous price-only alpha research on US equities.<br>
  Write a strategy — by hand or with an AI agent — gate it, read the verdict.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11-blue" alt="Python 3.11">
  <img src="https://img.shields.io/badge/engine-qf--lib%20(pinned)-orange" alt="qf-lib pinned">
  <img src="https://img.shields.io/badge/tests-82%20passing-brightgreen" alt="tests">
  <img src="https://img.shields.io/badge/built%20with-Claude%20Code-d97757" alt="Claude Code">
</p>

<p align="center">
  <a href="#1-get-the-data">Data</a> ·
  <a href="#2-write-a-strategy-by-hand">Hand strategy</a> ·
  <a href="#3-write-strategies-by-prompt-ai-agent">Agent strategy</a> ·
  <a href="#4-see-results--ledger--dashboard">Results</a> ·
  <a href="#5-the-agent-loop">Loop</a> ·
  <a href="#6-skills--issue--pr-automation">Skills</a>
</p>

---

## What you can do here

| # | Goal | Where | Command |
|---|---|---|---|
| 1 | **Get the data** | `research/` | `uv run python research/1_fetch_universe.py …` |
| 2 | **Write a strategy by hand** | `alpha_lab/experiments/exp_<id>/strategy.py` | `uv run python -m alpha_lab run …` |
| 3 | **Let an AI agent write strategies** | `alpha_lab/CLAUDE.md` (the contract) | point Claude Code at the repo |
| 4 | **See results** | ledger + dashboard | `uv run python -m alpha_lab status` · `uv run python research/dashboard.py` |
| 5 | **Understand the agent loop** | [§5](#5-the-agent-loop) | — |
| 6 | **Automate dev: issue → PR** | `.claude/skills/` | `/issue-author` · `/issue-to-pr` |

**First, once:** `uv sync` installs qf-lib (pinned) + deps. Then `touch .env`
(an empty file the local `uv` config expects). Python 3.11 is pinned.

### Layout

```
qf-lib-harness/
├── alpha_lab/      # the harness: AST gate, IS/OS backtest, ledger, experiments
├── research/       # data pipeline + manual backtests + dashboard
├── .claude/skills/ # issue-author + issue-to-pr dev-workflow skills
├── data/           # OHLCV parquet (gitignored, never leaves your machine)
└── pyproject.toml  # qf-lib pinned as an external dependency
```

---

## 1. Get the data

The data layer downloads US-equity OHLCV and builds a point-in-time universe.
Run the numbered scripts in order (from the repo root):

```bash
uv run python research/0_smoke_test.py       # ~5s   yfinance works?
uv run python research/1_fetch_universe.py   # ~5s   NASDAQ/NYSE/AMEX tickers (~7k)
uv run python research/2_download_prices.py  # 30m–2h daily OHLCV (resumable)
uv run python research/3_build_universe.py   # ~30s  PIT top-3000 by dollar volume
uv run python research/5_quality_check.py    # sanity / NaN / gaps
```

**Output:** `data/prices.parquet` and `data/universe_pit_top3000.parquet`.
Everything downstream reads these. (`data/` is gitignored.)

## 2. Write a strategy by hand

Copy the template, edit one function, run it:

```bash
mkdir -p alpha_lab/experiments/exp_myidea
cp alpha_lab/trial_template.py alpha_lab/experiments/exp_myidea/strategy.py
```

Edit `strategy.py` — you only touch the constants and `signal()`:

```python
REBAL = "M"              # rebalance: "M" | "W" | "Q"
TOP_N = 30               # names held each rebal (5–200), equal-weight
WEIGHT_SCHEME = "equal"  # only "equal" is wired
LOOKBACK_DAYS = 252      # informational

def signal(ctx) -> pd.DataFrame:
    # date × ticker scores. higher = more bullish. NaN = exclude.
    px = ctx.adj_close
    return px.pct_change(LOOKBACK_DAYS).shift(21)   # ← your idea here
```

`ctx` gives (all date × ticker): `adj_close`, `open/high/low`, `volume`,
`dollar_volume`, `universe`. **Two hard rules** (auto-rejected): no future bars
(`.shift(-N)` forbidden), no file reads (`pd.read_*`/`open()` forbidden — data
only via `ctx`).

Run it:

```bash
uv run python -m alpha_lab run --strategy alpha_lab/experiments/exp_myidea/strategy.py
```

## 3. Write strategies by prompt (AI agent)

You don't have to hand-write. **Point an AI coding agent (Claude Code) at this
repo and tell it to start the loop** — it invents strategies for you.

```bash
cd qf-lib-harness
claude            # then: "Start the alpha_lab loop."
```

`alpha_lab/CLAUDE.md` is the agent's **contract**: it may only create/edit
`alpha_lab/experiments/exp_<id>/strategy.py`. The core (`core.py`,
`pipeline.py`) is **frozen**, and an AST gate hard-rejects any look-ahead
before a strategy can run — so the agent cannot cheat or break the engine.

## 4. See results — ledger & dashboard

Two views, two sources:

```bash
# A) Loop results — every run appends a row to alpha_lab/alpha_ledger.jsonl
uv run python -m alpha_lab status --last 20
```

```
PASS = Sharpe_IS > 0.5  AND  Sharpe_OS > 0.5 × Sharpe_IS
```

```bash
# B) Visual dashboard — interactive Plotly tearsheets of full backtests
uv run python research/dashboard.py        # → http://localhost:8765
```

The dashboard renders detailed tearsheets from `research/output/backtesting/`
(produced by `research/run_tsmom_backtest.py`); the `status` CLI is the fast
text view of the agent loop's ledger.

## 5. The agent loop

The harness is built to run as a tight, never-stopping research loop:

```
LOOP FOREVER:
  1. Read the ledger        (status --last 20: what was tried, what passed)
  2. Pick a factor idea     (momentum, reversal, low-vol, liquidity, …)
  3. Choose a base          (best so far / a near-miss / template / scratch)
  4. Write strategy.py      (cp template → edit signal() + alpha-meta header)
  5. Run it                 (alpha_lab run … > run.log)
  6. Read the verdict       (pass / fail / crash → ledger row)
  7. Go back to 1
```

The **ledger is the memory** — the git diff (what changed) and the ledger row
(what it scored) are the lesson. Loop until a human interrupts or a strategy
clears `sharpe_is > 1.5`. Full contract: **`alpha_lab/CLAUDE.md`**.

## 6. Skills — issue → PR automation

Two **independent** Claude Code skills (in `.claude/skills/`) turn a goal into
GitHub issues, then issues into PRs — fully decoupled, talking only through
GitHub Issues. Invoke each separately in a Claude Code session:

```text
/issue-author    # goal/spec → epic → feature → task issues (with needs-human flags)
/issue-to-pr     # a ready task issue → branch → test → open PR (stops for human merge)
```

| Skill | Does | Stops at |
|---|---|---|
| **`issue-author`** | Decomposes a goal into an **epic → feature → task** tree, groups & links them (sub-issues), and flags which need human review (`needs-human`). **Shows the tree for your approval before creating anything.** | issues created on GitHub |
| **`issue-to-pr`** | Picks a **ready** task (skips `needs-human`, waits on `Depends on #N`), implements it on a branch, runs its tests, and opens a PR (`Closes #N`). | open PR — **a human merges** |

```
goal ─► /issue-author ─► GitHub Issues ─► /issue-to-pr ─► PR ─► (human merges)
                              ▲
                    you review / edit / set needs-human here
```

The shared contract (labels, sub-issue hierarchy, `Depends on #N`, `## Verify`,
needs-human criteria) lives in **`.claude/skills/CONVENTIONS.md`**. `issue-to-pr`
works on *any* conforming issue — including ones you wrote by hand.

---

## How it fits together

```
strategy (you or agent) ─► alpha_lab (AST gate ─► backtest ─► IS/OS slice ─► ledger)
                                            │
                                   data/prices.parquet ◄── research/ data pipeline (§1)
                                            │
                                         qf-lib ◄── the engine, pinned dependency
```

**qf-lib is not vendored here** — it is pinned as an external dependency in
`pyproject.toml` (`[tool.uv.sources]`, fork master `9ba5a0f`) and locked in
`uv.lock`. To upgrade the engine, bump the rev and `uv lock`. To edit it
locally, switch to the commented `editable` line. Every result is traceable to
*(qf-lib commit) × (data) × (experiment)*.
