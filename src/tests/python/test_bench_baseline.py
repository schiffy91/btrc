"""Contracts of the benchmark suite's baseline comparison."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from tools.bench import baseline
from tools.bench.main import main
from tools.bench.suite import PROGRAMS, Workload, discover, host_target, measure_peak, peak_counter, phase_times


def test_metric_kinds_are_declared_by_the_name() -> None:
    assert baseline.metric_kind("btrcc.compile.BenchHello_ms") == "ms"
    assert baseline.metric_kind("run.RunArc_cpu_ms") == "ms"
    assert baseline.metric_kind("c.BenchHello.bytes") == "bytes"
    assert baseline.metric_kind("c.BenchHello.lines") == "lines"
    assert baseline.metric_kind("c.BenchHello.parity") == "parity"
    assert baseline.metric_kind("btrcc.phase.BenchHello.lower_ms") == "info"
    assert baseline.metric_kind("btrcc.compile.BenchHello_peak") == "peak"
    assert baseline.metric_kind("btrcc.workload.BTRSmith_peak") == "peak"
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


def test_peaks_gate_at_two_percent_and_report_a_drop_so_the_baseline_is_retightened() -> None:
    gib = float(1 << 30)
    recorded = {"btrcc.workload.W_peak": 3 * gib, "btrcc.compile.A_peak": 3 * gib, "btrcc.compile.B_peak": 3 * gib}
    current = {
        "btrcc.workload.W_peak": 3.07 * gib,
        "btrcc.compile.A_peak": 3.05 * gib,
        "btrcc.compile.B_peak": 2.9 * gib,
    }
    findings = {finding.name: finding.status for finding in baseline.compare(current, recorded)}
    assert findings == {
        "btrcc.workload.W_peak": "regression",  # +2.3%
        "btrcc.compile.A_peak": "ok",  # +1.7%
        "btrcc.compile.B_peak": "improvement",  # -3.3%
    }
    loose = baseline.compare({"btrcc.workload.W_peak": 3.07 * gib}, recorded, tolerance_peak=0.05)
    assert loose[0].status == "ok"


def test_a_small_peak_gets_the_absolute_floor_of_slack() -> None:
    small = 4 << 20  # a 4 MiB compile: 2% is 84 KiB, below page and allocator noise
    floor = baseline.PEAK_FLOOR
    statuses = [
        baseline.compare({"btrcc.compile.H_peak": small + delta}, {"btrcc.compile.H_peak": small})[0].status
        for delta in (floor - 1, floor + 1, -(floor + 1))
    ]
    assert statuses == ["ok", "regression", "improvement"]


def test_a_workload_peak_over_its_absolute_budget_fails_whatever_its_baseline() -> None:
    current = {"btrcc.workload.W_peak": 3.01 * 2**30, "btrcc.workload.V_peak": 2.99 * 2**30}
    current["btrcc.compile.Huge_peak"] = 4.0 * 2**30  # a program compile is not the budgeted workload
    assert baseline.over_budget(current, 3.0) == ["btrcc.workload.W_peak"]
    assert baseline.over_budget(current, None) == []


def test_merge_keeps_the_platform_metrics_a_peak_only_run_did_not_measure(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    baseline.store(baseline.load(path), "darwin-arm64", {"a_ms": 1.0, "b.p_peak": 100}, {"revision": "abc"}, path)
    baseline.store(
        baseline.load(path), "darwin-arm64", {"b.p_peak": 90, "w_peak": 7}, {"revision": "def"}, path, merge=True
    )
    entry = baseline.load(path)["platforms"]["darwin-arm64"]
    assert entry["metrics"] == {"a_ms": 1.0, "b.p_peak": 90, "w_peak": 7}
    assert entry["recorded"] == {"revision": "abc"}
    assert entry["updates"] == [{"revision": "def", "metrics": ["b.p_peak", "w_peak"]}]
    baseline.store(baseline.load(path), "darwin-arm64", {"c_ms": 2.0}, {"revision": "ghi"}, path)
    assert baseline.load(path)["platforms"]["darwin-arm64"] == {
        "recorded": {"revision": "ghi"},
        "metrics": {"c_ms": 2.0},
    }


def _allocating(megabytes: int) -> list[str]:
    """A child that writes `megabytes` MiB and keeps it until it exits."""

    return [sys.executable, "-c", f"block = b'x' * ({megabytes} << 20)"]


def test_measure_peak_sees_an_allocation_and_rejects_a_failed_command(tmp_path: Path) -> None:
    small = measure_peak(_allocating(16), {}, tmp_path)
    large = measure_peak(_allocating(80), {}, tmp_path)
    assert small.source == large.source == peak_counter()
    assert large.bytes - small.bytes > 60 << 20
    with pytest.raises(RuntimeError, match="failed"):
        measure_peak([sys.executable, "-c", "raise SystemExit(3)"], {}, tmp_path)


def test_workload_command_is_the_cold_jobs_1_module_unit_compile(tmp_path: Path) -> None:
    workload = Workload(tmp_path, target="macos-arm64")
    assert workload.name == "BTRSmith" and workload.metric == "btrcc.workload.BTRSmith_peak"
    command = workload.command(Path("/b/btrcc"), tmp_path / "build")
    assert command[:6] == ["/b/btrcc", "--jobs", "1", "--strict-imports", "--target", "macos-arm64"]
    assert {"--debug", "--module-units", "--emit-units", "--emit-link-plan"} <= set(command)
    assert command[-3:] == ["src/BTRSmith.btrc", "-o", str(tmp_path / "build" / "p.c")]
    assert "--target" not in Workload(tmp_path, "src/App.btrc").command(Path("btrcc"), tmp_path)
    assert host_target() in {None, "macos-arm64", "macos-x64", "linux-arm64", "linux-x64"}


def _stand_in_compiler(directory: Path) -> Path:
    """A compiler with a fixed 48 MiB working set that logs how it was run.

    BENCH_INJECT_MIB adds an allocation on top, the way a regression would.
    """

    compiler = directory / "btrcc"
    compiler.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['BENCH_LOG'], 'a') as log:\n"
        "    run = {'argv': sys.argv[1:], 'cwd': os.getcwd(), 'cache': os.environ.get('BTRC_CACHE_DIR'),\n"
        "           'timing': 'BTRC_TIMING' in os.environ or 'BTRCC_TIMING' in os.environ}\n"
        "    log.write(json.dumps(run) + '\\n')\n"
        "block = b'x' * ((48 + int(os.environ.get('BENCH_INJECT_MIB', '0'))) << 20)\n"
    )
    compiler.chmod(0o755)
    return compiler


def test_peak_guard_trips_on_an_injected_allocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = tmp_path / "runs.jsonl"
    monkeypatch.setenv("BENCH_LOG", str(log))
    monkeypatch.setenv("BTRC_TIMING", "1")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    common = ["--btrcc", str(_stand_in_compiler(tmp_path)), "--peak-only", "--programs", "BenchHello"]
    common += ["--repeat", "1", "--peak-workload", str(workspace), "--out-dir", str(tmp_path / "out")]
    recorded = tmp_path / "baseline.json"
    results = tmp_path / "results.json"
    assert main(["baseline", *common, "--baseline", str(recorded), "--json", str(results)]) == 0
    assert set(json.loads(results.read_text())["metrics"]) == {
        "btrcc.compile.BenchHello_peak",
        "btrcc.workload.BTRSmith_peak",
    }
    runs = [json.loads(line) for line in log.read_text().splitlines()]
    workload = next(run for run in runs if "--module-units" in run["argv"])
    assert workload["cwd"] == str(workspace.resolve()) and workload["argv"][:2] == ["--jobs", "1"]
    assert Path(workload["cache"]).parent == tmp_path / "out" / "workloads" / "BTRSmith"
    assert not any(run["timing"] for run in runs)  # peaks are taken without the phase report
    assert main(["check", *common, "--baseline", str(recorded)]) == 0
    monkeypatch.setenv("BENCH_INJECT_MIB", "6")  # about 10% of a ~60 MiB peak
    injected = tmp_path / "injected.json"
    assert main(["check", *common, "--baseline", str(recorded), "--json", str(injected)]) == 1
    metrics = json.loads(injected.read_text())["metrics"]
    recorded_metrics = baseline.platform_metrics(baseline.load(recorded), baseline.platform_key())
    statuses = {finding.name: finding.status for finding in baseline.compare(metrics, recorded_metrics)}
    assert statuses == {"btrcc.compile.BenchHello_peak": "regression", "btrcc.workload.BTRSmith_peak": "regression"}
    assert main(["check", *common, "--baseline", str(recorded), "--peak-tolerance", "0.5"]) == 0
    # The M11 guard alone: the workload, no program compiles and no timings.
    alone = tmp_path / "alone.json"
    assert main(["check", *common, "--no-peaks", "--baseline", str(recorded), "--json", str(alone)]) == 1
    assert set(json.loads(alone.read_text())["metrics"]) == {"btrcc.workload.BTRSmith_peak"}
    # An absolute budget fails even with the baseline's slack to spare.
    monkeypatch.delenv("BENCH_INJECT_MIB")
    workload_only = [*common, "--no-peaks", "--baseline", str(recorded)]
    assert main(["check", *workload_only, "--peak-budget-gib", "1"]) == 0
    assert main(["check", *workload_only, "--peak-budget-gib", "0.01"]) == 1
    assert main(["check", *workload_only, "--peak-budget-gib", "0.01", "--baseline", str(tmp_path / "none.json")]) == 1
