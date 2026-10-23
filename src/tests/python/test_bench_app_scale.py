"""Application-scale workload generation, stage totals and promotion policy."""

from pathlib import Path

import pytest

from tools.bench.app_scale import AppScaleFixture
from tools.bench.baseline import Baseline
from tools.bench.suite import Program, Suite, Timing


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
