"""The benchmark suite runs end to end on the shared self-host compiler."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tools.bench.main import main
from tools.bench.suite import REPO


def test_suite_measures_hello_and_checks_against_a_fresh_baseline(immutable_btrcc: Path, tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    recorded = tmp_path / "baseline.json"
    common = [
        "--btrcc",
        str(immutable_btrcc),
        "--repeat",
        "1",
        "--programs",
        "BenchHello",
        "--out-dir",
        str(tmp_path / "out"),
    ]
    assert main(["baseline", *common, "--json", str(results), "--baseline", str(recorded)]) == 0
    metrics = json.loads(results.read_text())["metrics"]
    assert metrics["c.BenchHello.parity"] == 1
    assert metrics["btrcc.startup_ms"] > 0 and metrics["btrcc.compile.BenchHello_ms"] > 0
    assert metrics["c.BenchHello.bytes"] > 0 and metrics["binary.BenchHello.bytes"] > 0
    assert "btrcc.phase.BenchHello.lower_ms" in metrics and "run.BenchHello_ms" in metrics
    assert main(["check", "--results", str(results), "--baseline", str(recorded)]) == 0
    # A metric that leaves its slack is a failure; a missing platform is only one under --strict.
    metrics["c.BenchHello.bytes"] = metrics["c.BenchHello.bytes"] * 2
    worse = tmp_path / "worse.json"
    worse.write_text(json.dumps({"meta": json.loads(results.read_text())["meta"], "metrics": metrics}))
    assert main(["check", "--results", str(worse), "--baseline", str(recorded)]) == 1
    assert main(["check", "--results", str(results), "--baseline", str(tmp_path / "none.json")]) == 0
    assert main(["check", "--results", str(results), "--baseline", str(tmp_path / "none.json"), "--strict"]) == 1


def test_module_entry_point_prints_help() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "tools.bench", "--help"], cwd=REPO, capture_output=True, text=True
    )
    assert completed.returncode == 0 and "bench-baseline" not in completed.stderr
