"""Application-scale workload generation, stage totals and promotion policy."""

import json
from pathlib import Path

import pytest

from tools.bench.app_scale import AppScaleFixture
from tools.bench.baseline import Baseline
from tools.bench.suite import IncrementalBuild, Program, Suite, Timing
from tools.host_c_compiler import HostCCompiler


def test_generated_application_workload_is_current() -> None:
    assert AppScaleFixture.path().read_text() == AppScaleFixture.render()
    program = Program.discover([AppScaleFixture.NAME])[0]
    assert program.phases and program.native
    assert len(AppScaleFixture.MODELS) == len(set(AppScaleFixture.MODELS)) == 64


@pytest.mark.parametrize("qualified_ms", [1.0, 10_000.0])
def test_app_stages_gate_after_a_qualifying_baseline(qualified_ms: float) -> None:
    baseline = {"btrcc.compile.CompileAppScale_ms": qualified_ms}
    baseline.update(
        {f"btrcc.phase.CompileAppScale.{phase}_ms": 100 for phase in ("analyze", "lower", "optimize", "emit")}
    )
    current = {name: value * 1.36 for name, value in baseline.items()}
    findings = Baseline.compare(current, baseline)
    assert all(finding.status == "regression" for finding in findings)
    # A candidate exceeding ten seconds must not turn its established gate off.
    reported = Baseline.compare(current, baseline, gate_timings=False)
    assert all(finding.status == "slower" for finding in reported)
    boundary = {name: value * 1.35 for name, value in baseline.items()}
    assert all(finding.status == "ok" for finding in Baseline.compare(boundary, baseline))


@pytest.mark.parametrize("baseline_ms", [0.0, 10_000.01, 20_000.0])
def test_app_timings_stay_informational_before_qualification(baseline_ms: float) -> None:
    baseline = {
        "btrcc.compile.CompileAppScale_ms": baseline_ms,
        "btrcc.compile.CompileAppScale_cpu_ms": 100,
        "btrcc.phase.CompileAppScale.analyze_ms": 100,
        "cc.CompileAppScale.O2_ms": 100,
        "reference.compile.CompileAppScale_ms": 100,
        "c.CompileAppScale.bytes": 100,
        "c.CompileAppScale.parity": 1,
    }
    current = {name: value * 2 for name, value in baseline.items()}
    findings = {finding.name: finding.status for finding in Baseline.compare(current, baseline)}
    assert {status for name, status in findings.items() if name.endswith("_ms")} == {"ok"}
    assert findings["c.CompileAppScale.bytes"] == "regression"
    assert findings["c.CompileAppScale.parity"] == "regression"


def test_reference_and_individual_marks_do_not_gate_after_promotion() -> None:
    baseline = {
        "btrcc.compile.CompileAppScale_ms": 9_000,
        "reference.compile.CompileAppScale_ms": 100,
        "btrcc.phase.CompileAppScale.a-bodies_ms": 100,
    }
    current = {**baseline, "reference.compile.CompileAppScale_ms": 900, "btrcc.phase.CompileAppScale.a-bodies_ms": 900}
    assert all(finding.status == "ok" for finding in Baseline.compare(current, baseline))


def test_app_measurement_uses_native_plan_and_complete_stage_totals(tmp_path: Path, monkeypatch) -> None:
    program = Program(AppScaleFixture.NAME, AppScaleFixture.path())
    commands = []
    builds = []

    def run(command, env, cwd, repeat):
        commands.append(command)
        if len(commands) == 1:
            return Timing(
                50,
                45,
                "int main(void) { return 0; }\n",
                (
                    "btrcc timing: a-decls=1000us a-bodies=2000us analyze=3000us "
                    "l-functions=4000us lower=3000us o-reachability=6000us optimize=5000us "
                    "setjmp-analysis=7000us emit=8000us\n"
                ),
            ), []
        return Timing(1, 1, AppScaleFixture.expected_stdout()), []

    def build(self, selected, source, plan, binary, level, env, repeat):
        builds.append((selected, plan, level))
        binary.write_bytes(b"fixture")
        return Timing(1, 1)

    monkeypatch.setattr(Timing, "best", run)
    monkeypatch.setattr(Suite, "_build", build)
    suite = Suite(Path("btrcc"), ["cc"], 1, tmp_path, reference=False, peaks=False)
    suite._program(program, {})
    assert commands[0][1:4] == ["--no-cache", "--emit-link-plan", str(tmp_path / "CompileAppScale.link.json")]
    assert builds == [
        (program, tmp_path / "CompileAppScale.link.json", 0),
        (program, tmp_path / "CompileAppScale.link.json", 2),
    ]
    assert {key: value for key, value in suite.metrics.items() if key.startswith("btrcc.phase.")} == {
        "btrcc.phase.CompileAppScale.analyze_ms": 6,
        "btrcc.phase.CompileAppScale.lower_ms": 7,
        "btrcc.phase.CompileAppScale.optimize_ms": 18,
        "btrcc.phase.CompileAppScale.emit_ms": 8,
    }


