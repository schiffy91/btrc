"""The observer diagnostic preserves its exact selection and failed outcomes."""

import xml.etree.ElementTree as ET

import pytest

from tools.ui.windows_user_diagnostic import UserCensusDiagnostic


def test_user_diagnostic_exact_selection():
    nodes = UserCensusDiagnostic.BUILD
    UserCensusDiagnostic.exact_collection("\n".join(nodes) + "\n2 tests collected", nodes)
    with pytest.raises(ValueError, match="Unexpected collection"):
        UserCensusDiagnostic.exact_collection("\n".join(nodes[:1]), nodes)
    with pytest.raises(ValueError, match="Unexpected collection"):
        UserCensusDiagnostic.exact_collection("\n".join((*nodes, UserCensusDiagnostic.RUN)), nodes)


@pytest.mark.parametrize("outcome", [None, "failure", "error", "skipped"])
def test_user_diagnostic_requires_executed_pass(tmp_path, outcome):
    root = ET.Element("testsuites")
    case = ET.SubElement(ET.SubElement(root, "testsuite"), "testcase")
    if outcome:
        ET.SubElement(case, outcome)
    path = tmp_path / "result.xml"
    ET.ElementTree(root).write(path)
    assert UserCensusDiagnostic.junit_passed(path, 1) is (outcome is None)
    assert not UserCensusDiagnostic.junit_passed(path, 2)


def test_user_diagnostic_hashes_detect_changes(tmp_path):
    binary = tmp_path / "native-shell-windows-x64" / "shell.exe"
    binary.parent.mkdir()
    binary.write_bytes(b"original")
    before = UserCensusDiagnostic.hashes(tmp_path)
    assert set(before) == {"native-shell-windows-x64/shell.exe"}
    binary.write_bytes(b"changed")
    assert before != UserCensusDiagnostic.hashes(tmp_path)


def test_user_diagnostic_runs_both_modes_after_first_failure(tmp_path, monkeypatch):
    import json

    monkeypatch.chdir(tmp_path)
    evidence = tmp_path / "build/user-census-executables"
    evidence.mkdir(parents=True)
    (evidence / "sha256.json").write_text(json.dumps({}))
    # Provenance is input to this protocol test. Avoid making platform's own
    # subprocess probes inherit the git command's text-only response.
    monkeypatch.setattr("tools.ui.windows_user_diagnostic.platform.platform", lambda: "test-platform")
    monkeypatch.setattr("tools.ui.windows_user_diagnostic.subprocess.check_output", lambda *a, **k: "source-head\n")
    runner = UserCensusDiagnostic("run", tmp_path / "evidence")
    observed = []

    def command(name, args, environment):
        observed.append(name)
        if name == "collection":
            (runner.output / "collection.log").write_text(UserCensusDiagnostic.RUN + "\n")
            return 0
        assert environment["BTRC_UI_SHELL_CYCLES"] == "100"
        assert environment["BTRC_UI_SHELL_USER_DIAGNOSTIC"] == name
        root = ET.Element("testsuites")
        case = ET.SubElement(ET.SubElement(root, "testsuite"), "testcase")
        if name == "count-only":
            ET.SubElement(case, "failure")
        ET.ElementTree(root).write(runner.output / f"{name}.xml")
        return int(name == "count-only")

    monkeypatch.setattr(runner, "command", command)
    assert runner.run() == 1
    assert observed == ["collection", "count-only", "query-bracket"]


def test_user_diagnostic_malformed_junit_is_not_a_pass(tmp_path):
    path = tmp_path / "interrupted.xml"
    path.write_text("<testsuites><testsuite>")
    assert not UserCensusDiagnostic.junit_passed(path, 1)


def test_user_diagnostic_retains_separate_mode_and_normal_artifacts(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from src.tests.python import test_native_ui_shell_windows as driver

    evidence = tmp_path / "executables"
    binary = evidence / "native-shell-windows-x64" / driver.shell_name("python", "windows-x64", True)
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"test executable placeholder; never launched")
    observer = binary.with_name("observer-" + binary.name)
    observer.write_bytes(b"test observer placeholder; never launched")
    monkeypatch.setattr(driver, "REPO", tmp_path)
    monkeypatch.setattr(driver, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setenv("BTRC_WIN32_EVIDENCE_DIR", str(evidence))
    monkeypatch.setenv("BTRC_UI_SHELL_CYCLES", "100")
    monkeypatch.setenv("BTRC_UI_SHELL_NO_AX", "1")
    monkeypatch.setenv("BTRC_UI_SHELL_NO_SCROLL", "1")
    base = tmp_path / "build/ui-shell" / binary.stem
    for mode in ("", *UserCensusDiagnostic.MODES):
        monkeypatch.setenv("BTRC_UI_SHELL_USER_DIAGNOSTIC", mode)
        invocation = tmp_path / (mode or "normal")
        invocation.mkdir()
        label = mode or "normal"

        def failed_shell(command, environment, timeout, label=label):
            assert "BTRC_UI_SHELL_NO_AX" not in environment
            assert "BTRC_UI_SHELL_NO_SCROLL" not in environment
            if command == [str(observer)]:
                assert timeout == 60
                return SimpleNamespace(
                    returncode=0,
                    stdout="OBSERVER passed\n" + label,
                    stderr="SHELL resource-window cycle=0 thread=1 handle=0x1 "
                    "message-only=0 class=BtrcObserverForeignAnsi\n" + label,
                )
            assert command[0] == str(binary) and command[1] == "102" and timeout == 1200
            return SimpleNamespace(returncode=7, stdout=label, stderr=label + " failure evidence")

        monkeypatch.setattr(driver, "run_shell", failed_shell)
        with pytest.raises(AssertionError, match="Shell returncode=7"):
            driver.test_windows_native_shell_runs(invocation, monkeypatch, "python", "windows-x64", True)
    for mode in ("", *UserCensusDiagnostic.MODES):
        directory = base / mode if mode else base
        assert (directory / "shell.stdout").read_text() == (mode or "normal")
        assert (directory / "shell.stderr").read_text() == (mode or "normal") + " failure evidence"
        assert (directory / "observer.stdout").read_text() == "OBSERVER passed\n" + (mode or "normal")
        assert (directory / "observer.stderr").read_text() == (
            "SHELL resource-window cycle=0 thread=1 handle=0x1 "
            "message-only=0 class=BtrcObserverForeignAnsi\n" + (mode or "normal")
        )
    assert not (base / "BTRC_UI_SHELL_NO_SCROLL").exists()
