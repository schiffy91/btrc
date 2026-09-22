"""Measure both frontends through the strict production native-plan compile/link path."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import perf

ROOT = Path(__file__).resolve().parents[3]


def test_phase_times_reads_both_compilers_marks():
    stderr = "noise\nbtrcpy timing: lex=1500us parse=500us analyze=2000000us\nbtrcc timing: lex=1000us emit=250us\n"
    assert perf.phase_times(stderr) == {"lex": 0.0025, "parse": 0.0005, "analyze": 2.0, "emit": 0.00025}


@pytest.mark.parametrize("platform,raw", [("darwin", 32 * 1024 * 1024), ("linux", 32 * 1024)])
def test_measurement_normalizes_peak_rss(platform, raw):
    measured = perf.Measurement.from_usage({"wall_s": 1.0, "cpu_s": 0.8, "max_rss": raw, "returncode": 0}, platform)
    assert measured.max_rss_kb == 32 * 1024


def test_selfhost_sequential_marks_belong_to_their_stage():
    run = perf.CompilerRun(
        "btrcc",
        30.0,
        29.0,
        1024,
        {
            "lex": 1.0,
            "r-graph": 2.0,
            "a-register": 3.0,
            "analyze": 0.1,
            "l-setup": 4.0,
            "lower": 0.2,
            "setjmp-analysis": 0.3,
            "o-setjmp": 5.0,
            "optimize": 0.4,
            "emit": 6.0,
            "new-phase": 0.5,
        },
        "program.c",
        "program.link.json",
    )
    assert run.phase_totals() == pytest.approx(
        {
            "frontend": 3.0,
            "analyze": 3.1,
            "lower": 4.2,
            "optimize": 5.7,
            "emit": 6.0,
            "other": 0.5,
            "unattributed": 7.5,
        }
    )


def test_reference_phase_totals_do_not_invent_frontend_work():
    run = perf.CompilerRun("btrcpy", 10.0, 9.0, 1024, {"lex": 1.0, "analyze": 2.0, "lower": 3.0}, "p.c", "p.json")
    totals = run.phase_totals()
    assert totals["frontend"] == 1.0
    assert totals["unattributed"] == 4.0
    assert sum(totals.values()) == run.wall_s


def test_c_stats_counts_definitions(tmp_path):
    source = tmp_path / "unit.c"
    source.write_text(
        '#line 3 "x.btrc"\ntypedef struct btrc_Vector_int btrc_Vector_int;\nstruct A {\n};\nint f(void) {\n}\nstatic int g(int a) {\n}\n'
    )
    stats = perf.c_stats(source)
    assert (stats.lines, stats.functions, stats.structs, stats.vector_instances, stats.line_directives) == (
        8,
        2,
        1,
        1,
        1,
    )


@pytest.mark.skipif(shutil.which("cc") is None, reason="needs a C compiler")
def test_reference_compiler_measurement(tmp_path):
    report = tmp_path / "report.json"
    code = perf.main(
        [
            str(ROOT / "src/tests/basics/Hello.btrc")
            if (ROOT / "src/tests/basics/Hello.btrc").exists()
            else str(next((ROOT / "src/tests/basics").glob("*.btrc"))),
            "--frontends",
            "btrcpy",
            "--opt",
            "O0",
            "--cc",
            "cc",
            "--out",
            str(tmp_path / "work"),
            "--json",
            str(report),
        ]
    )
    assert code == 0
    data = json.loads(report.read_text())
    assert data["compilers"][0]["frontend"] == "btrcpy"
    assert data["compilers"][0]["phases_s"]["lower"] >= 0.0
    assert data["schema"] == 2
    target = perf.PackageTarget.parse(None)
    assert data["target"] == f"{target.operating_system}-{target.architecture}"
    assert data["provenance"]["input_stability"] == {"changed": [], "unchanged": True}
    cold, warm = data["native_builds"]
    assert cold["operations"]["optimization"] == 0
    assert cold["operations"]["executable_bytes"] > 0
    assert cold["operations"]["compiled_units"] >= 1
    assert warm["operations"]["compiled_units"] == 0
    assert warm["operations"]["reused_units"] == cold["operations"]["compiled_units"]
    assert warm["end_to_end_s"] is None
    assert data["provenance"]["compiler_sources"]["files"] > 0
    assert data["provenance"]["compiler_repository"]["revision"]
    assert data["provenance"]["rss_unit"] == "KiB"
    assert sys.executable


@pytest.mark.parametrize("frontend", ["btrcpy", "btrcc"])
def test_complete_build_measurement_includes_every_unit_and_mode(tmp_path, request, frontend, capsys):
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples/native-package", project, ignore=shutil.ignore_patterns("build", ".btrc-cache"))
    path = tmp_path / "report.json"
    options = [
        str(project / "src/Main.btrc"),
        "--frontends",
        frontend,
        "--unit-lines",
        "1",
        "--jobs",
        "2",
        "--out",
        str(tmp_path / "results"),
        "--json",
        str(path),
    ]
    if frontend == "btrcc":
        options.extend(["--btrcc", str(request.getfixturevalue("immutable_btrcc"))])
    assert perf.main(options) == 0
    rendered = capsys.readouterr().out
    report = json.loads(path.read_text())
    assert {run["mode"] for run in report["compilers"]} == {"dev", "release"}
    assert report["provenance"]["entry_package_sources"]["files"] >= 6
    assert len(report["native_builds"]) == 4
    native_count = 4 if report["target"].startswith("macos-") else 2
    for run in report["native_builds"]:
        operations = run["operations"]
        assert operations["emitted_units"] >= 2
        assert operations["native_units"] == native_count
        assert len(operations["units"]) == operations["emitted_units"] + native_count
        if operations["link_cache_status"] in {"hit", "stored"}:
            assert operations["links"] == (2 if run["scenario"] == "cold" else 0)
        else:
            assert operations["links"] == 1
        scenario = "cold build" if run["scenario"] == "cold" else "warm native only"
        prefix = f"| {run['frontend']} / {run['mode']} | {scenario} |"
        row = next(line for line in rendered.splitlines() if line.startswith(prefix))
        assert row.split("|")[-2].strip() == str(operations["links"])
        assert operations["debug_info"] == (run["mode"] == "dev")
        assert operations["optimization"] == (0 if run["mode"] == "dev" else 2)
        for unit in operations["units"]:
            assert "-Werror" in unit["command"] and "-w" not in unit["command"]
            assert unit["dependency_scan_s"] >= 0.0 and unit["cache_validation_s"] >= 0.0
        if run["scenario"] == "cold":
            assert operations["compiled_units"] == len(operations["units"])
            assert operations["cache_misses"] == {"missing-entry": len(operations["units"])}
            assert run["end_to_end_s"] >= run["measurement"]["wall_s"]
        else:
            assert operations["compiled_units"] == 0
            assert operations["reused_units"] == len(operations["units"])
        result = subprocess.run([run["executable"]], capture_output=True, text=True, check=True)
        assert result.stdout == "PASS: native package graph\n"


def test_failed_frontend_retains_measurement_and_logs(tmp_path):
    source = tmp_path / "Broken.btrc"
    source.write_text("int main( {\n")
    path = tmp_path / "report.json"
    assert (
        perf.main(
            [
                str(source),
                "--frontends",
                "btrcpy",
                "--modes",
                "dev",
                "--out",
                str(tmp_path / "runs"),
                "--json",
                str(path),
            ]
        )
        == 1
    )
    report = json.loads(path.read_text())
    assert report["failure"]
    assert report["compilers"][0]["returncode"] != 0
    assert report["native_builds"] == []
    directory = Path(report["provenance"]["work_directory"])
    assert (directory / "btrcpy-dev-1/frontend.stderr").stat().st_size > 0


@pytest.mark.parametrize(
    "option,value",
    [
        ("--frontends", "typo"),
        ("--frontends", ""),
        ("--modes", "dev,dev"),
        ("--modes", ""),
        ("--samples", "0"),
        ("--jobs", "0"),
        ("--opt", "O5"),
        ("--opt", ""),
        ("--target", "unknown-x64"),
    ],
)
def test_measurement_rejects_invalid_matrix_before_build(tmp_path, option, value):
    with pytest.raises(SystemExit) as error:
        perf.main([str(tmp_path / "Absent.btrc"), option, value])
    assert error.value.code == 2


def test_failed_link_retains_native_measurement_and_logs(tmp_path):
    source = tmp_path / "Unresolved.btrc"
    source.write_text("extern int missing_native_symbol();\nint main() { return missing_native_symbol(); }\n")
    path = tmp_path / "report.json"
    assert (
        perf.main(
            [
                str(source),
                "--frontends",
                "btrcpy",
                "--modes",
                "dev",
                "--out",
                str(tmp_path / "runs"),
                "--json",
                str(path),
            ]
        )
        == 1
    )
    report = json.loads(path.read_text())
    assert report["compilers"][0]["returncode"] == 0
    assert report["native_builds"][0]["measurement"]["returncode"] != 0
    assert report["native_builds"][0]["operations"] == {}
    directory = Path(report["provenance"]["work_directory"])
    assert "missing_native_symbol" in (directory / "btrcpy-dev-1/cold.stderr").read_text()


def test_measurement_rejects_inputs_changed_during_build(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples/native-package", project, ignore=shutil.ignore_patterns("build", ".btrc-cache"))
    original = perf.Perf.run_native

    def build_then_edit(self, run, directory, scenario, started):
        original(self, run, directory, scenario, started)
        with (project / "packages/leaf/src/Api.btrc").open("a") as stream:
            stream.write("\n// concurrent source edit\n")

    monkeypatch.setattr(perf.Perf, "run_native", build_then_edit)
    path = tmp_path / "report.json"
    assert (
        perf.main(
            [
                str(project / "src/Main.btrc"),
                "--frontends",
                "btrcpy",
                "--modes",
                "dev",
                "--warm-native-runs",
                "0",
                "--out",
                str(project / "results"),
                "--json",
                str(path),
            ]
        )
        == 1
    )
    report = json.loads(path.read_text())
    assert "inputs changed" in report["failure"]
    assert report["provenance"]["input_stability"] == {"changed": ["entry_package_sources"], "unchanged": False}
    assert report["native_builds"][0]["measurement"]["returncode"] == 0


@pytest.mark.parametrize("alias", [False, True])
def test_report_cannot_replace_program(tmp_path, alias):
    source = tmp_path / "Main.btrc"
    source.write_text("int main() { return 0; }\n")
    report = tmp_path / "report.json" if alias else source
    if alias:
        report.hardlink_to(source)
    with pytest.raises(SystemExit) as error:
        perf.main([str(source), "--json", str(report)])
    assert error.value.code == 2
    assert source.read_text() == "int main() { return 0; }\n"