@pytest.mark.parametrize("stdout", ["", "PASS: app-scale models=64 checksum=0\n"])
def test_app_output_is_checked_without_a_baseline_or_reference(stdout: str) -> None:
    program = Program(AppScaleFixture.NAME, AppScaleFixture.path())
    with pytest.raises(RuntimeError, match="workload contract"):
        program.check_output(stdout, "self-host")


def test_app_measurement_refuses_a_missing_stage_report(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Timing, "best", lambda *args: (Timing(1, 1, "", "btrcc timing: analyze=100us\n"), []))
    suite = Suite(Path("btrcc"), ["cc"], 1, tmp_path, reference=False, peaks=False)
    with pytest.raises(RuntimeError, match="missing stage marks"):
        suite._program(Program(AppScaleFixture.NAME, AppScaleFixture.path()), {})


def test_incremental_edits_change_only_main_and_its_checked_result() -> None:
    source = AppScaleFixture.path().read_text()
    assert AppScaleFixture.edited_source(source, 0) == source
    prefix = source.split("int main() {", 1)[0]
    for revision in (1, 2, 101):
        edited = AppScaleFixture.edited_source(source, revision)
        assert edited.startswith(prefix)
        assert f"int checksum = {revision};" in edited[len(prefix) :]
        assert f"assert(checksum == {AppScaleFixture.checksum() + revision});" in edited
        assert AppScaleFixture.expected_stdout(revision) != AppScaleFixture.expected_stdout()
    with pytest.raises(ValueError, match="anchors"):
        AppScaleFixture.edited_source("int main() {}", 1)


def test_incremental_gate_does_not_wait_for_cold_compile_qualification() -> None:
    baseline = {"incremental.edit_ms": 4_000.0, "btrcc.compile.CompileAppScale_ms": 30_000.0}
    candidate = {**baseline, "incremental.edit_ms": 5_401.0}
    findings = {finding.name: finding.status for finding in Baseline.compare(candidate, baseline)}
    assert findings["incremental.edit_ms"] == "regression"
    reported = {finding.name: finding.status for finding in Baseline.compare(candidate, baseline, gate_timings=False)}
    assert reported["incremental.edit_ms"] == "slower"


def test_incremental_timer_excludes_priming_and_writes(tmp_path: Path, monkeypatch) -> None:
    events = []
    times = iter((1.0, 1.3, 2.0, 2.2))
    monkeypatch.setattr(IncrementalBuild, "prepare", lambda self, revision: events.append(("edit", revision)))
    monkeypatch.setattr(IncrementalBuild, "run", lambda self, revision: events.append(("run", revision)))

    def clock():
        events.append(("clock", None))
        return next(times)

    monkeypatch.setattr("tools.bench.suite.time.perf_counter", clock)
    suite = Suite(Path("btrcc"), ["cc"], 2, tmp_path)
    suite._incremental(Program(AppScaleFixture.NAME, AppScaleFixture.path()))
    assert suite.metrics == {"incremental.edit_ms": 200.0}
    assert events == [
        ("edit", 0),
        ("run", 0),
        ("run", 0),
        ("edit", 1),
        ("clock", None),
        ("run", 1),
        ("clock", None),
        ("edit", 2),
        ("clock", None),
        ("run", 2),
        ("clock", None),
    ]


def test_incremental_build_reuses_real_objects_and_rejects_stale_output(tmp_path: Path, immutable_btrcc: Path) -> None:
    """Exercise the real compiler, object cache, linker and executable without timing them."""

    source = f"""#include <assert.h>
int main() {{
\tint checksum = 0;
\tchecksum += {AppScaleFixture.checksum()};
\tassert(checksum == {AppScaleFixture.checksum()});
\tprint(f"PASS: app-scale models={len(AppScaleFixture.MODELS)} checksum={{checksum}}");
\treturn 0;
}}
"""
    suite = Suite(immutable_btrcc, HostCCompiler.configured(), 1, tmp_path)
    build = IncrementalBuild(immutable_btrcc, suite.cc, tmp_path, suite.peak_environment(), source)
    build.prepare(0)
    build.run(0)
    build.run(0)
    report = json.loads((tmp_path / "native-0.json").read_text())
    assert report["reused_units"] > 0
    with pytest.raises(RuntimeError, match="output failed the workload contract"):
        build.run(1)
    for revision in (1, 2):
        build.prepare(revision)
        build.run(revision)
