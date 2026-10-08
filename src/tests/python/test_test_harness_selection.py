"""Fail-closed compiler-matrix selection for the language test harness."""

import errno
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.tests.c_toolchains import HostCompilerDiagnostics
from src.tests.conftest import _configured_test_btrcc, _parse_compilers


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("both", ["python", "btrc"]),
        ("python", ["python"]),
        ("btrc", ["btrc"]),
        ("python,btrc", ["python", "btrc"]),
        (" btrc , python ", ["btrc", "python"]),
        ("python,python", ["python"]),
    ),
)
def test_parse_compilers(raw: str, expected: list[str]) -> None:
    assert _parse_compilers(raw) == expected


@pytest.mark.parametrize("raw", ("", " ", "unknown", "python,", "both,python"))
def test_invalid_compiler_selection_raises_usage_error(raw: str) -> None:
    with pytest.raises(pytest.UsageError):
        _parse_compilers(raw)


def test_prebuilt_btrcc_override_is_optional_and_resolves_absolute_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BTRC_TEST_BTRCC", raising=False)
    assert _configured_test_btrcc() is None

    binary = tmp_path / "btrcc"
    binary.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("BTRC_TEST_BTRCC", str(binary))
    assert _configured_test_btrcc() == binary.resolve()


@pytest.mark.parametrize("configured", ("", "relative/btrcc"))
def test_prebuilt_btrcc_override_rejects_non_absolute_paths(
    configured: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BTRC_TEST_BTRCC", configured)
    with pytest.raises(pytest.UsageError, match="absolute"):
        _configured_test_btrcc()


def test_prebuilt_btrcc_override_rejects_missing_or_non_executable_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing-btrcc"
    monkeypatch.setenv("BTRC_TEST_BTRCC", str(missing))
    with pytest.raises(pytest.UsageError, match="does not resolve"):
        _configured_test_btrcc()

    if os.name != "nt":
        binary = tmp_path / "btrcc"
        binary.write_text("not executable\n", encoding="utf-8")
        binary.chmod(0o644)
        monkeypatch.setenv("BTRC_TEST_BTRCC", str(binary))
        with pytest.raises(pytest.UsageError, match="not executable"):
            _configured_test_btrcc()


@pytest.mark.parametrize("removed", ("wrapper", "interpreter", "parent"))
def test_selected_compiler_launch_evidence_distinguishes_missing_components(tmp_path: Path, removed: str) -> None:
    parent = tmp_path / "tool"
    parent.mkdir()
    interpreter = tmp_path / "interpreter"
    if os.name == "posix":
        interpreter.symlink_to(sys.executable)
    else:
        interpreter.write_bytes(b"test interpreter identity")
    wrapper = parent / "compiler"
    wrapper.write_text(f"#!{interpreter}\npass\n", encoding="utf-8")
    wrapper.chmod(0o755)
    diagnostics = HostCompilerDiagnostics((str(wrapper),))
    before = diagnostics.selected[str(wrapper)]
    assert "error" not in before["lstat"] and "error" not in before["interpreter"]["lstat"]
    (interpreter if removed == "interpreter" else wrapper).unlink()
    if removed == "parent":
        parent.rmdir()
    if os.name == "posix" or removed != "interpreter":
        with pytest.raises(FileNotFoundError) as caught:
            subprocess.run([str(wrapper)], check=True, timeout=5)
        error = caught.value
    else:
        # Windows does not execute shebangs. It still records the same path
        # facts; only POSIX hosts claim the real interpreter-launch failure.
        error = FileNotFoundError(errno.ENOENT, "test launch", str(wrapper))
    evidence = diagnostics.failure(error)
    assert evidence is not None and evidence["selected"] == before
    after = evidence["failure"]
    if removed == "interpreter":
        assert after["lstat"] == before["lstat"]
        assert after["interpreter"]["lstat"]["errno"] == errno.ENOENT
    else:
        assert after["lstat"]["errno"] == errno.ENOENT
        missing = parent if removed == "parent" else wrapper
        assert after["unavailable_component"]["path"] == str(missing.resolve())
    assert error.filename == str(wrapper) and error.errno == errno.ENOENT


def test_compiler_launch_evidence_does_not_invent_loss_or_select_another_tool(tmp_path: Path) -> None:
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"an intact ordinary file")
    diagnostics = HostCompilerDiagnostics((str(compiler),))
    error = FileNotFoundError(errno.ENOENT, "historical failure", os.fsencode(compiler))
    evidence = diagnostics.failure(error)
    assert evidence["failure"]["lstat"] == evidence["selected"]["lstat"]
    assert evidence["failure"]["header"] == "no shebang"
    assert diagnostics.failure(FileNotFoundError(errno.ENOENT, "other", str(tmp_path / "other"))) is None
    assert diagnostics.failure(PermissionError(errno.EACCES, "other", str(compiler))) is None
    assert diagnostics.failure(FileNotFoundError("no filename")) is None


