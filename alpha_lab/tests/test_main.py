"""Tests for alpha_lab.__main__ — CLI argparse + status command."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from alpha_lab import __main__ as main_mod
from alpha_lab import pipeline


_RESEARCH_ROOT = Path(__file__).resolve().parents[2]


class TestStatusCommand:
    def test_empty_ledger_prints_marker(self, tmp_path: Path, monkeypatch, capsys):
        ledger_path = tmp_path / "alpha_ledger.jsonl"
        monkeypatch.setattr(pipeline, "LEDGER_PATH", ledger_path)
        monkeypatch.setattr(main_mod, "LEDGER_PATH", ledger_path)
        monkeypatch.setattr(sys, "argv", ["alpha_lab", "status"])

        rc = main_mod.main()

        assert rc == 0
        out = capsys.readouterr().out
        assert "(empty ledger)" in out

    def test_lists_ledger_rows(self, tmp_path: Path, monkeypatch, capsys):
        ledger_path = tmp_path / "alpha_ledger.jsonl"
        monkeypatch.setattr(pipeline, "LEDGER_PATH", ledger_path)
        monkeypatch.setattr(main_mod, "LEDGER_PATH", ledger_path)

        rows = [
            {"ts": "2026-05-01T00:00:00Z", "exp_id": "alpha_a", "verdict": "pass",
             "metrics": {"sharpe_is": 0.81, "sharpe_os": 0.42}, "gate": {"reason": "pass"}},
            {"ts": "2026-05-02T00:00:00Z", "exp_id": "alpha_b", "verdict": "fail",
             "metrics": {"sharpe_is": 0.20, "sharpe_os": 0.10}, "gate": {"reason": "is_floor"}},
        ]
        ledger_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

        monkeypatch.setattr(sys, "argv", ["alpha_lab", "status", "--last", "5"])

        rc = main_mod.main()

        assert rc == 0
        out = capsys.readouterr().out
        assert "alpha_a" in out
        assert "alpha_b" in out
        assert "pass" in out
        assert "is_floor" in out

    def test_last_flag_truncates(self, tmp_path: Path, monkeypatch, capsys):
        ledger_path = tmp_path / "alpha_ledger.jsonl"
        monkeypatch.setattr(pipeline, "LEDGER_PATH", ledger_path)
        monkeypatch.setattr(main_mod, "LEDGER_PATH", ledger_path)

        rows = [
            {"ts": f"2026-05-{i:02d}T00:00:00Z", "exp_id": f"alpha_{i}",
             "verdict": "pass", "metrics": {}, "gate": {}}
            for i in range(1, 11)
        ]
        ledger_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

        monkeypatch.setattr(sys, "argv", ["alpha_lab", "status", "--last", "3"])
        main_mod.main()

        out = capsys.readouterr().out
        # Should only show the last 3 rows. Use space-bounded matching so
        # "alpha_1 " (ledger column-padded) doesn't false-match "alpha_10".
        lines = [l for l in out.splitlines() if "alpha_" in l]
        assert len(lines) == 3
        assert any("alpha_8" in l for l in lines)
        assert any("alpha_9" in l for l in lines)
        assert any("alpha_10" in l for l in lines)
        # Verify earlier rows are NOT shown
        assert not any("alpha_1 " in l for l in lines)
        assert not any("alpha_2 " in l for l in lines)
        assert not any("alpha_7 " in l for l in lines)


class TestArgparseRequiresSubcommand:
    def test_no_subcommand_exits(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["alpha_lab"])
        with pytest.raises(SystemExit):
            main_mod.main()


class TestRunCommandRejectsBadStrategy:
    """Smoke test that `run` end-to-end CLI path catches missing strategy file
    without needing data or qf-lib."""

    def test_missing_file_returns_nonzero(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["alpha_lab", "run", "--strategy", str(tmp_path / "nope.py")])
        rc = main_mod.main()
        assert rc != 0

    def test_run_via_subprocess_status_command(self):
        """Sanity-run `python -m alpha_lab status` as a separate process."""
        result = subprocess.run(
            [sys.executable, "-m", "alpha_lab", "status"],
            cwd=str(_RESEARCH_ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
