"""CLI: `python -m alpha_lab run --strategy <path>`."""
from __future__ import annotations

import argparse
import sys

from alpha_lab.pipeline import run, LEDGER_PATH


def main() -> int:
    p = argparse.ArgumentParser(prog="alpha_lab")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="run one strategy.py")
    p_run.add_argument("--strategy", required=True, help="path to experiments/<exp>/strategy.py")

    p_status = sub.add_parser("status", help="show recent ledger rows")
    p_status.add_argument("--last", type=int, default=10)

    args = p.parse_args()

    if args.cmd == "run":
        return run(args.strategy)

    if args.cmd == "status":
        if not LEDGER_PATH.exists():
            print("(empty ledger)")
            return 0
        import json
        rows = [json.loads(line) for line in LEDGER_PATH.read_text().splitlines() if line.strip()]
        rows = rows[-args.last:]
        for r in rows:
            m = r.get("metrics", {})
            print(f"{r.get('ts','?')} | {r.get('exp_id','?'):24s} | "
                  f"verdict={r.get('verdict','?'):5s} | "
                  f"S_IS={m.get('sharpe_is', float('nan')):+.2f} "
                  f"S_OS={m.get('sharpe_os', float('nan')):+.2f} | "
                  f"{r.get('gate', {}).get('reason','-')}")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
