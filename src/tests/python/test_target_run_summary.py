"""The step-summary Markdown the target-corpus CI jobs publish (tools/target_hosts/summary.py)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.tests.process_limits import TOOL_TIMEOUT
from tools.target_hosts.summary import TargetRunSummary

REPO = Path(__file__).resolve().parents[3]


def report(mode: str = "execute") -> dict:
    return {
        "target": {"label": "android-x86_64"},
        "mode": mode,
        "executor": "android-emulator" if mode == "execute" else None,
        "executor_provenance": {"device": "sdk_gphone_x86_64 (emulator-5554)"} if mode == "execute" else None,
        "counts": {
            "reference": {"passed": 2, "failed": 1, "restricted": 1, "missing": 2},
            "selfhost": {"passed": 3, "failed": 0, "restricted": 1, "missing": 2},
        },
        "results": [
            {"frontend": "reference", "program": "a/A.btrc", "status": "passed"},
            {
                "frontend": "reference",
                "program": "b/B.btrc",
                "status": "failed",
                "phase": "compare",
                "reason": "stdout differs | at line 2\nsecond line",
            },
            *(
                {
                    "frontend": frontend,
                    "program": "gpu/G.btrc",
                    "status": "missing",
                    "reason": "no compute runtime",
                    "cites": "corpus.gpu@android-x86_64",
                }
                for frontend in ("reference", "selfhost")
            ),
            {
                "frontend": "selfhost",
                "program": "s/S.btrc",
                "status": "restricted",
                "reason": "by design",
                "cites": "x#y",
            },
        ],
    }


def test_an_executed_run_lists_counts_failures_and_grouped_exclusions():
    lines = TargetRunSummary(report()).lines()
    assert lines[0] == "### android-x86_64: the corpus on sdk_gphone_x86_64 (emulator-5554) (android-emulator)"
    assert "| reference | 2 | 1 | 1 | 2 |" in lines and "| selfhost | 3 | 0 | 1 | 2 |" in lines
    assert "| reference | b/B.btrc | compare | stdout differs \\| at line 2 |" in lines
    assert "| missing | 2 | no compute runtime | corpus.gpu@android-x86_64 |" in lines
    assert "| restricted | 1 | by design | x#y |" in lines


def test_a_compile_only_run_says_passed_means_built():
    assert "compile-only: passed means built" in TargetRunSummary(report("compile-only")).lines()[0]


def test_the_command_prints_one_section_per_report(tmp_path):
    path = tmp_path / "target-run.json"
    path.write_text(json.dumps(report()))
    completed = subprocess.run(
        [sys.executable, "-m", "tools.target_hosts.summary", str(path), str(path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
        check=True,
    )
    assert completed.stdout.count("### android-x86_64") == 2
