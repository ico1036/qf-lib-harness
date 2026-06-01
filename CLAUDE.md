# CLAUDE.md — qf-lib-harness

This repo is an autonomous price-only alpha-research harness. **qf-lib is a
pinned external dependency** (see `pyproject.toml` → `[tool.uv.sources]`), not
part of this tree — never look for `qf_lib/` source here.

## The one rule for the loop

The agent's job is to write `alpha_lab/experiments/exp_<name>/strategy.py` and
run it. **The harness core is FROZEN** — never edit `alpha_lab/core.py`,
`alpha_lab/pipeline.py`, `alpha_lab/__main__.py`, or `alpha_lab/trial_template.py`.

➡️ **Read `alpha_lab/CLAUDE.md` first** — it is the authoritative contract
(the `signal(ctx)` API, the no-look-ahead hard rules, the IS/OS gate).

## Run

```bash
uv run python -m alpha_lab run --strategy alpha_lab/experiments/<exp>/strategy.py
uv run python -m alpha_lab status
```

## Touching qf-lib (rare)

Real engine bugs / missing extension points only — most "I need to change
qf-lib" is actually subclassing `AlphaModel` / `DataProvider` in this repo.
If the engine genuinely must change: edit the fork, tag it, bump `rev` in
`pyproject.toml`, `uv lock`. Don't vendor qf-lib source into this repo.
