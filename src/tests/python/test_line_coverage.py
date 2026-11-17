"""Line coverage: the corpus runner's recorder and the report `make coverage` writes.

The job itself needs gcc's gcov and most of an hour; these check its
arithmetic and its wiring with stand-ins: a gcov that prints a prepared
document, records written by hand, and the Makefile's dry run.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from src.tests import runner
from src.tests.line_coverage import LineCoverage
from src.tests.process_limits import TRANSPILE_TIMEOUT
from tools.line_coverage import CoverageReport, StdlibCensus

REPO = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the stand-in gcov is a shell script")


def _document(repo: Path, files: dict[str, list[tuple[int, int]]], cwd: Path | None = None) -> dict:
    return {
        "current_working_directory": str(cwd or repo),
        "files": [
            {"file": name, "lines": [{"line_number": number, "count": count} for number, count in lines]}
            for name, lines in files.items()
        ],
    }


def _tree(root: Path) -> Path:
    for relative in ("src/stdlib/Vector.btrc", "src/stdlib/USB/USBHID.btrc", "src/compiler/btrc/Lexer.btrc"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n")
    return root


def test_only_tracked_btrc_lines_count_and_a_shared_line_adds_up(tmp_path: Path) -> None:
    repo = _tree(tmp_path / "repo")
    coverage = LineCoverage(tmp_path / "records", repo=repo)
    document = _document(
        repo,
        {
            # A generic's instances list their shared line once each.
            str(repo / "src/stdlib/Vector.btrc"): [(10, 2), (10, 0), (11, 0)],
            "src/stdlib/USB/USBHID.btrc": [(5, 1)],
            "src/compiler/btrc/Lexer.btrc": [(7, 0)],
            # Not what the report covers: the program itself, generated C, a path outside the checkout.
            "src/tests/stdlib/Program.btrc": [(1, 1)],
            "/tmp/program.c": [(1, 1)],
            "../elsewhere/src/stdlib/Vector.btrc": [(1, 1)],
        },
    )

    assert coverage.lines_of(document) == {
        "src/stdlib/Vector.btrc": {10: 2, 11: 0},
        "src/stdlib/USB/USBHID.btrc": {5: 1},
        "src/compiler/btrc/Lexer.btrc": {7: 0},
    }


def test_a_program_is_recorded_once_and_its_data_is_removed(tmp_path: Path) -> None:
    repo = _tree(tmp_path / "repo")
    build = tmp_path / "build"
    native = tmp_path / "native" / "objects"
    for directory in (build, native):
        directory.mkdir(parents=True)
    documents = {
        "program-program.gcda": _document(repo, {"src/stdlib/Vector.btrc": [(10, 1), (11, 0)]}),
        "unit.gcda": _document(repo, {"src/stdlib/Vector.btrc": [(11, 3)]}),
    }
    for name, document in documents.items():
        directory = build if name.startswith("program") else native
        (directory / name).write_text("data")
        (directory / name).with_suffix(".gcno").write_text("notes")
        (directory / f"{name}.json").write_text(json.dumps(document))
    (build / "other-other.gcda").write_text("another program's")
    gcov = tmp_path / "gcov"
    # gcov is asked for JSON on stdout, by the data file's name, in its directory.
    gcov.write_text('#!/bin/sh\n[ "$1" = --json-format ] && [ "$2" = --stdout ] && cat "$3.json"\n')
    gcov.chmod(0o755)
    coverage = LineCoverage(tmp_path / "records", repo=repo, gcov=str(gcov))

    assert coverage.record(build / "program", native.parent) is True

    assert LineCoverage.total(tmp_path / "records") == {"src/stdlib/Vector.btrc": {10: 1, 11: 3}}
    # The data and its notes are spent; another program's are not touched.
    for spent in (
        build / "program-program.gcda",
        build / "program-program.gcno",
        native / "unit.gcda",
        native / "unit.gcno",
    ):
        assert not spent.exists(), spent
    assert (build / "other-other.gcda").is_file()
    # A second program's record is added to the first's, also from another worker's file.
    (build / "program-program.gcda").write_text("data")
    coverage.record(build / "program")
    (tmp_path / "records" / "other-worker.jsonl").write_text(json.dumps({"src/stdlib/Vector.btrc": {"12": 0}}) + "\n")
    assert LineCoverage.total(tmp_path / "records") == {"src/stdlib/Vector.btrc": {10: 2, 11: 3, 12: 0}}
    # A program that left no data (its objects' directory is gone, or it was killed) records nothing,
    # and is named so the report can say what it does not count.
    assert coverage.record(build / "absent") is False
    coverage.unrecorded("stdlib/Daemon.btrc")
    coverage.unrecorded("stdlib/Daemon.btrc")
    assert LineCoverage.unrecorded_programs(tmp_path / "records") == ["stdlib/Daemon.btrc"]
    with pytest.raises(RuntimeError, match="gcov could not read"):
        coverage.read(build / "missing.gcda")


def test_the_notes_of_a_native_plans_objects_are_kept_where_the_program_writes_its_data(tmp_path: Path) -> None:
    objects = tmp_path / "work" / ".btrc-native-x"
    objects.mkdir(parents=True)
    kept = tmp_path / "gcov"
    commands = []

    def run(command, **options):
        commands.append(list(command))
        if "-c" in command:  # a compile leaves its notes beside the object
            produced = Path(options.get("cwd") or ".", command[command.index("-o") + 1])
            produced.write_text("object")
            produced.with_suffix(".gcno").write_text("notes")
        return subprocess.CompletedProcess(command, 1 if "broken.c" in command else 0, "", "")

    watched = LineCoverage.keeping_notes(kept, run)
    assert watched(["cc", "-c", "generated.c", "-o", "generated.o"], cwd=str(objects)).returncode == 0
    assert watched(["cc", "-c", "unit.c", "-o", str(objects / "unit.o")]).returncode == 0
    watched(["cc", "-c", "broken.c", "-o", "broken.o"], cwd=str(objects))
    watched(["cc", "generated.o", "unit.o", "-o", "program"], cwd=str(objects))

    # Each note is under the kept directory at its own absolute path: GCOV_PREFIX puts the data there too.
    mirrored = kept / objects.resolve().relative_to(objects.resolve().anchor)
    assert sorted(path.name for path in mirrored.iterdir()) == ["generated.gcno", "unit.gcno"]
    assert len(commands) == 4  # every command still ran, and a link or a failed compile keeps nothing


def test_the_recorder_is_configured_by_an_absolute_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(LineCoverage.VARIABLE, raising=False)
    assert LineCoverage.configured() is None
    monkeypatch.setenv(LineCoverage.VARIABLE, str(tmp_path / "lines"))
    assert LineCoverage.configured().directory == tmp_path / "lines"
    for wrong in ("", "relative/lines"):
        monkeypatch.setenv(LineCoverage.VARIABLE, wrong)
        with pytest.raises(ValueError, match="absolute directory"):
            LineCoverage.configured()


def test_the_runner_builds_for_gcov_only_when_coverage_is_asked_for(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = "int main(void) { return 0; }"
    monkeypatch.setattr(runner, "LINE_COVERAGE", None)  # this test also runs inside the coverage job
    plain = runner._gcc_flags(source, "program.c", "program")
    assert not set(LineCoverage.FLAGS) & set(plain)
    assert runner._python_options().debug is False

    monkeypatch.setattr(runner, "LINE_COVERAGE", LineCoverage(tmp_path))
    measured = runner._gcc_flags(source, "program.c", "program")
    # After the gate's own flags, so the program is unoptimised whatever they ask for.
    assert measured[measured.index("program.c") - len(LineCoverage.FLAGS) : measured.index("program.c")] == list(
        LineCoverage.FLAGS
    )
    compile_flags, link_flags = runner._gcc_flags(source, "program.c", "program", native=True)
    assert set(LineCoverage.FLAGS) <= set(compile_flags) and set(LineCoverage.FLAGS) <= set(link_flags)
    # Line directives are what lets gcov name a BTRC line.
    assert runner._python_options().debug is True and runner._python_options().map_stdlib_positions is True


def test_a_module_is_imported_for_the_census_by_the_name_a_program_uses(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    for relative in ("Vector.btrc", "USB/USB.btrc", "USB/USBHID.btrc", "USB/Linux/USBHostProvider.btrc"):
        path = repo / "src/stdlib" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n")

    # A package's facade goes by the package's name.
    assert StdlibCensus(repo, tmp_path / "out").modules() == [
        "USB",
        "USB.Linux.USBHostProvider",
        "USB.USBHID",
        "Vector",
    ]


def test_the_report_counts_code_no_test_reaches_and_groups_by_package(tmp_path: Path) -> None:
    repo = _tree(tmp_path / "repo")
    (repo / "src/stdlib/Crypto").mkdir()
    (repo / "src/stdlib/Crypto/Base64.btrc").write_text("\n")
    directory = repo / "build/coverage"
    (directory / "lines").mkdir(parents=True)
    # The census knows of code in three files; the corpus reached two of them, and one line the census missed.
    (directory / "census.json").write_text(
        json.dumps(
            {
                "lines": {
                    "src/stdlib/Vector.btrc": [10, 11, 12],
                    "src/stdlib/USB/USBHID.btrc": [5, 6],
                    "src/stdlib/Crypto/Base64.btrc": [3, 4],
                },
                "failed": {"GUI": "SDL3/SDL.h: No such file or directory"},
                "private": 3,
            }
        )
    )
    (directory / "lines" / "1.jsonl").write_text(
        json.dumps({"src/stdlib/Vector.btrc": {"10": 4, "11": 0, "20": 1}})
        + "\n"
        + json.dumps({"src/stdlib/USB/USBHID.btrc": {"5": 1}})
        + "\n"
    )
    (directory / "lines" / "1.unrecorded").write_text("stdlib/Daemon.btrc\n")
    (directory / "reference.json").write_text(
        json.dumps(
            {
                "files": {
                    "src/compiler/python/lexer/lexer.py": {
                        "summary": {"num_statements": 10, "covered_lines": 9},
                        "missing_lines": [7],
                    },
                    "src/compiler/python/main.py": {"summary": {"num_statements": 4, "covered_lines": 1}},
                    "src/tests/runner.py": {"summary": {"num_statements": 99, "covered_lines": 99}},
                }
            }
        )
    )

    report = CoverageReport(repo, directory).write()

    assert report["schema"] == "btrc.line-coverage/1" and report["corpus_programs"] == 2
    stdlib = report["stdlib"]
    assert (stdlib["lines"], stdlib["executed"], stdlib["percent"]) == (8, 3, 37.5)
    assert stdlib["packages"] == {
        "Crypto": {"lines": 2, "executed": 0, "percent": 0.0},
        "USB": {"lines": 2, "executed": 1, "percent": 50.0},
        "Vector": {"lines": 4, "executed": 2, "percent": 50.0},
    }
    assert stdlib["files"]["src/stdlib/Vector.btrc"]["missed"] == [11, 12]
    assert stdlib["files"]["src/stdlib/Crypto/Base64.btrc"] == {
        "lines": 2,
        "executed": 0,
        "percent": 0.0,
        "missed": [3, 4],
    }
    # The self-hosted compiler never ran here: its tracked file is listed with nothing known of it.
    assert report["selfhost_compiler"]["files"] == {
        "src/compiler/btrc/Lexer.btrc": {"lines": 0, "executed": 0, "percent": None, "missed": []}
    }
    reference = report["reference_compiler"]
    assert (reference["lines"], reference["executed"], reference["percent"]) == (14, 10, 71.4)
    assert reference["packages"] == {
        "lexer": {"lines": 10, "executed": 9, "percent": 90.0},
        "main": {"lines": 4, "executed": 1, "percent": 25.0},
    }
    assert json.loads((directory / "report.json").read_text()) == report
    text = (directory / "report.md").read_text()
    assert "| Standard library (`src/stdlib`) | 8 | 3 | 37.5% |" in text
    assert "| Crypto | 2 | 0 | 0.0% |" in text
    assert "src/stdlib/Crypto/Base64.btrc" in text.split("no test executes")[1]
    assert "1 stdlib modules could not be compiled alone" in text and "GUI" in text
    assert report["unrecorded_programs"] == ["stdlib/Daemon.btrc"]
    assert "1 corpus programs ran and left no gcov data" in text and "stdlib/Daemon.btrc" in text


def test_one_command_runs_the_whole_job_and_writes_one_report() -> None:
    environment = {
        key: value for key, value in os.environ.items() if key not in {"MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES"}
    }
    output = subprocess.run(
        ["make", "--dry-run", "coverage", "NIX=", "PYTEST_WORKERS=8"],
        cwd=REPO,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=TRANSPILE_TIMEOUT,
    ).stdout.replace("\\\n", " ")
    steps = [line.strip() for line in output.splitlines() if "tools.line_coverage" in line or "-m pytest" in line]

    assert [step.split("tools.line_coverage ")[1].split()[0] for step in steps if "tools.line_coverage" in step] == [
        "census",
        "selfhost-build",
        "report",
    ]
    census, reference, build, selfhost, report = steps
    assert build.endswith("selfhost-build --output build/coverage")
    # The fast tier, measured: every corpus program reports its lines, and coverage.py watches the reference compiler.
    assert f"{LineCoverage.VARIABLE}=" in reference and "/build/coverage/lines" in reference
    assert "--fast" in reference and "--compilers=python" in reference
    assert "--cov=src/compiler/python" in reference and "--cov-report=json:build/coverage/reference.json" in reference
    # Then the corpus through the instrumented self-hosted compiler; its programs are built as ever.
    assert "BTRC_TEST_BTRCC=" in selfhost and "/build/coverage/btrcc/btrcc" in selfhost
    assert "--compilers=btrc" in selfhost and LineCoverage.VARIABLE not in selfhost
    assert census.endswith("--workers 8") and report.endswith("report --output build/coverage")
