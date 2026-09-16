"""Contracts of the benchmark suite's baseline comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.bench import baseline
from tools.bench.suite import PROGRAMS, discover, phase_times


def test_metric_kinds_are_declared_by_the_name() -> None:
    assert baseline.metric_kind("btrcc.compile.BenchHello_ms") == "ms"
    assert baseline.metric_kind("run.RunArc_cpu_ms") == "ms"
    assert baseline.metric_kind("c.BenchHello.bytes") == "bytes"
    assert baseline.metric_kind("c.BenchHello.lines") == "lines"
    assert baseline.metric_kind("c.BenchHello.parity") == "parity"
    assert baseline.metric_kind("btrcc.phase.BenchHello.lower_ms") == "info"
    with pytest.raises(ValueError):
        baseline.metric_kind("btrcc.compile.BenchHello")


def test_platform_key_names_operating_system_and_architecture_family() -> None:
    key = baseline.platform_key()
    system, _, machine = key.partition("-")
    assert system in {"darwin", "linux", "win32"}
    assert machine in {"arm64", "x86_64"} or machine


def test_compare_applies_kind_tolerances_and_flags_regressions() -> None:
    recorded = {"a.compile_ms": 100.0, "c.a.bytes": 1000, "c.a.parity": 1, "run.b_ms": 50.0, "btrcc.phase.a.x_ms": 1.0}
    current = {
        "a.compile_ms": 134.0,
        "c.a.bytes": 1040,
        "c.a.parity": 0,
        "run.b_ms": 30.0,
        "new.metric_ms": 1.0,
        "btrcc.phase.a.x_ms": 9.0,
    }
    findings = {finding.name: finding for finding in baseline.compare(current, recorded)}
    assert findings["a.compile_ms"].status == "ok"  # inside the 35 % timing slack
    assert findings["c.a.bytes"].status == "regression"  # sizes only get 3 %
    assert findings["c.a.parity"].status == "regression"  # booleans must match exactly
    assert findings["run.b_ms"].status == "improvement"
    assert findings["new.metric_ms"].status == "new"
    assert findings["btrcc.phase.a.x_ms"].status == "ok"  # attribution only, never gates
    tightened = {finding.name: finding for finding in baseline.compare(current, recorded, tolerance_ms=0.1)}
    assert tightened["a.compile_ms"].status == "regression"
    assert all(finding.status == "new" for finding in baseline.compare(current, None))


def test_store_and_load_round_trip_one_platform_without_touching_others(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    document = baseline.load(path)
    baseline.store(document, "linux-x86_64", {"z_ms": 2.0, "a_ms": 1.0}, {"revision": "abc"}, path)
    document = baseline.load(path)
    baseline.store(document, "darwin-arm64", {"a_ms": 3.0}, {"revision": "def"}, path)
    document = json.loads(path.read_text())
    assert list(document["platforms"]) == ["darwin-arm64", "linux-x86_64"]
    assert list(document["platforms"]["linux-x86_64"]["metrics"]) == ["a_ms", "z_ms"]
    assert baseline.platform_metrics(document, "darwin-arm64") == {"a_ms": 3.0}
    assert baseline.platform_metrics(document, "win32-x86_64") is None


def test_render_lists_regressions_first() -> None:
    findings = [
        baseline.Finding("ok_ms", 1.0, 1.0, "ok"),
        baseline.Finding("bad_ms", 1.0, 2.0, "regression"),
    ]
    rendered = baseline.render(findings).splitlines()
    assert rendered[1].startswith("bad_ms") and "2.00x" in rendered[1]


def test_phase_times_sum_repeated_marks() -> None:
    stderr = "btrcc timing: grammar=500us m-read=100us m-read=200us lower=1500us\nother line\n"
    assert phase_times(stderr) == pytest.approx({"grammar": 0.5, "m-read": 0.3, "lower": 1.5})


def test_workloads_are_discovered_and_run_kinds_are_named() -> None:
    programs = discover()
    names = {program.name for program in programs}
    assert {
        "BenchHello",
        "RunStrings",
        "RunCollections",
        "RunArc",
        "RunExceptions",
        "RunDispatch",
        "CompileStdlibHeavy",
    } <= names
    assert {program.name for program in programs if program.runs} >= {"BenchHello", "RunArc"}
    assert not next(program for program in programs if program.name == "CompileStdlibHeavy").runs
    assert all(program.path.parent == PROGRAMS for program in programs)
    with pytest.raises(ValueError):
        discover(["NoSuchProgram"])


def test_tracked_baseline_document_is_well_formed() -> None:
    document = baseline.load()
    for key, entry in document["platforms"].items():
        assert key == f"{key.split('-')[0]}-{key.split('-', 1)[1]}"
        assert {"recorded", "metrics"} <= set(entry)
        for name in entry["metrics"]:
            baseline.metric_kind(name)
