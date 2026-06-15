"""CLI for inspecting backtest runs — same numbers as the dashboard, no browser.

Reads the qf-lib backtest artifacts under `output/backtesting/` and exposes the
statistics table and equity/return time series on the command line. Statistics
come from the exact same functions the dashboard renders (dashboard.stats_rows /
load_strategy_series), so the CLI and the web view never disagree.

Run:
    uv run python research/cli.py list
    uv run python research/cli.py stats <run>
    uv run python research/cli.py timeseries <run> [--freq D|W|M] [--returns] [--out FILE]

`<run>` may be a full run id ("2026_06_03-1432 strategy"), any unique substring
("ls_mom", "1432"), or the 1-based index shown by `list`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# dashboard.py guards ui.run() behind __main__, so importing it is side-effect
# free except for registering the qf-lib plot style — we reuse its loaders and
# the stats table so this CLI reports byte-identical numbers to the web view.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dashboard as dash  # noqa: E402


def _output_dir() -> Path:
    """Resolve the backtesting output dir, tolerant of the research/output
    symlink being absent. Repo-root output/ is where the pipeline writes."""
    root = Path(__file__).resolve().parent.parent
    for cand in (root / "output" / "backtesting", dash.OUTPUT_DIR):
        if cand.exists() and any(cand.iterdir()):
            return cand
    return root / "output" / "backtesting"


def _scan() -> list[dict]:
    out_dir = _output_dir()
    if not out_dir.exists():
        return []
    runs = []
    for d in sorted(out_dir.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        ts_xlsx = next(d.glob("*Timeseries.xlsx"), None)
        if not ts_xlsx:
            continue
        ts_str, _, name = d.name.partition(" ")
        runs.append(dict(id=d.name, name=name or d.name, ts_str=ts_str,
                         path=d, ts_xlsx=ts_xlsx))
    return runs


def _resolve(runs: list[dict], token: str) -> dict:
    """Match a run by exact id, 1-based list index, then unique substring."""
    for r in runs:
        if r["id"] == token:
            return r
    if token.isdigit():
        i = int(token) - 1
        if 0 <= i < len(runs):
            return runs[i]
    hits = [r for r in runs if token.lower() in r["id"].lower()]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        sys.exit(f"no run matches {token!r}. Try `cli.py list`.")
    ids = "\n  ".join(r["id"] for r in hits)
    sys.exit(f"{token!r} is ambiguous, matches:\n  {ids}")


def _series(run: dict):
    return dash.load_strategy_series(str(run["ts_xlsx"]), run["name"])


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_list(args: argparse.Namespace) -> int:
    runs = _scan()
    if not runs:
        print(f"(no backtest runs under {_output_dir()})")
        return 0

    records = []
    for i, r in enumerate(runs, 1):
        rec = dict(idx=i, id=r["id"], name=r["name"], run=r["ts_str"])
        try:
            m = {label: f"{v}{(' ' + u) if u else ''}"
                 for label, v, u in dash.stats_rows(_series(r))}
            rec.update(start=m["Start Date"], end=m["End Date"],
                       total=m["Total Return"], ann=m["Annualised Return"],
                       sharpe=m["Sharpe Ratio"], max_dd=m["Max Drawdown"])
        except Exception as e:  # corrupt/partial run — list it, flag the error
            rec.update(error=str(e))
        records.append(rec)

    if args.json:
        print(json.dumps(records, indent=2))
        return 0

    hdr = f"{'#':>2}  {'name':<22} {'run':<14} {'Sharpe':>7} {'Total':>9} {'Ann':>8} {'MaxDD':>9}  range"
    print(hdr)
    print("-" * len(hdr))
    for rec in records:
        if "error" in rec:
            print(f"{rec['idx']:>2}  {rec['name']:<22} {rec['run']:<14}  !! {rec['error']}")
            continue
        print(f"{rec['idx']:>2}  {rec['name']:<22} {rec['run']:<14} "
              f"{rec['sharpe']:>7} {rec['total']:>9} {rec['ann']:>8} {rec['max_dd']:>9}  "
              f"{rec['start']} → {rec['end']}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    run = _resolve(_scan(), args.run)
    rows = dash.stats_rows(_series(run))

    if args.json:
        out = {label: (f"{value} {unit}".strip() if unit else value)
               for label, value, unit in rows}
        print(json.dumps({"id": run["id"], "name": run["name"], "stats": out}, indent=2))
        return 0

    print(f"{run['name']}  ·  run {run['ts_str']}  ({run['id']})")
    print("-" * 48)
    for label, value, unit in rows:
        full = f"{label} [{unit}]" if unit else label
        print(f"{full:<34} {value:>12}")
    return 0


_FREQ = {"D": None, "W": "W", "M": "ME"}


def cmd_timeseries(args: argparse.Namespace) -> int:
    run = _resolve(_scan(), args.run)
    series = _series(run)  # daily EOD equity (PricesSeries)

    rule = _FREQ[args.freq]
    s = series.resample(rule).last() if rule else series
    s = pd.Series(s.values, index=pd.DatetimeIndex(s.index))

    if args.returns:
        s = s.pct_change().dropna()
        value_col = "return"
    else:
        value_col = "equity"

    df = pd.DataFrame({"date": s.index.strftime("%Y-%m-%d"), value_col: s.values})

    if args.format == "json":
        text = df.to_json(orient="records", indent=2)
    else:
        text = df.to_csv(index=False)

    if args.out:
        Path(args.out).write_text(text)
        print(f"wrote {len(df)} rows ({args.freq} {value_col}) → {args.out}")
    else:
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="cli", description="Inspect backtest runs (stats + time series).")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list all runs with headline stats")
    p_list.add_argument("--json", action="store_true", help="emit JSON")
    p_list.set_defaults(func=cmd_list)

    p_stats = sub.add_parser("stats", help="full statistics table for one run")
    p_stats.add_argument("run", help="run id, list index, or unique substring")
    p_stats.add_argument("--json", action="store_true", help="emit JSON")
    p_stats.set_defaults(func=cmd_stats)

    p_ts = sub.add_parser("timeseries", aliases=["ts"], help="dump equity / return series")
    p_ts.add_argument("run", help="run id, list index, or unique substring")
    p_ts.add_argument("--freq", choices=list(_FREQ), default="D",
                      help="resample frequency: D(aily, default) / W(eekly) / M(onthly)")
    p_ts.add_argument("--returns", action="store_true",
                      help="emit simple returns instead of equity level")
    p_ts.add_argument("--format", choices=["csv", "json"], default="csv")
    p_ts.add_argument("--out", help="write to file instead of stdout")
    p_ts.set_defaults(func=cmd_timeseries)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