@pytest.mark.parametrize("header", (b"#!\n", b"#!/missing\r\n", b"#!" + b"x" * 5000))
def test_compiler_launch_evidence_bounds_malformed_headers(tmp_path: Path, header: bytes) -> None:
    compiler = tmp_path / "compiler"
    compiler.write_bytes(header)
    evidence = HostCompilerDiagnostics.snapshot(str(compiler))
    assert evidence["header"] in {"malformed shebang", "unterminated or oversized shebang"}
    assert "interpreter" not in evidence


def test_compiler_launch_evidence_never_reads_special_files_or_loops(tmp_path: Path, monkeypatch) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    paths = [directory]
    if os.name == "posix":
        fifo = tmp_path / "fifo"
        os.mkfifo(fifo, 0o700)
        paths.append(fifo)
        loop = tmp_path / "loop"
        loop.symlink_to("loop")
        paths.append(loop)
        target = tmp_path / "target"
        (target / "nested").mkdir(parents=True)
        actual = target / "compiler"
        actual.write_bytes(b"binary")
        link = tmp_path / "alias"
        link.symlink_to(target / "nested", target_is_directory=True)
        facts = HostCompilerDiagnostics.path_facts(str(link / ".." / "compiler"))
        assert facts["realpath"] == str(actual.resolve())
        assert facts["resolved_lstat"] == HostCompilerDiagnostics.identity(str(actual))
    with monkeypatch.context() as patch:
        patch.setattr(os, "open", lambda *args: pytest.fail("diagnostic opened a special file"))
        for path in paths:
            evidence = HostCompilerDiagnostics.snapshot(str(path))
            assert evidence["header"] == "not a resolved regular file"
    if os.name == "posix":
        assert evidence["limit"] == "symlink hops"


def test_compiler_launch_evidence_keeps_diagnostic_errors_as_data(tmp_path: Path, monkeypatch) -> None:
    compiler = tmp_path / "compiler"
    compiler.write_bytes(b"readable at selection")
    diagnostics = HostCompilerDiagnostics((str(compiler),))

    def denied(*args):
        raise PermissionError(errno.EACCES, "diagnostic read refused")

    monkeypatch.setattr(os, "open", denied)
    error = FileNotFoundError(errno.ENOENT, "original launch", str(compiler))
    evidence = diagnostics.failure(error)
    assert evidence["failure"]["diagnostic_error"] == "PermissionError"
    assert evidence["failure"]["errno"] == errno.EACCES
    assert error.errno == errno.ENOENT and error.filename == str(compiler)


def test_missing_compiler_evidence_preserves_actual_pytest_failure(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    compiler = tmp_path / "compiler"
    compiler.write_text("#!/missing/test-interpreter\n", encoding="utf-8")
    compiler.chmod(0o755)
    # Install the real hook with a test-owned selection, not a subprocess shim.
    (tmp_path / "conftest.py").write_text(
        "from src.tests import conftest as owner\n"
        "from src.tests.c_toolchains import HostCompilerDiagnostics\n"
        f"owner.HOST_COMPILER_DIAGNOSTICS = HostCompilerDiagnostics(({str(compiler)!r},))\n"
        "pytest_addoption = owner.pytest_addoption\n"
        "pytest_configure = owner.pytest_configure\n"
        "pytest_runtest_makereport = owner.pytest_runtest_makereport\n",
        encoding="utf-8",
    )
    (tmp_path / "test_launch.py").write_text(
        "import subprocess\nfrom pathlib import Path\n"
        "def test_original_failure():\n"
        f"    path = {str(compiler)!r}\n"
        "    Path(path).unlink()\n"
        "    subprocess.run([path], check=True, timeout=5)\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment.update(PYTHONPATH=str(root), PYTEST_ADDOPTS="", PYTHONDONTWRITEBYTECODE="1")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-c",
            str(root / "pyproject.toml"),
            f"--rootdir={tmp_path}",
            f"--confcutdir={tmp_path}",
            "-o",
            "addopts=",
            "test_launch.py",
            "--junitxml=report.xml",
            "--skip-report=skip-report.json",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    cases = list(ET.parse(tmp_path / "report.xml").iter("testcase"))
    assert len(cases) == 1 and cases[0].attrib["name"] == "test_original_failure"
    failure = cases[0].find("failure")
    assert failure is not None and "FileNotFoundError" in failure.attrib["message"]
    assert cases[0].find("error") is None and cases[0].find("skipped") is None
    assert "host compiler launch evidence" in result.stdout
    evidence = next(json.loads(line) for line in result.stdout.splitlines() if line.startswith('{"failure":'))
    assert evidence["selected"]["path"] == str(compiler)
    assert evidence["failure"]["lstat"]["errno"] == errno.ENOENT
    ledger = json.loads((tmp_path / "skip-report.json").read_text())
    assert ledger["tests"] == {"test_launch.py::test_original_failure": "failed"}
