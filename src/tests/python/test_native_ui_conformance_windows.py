"""The GUI conformance suite's Windows rows: cross-built on Linux or macOS, run on Windows.

On a host with the dev shell, the build tests compile the suite
(src/tests/native/gui/conformance) for windows-x86_64 and windows-aarch64
through both compilers, plain and under UBSan, the way the shell rows are
built (test_native_ui_shell_windows.py). With BTRC_WIN32_EVIDENCE_DIR set,
each row's executable, the wgpu-native DLL, the WebView2 loader and the
suite's web bundle are copied into gui-conformance-<target> there. On Windows, each case of each
published executable runs as its own process, with real input: the probe
moves the session's pointer and types on its keyboard (SendInput), so the
rows run only in a session made for tests. windows.yml's win32-native job
is one; the local guest is another (tools/target_hosts/windows/vm.py).
"""

import os
import shutil
import sys
import tomllib
from pathlib import Path

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.python import test_native_ui_shell_windows as shell
from src.tests.python.native_ui_shell_fixtures import transpile

REPO = Path(__file__).resolve().parents[3]
SUITE = REPO / "src/tests/native/gui/conformance"
CASES = tomllib.loads((SUITE / "cases.toml").read_text(encoding="utf-8"))["case"]
NAMES = [case["name"] for case in CASES]
NEEDS = {case["name"]: case["needs"] for case in CASES if "needs" in case}
# What the Windows provider has of what a case may need: a web view, and no
# FreeType (a font face from a file is FreeType's, which the Windows SDK
# does not carry).
HAS = {"web", "modal", "wheel"}


def suite_name(frontend, target, sanitized):
    return f"gui-conformance-{shell.FRONTENDS[frontend]}-{target}{'-ubsan' if sanitized else ''}.exe"


def published(target):
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    return Path(evidence) / f"gui-conformance-{target}" if evidence else None


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "ubsan"])
@pytest.mark.parametrize("target", sorted(shell.TARGETS))
@pytest.mark.parametrize("frontend", sorted(shell.FRONTENDS))
def test_windows_conformance_builds(tmp_path, request, monkeypatch, frontend, target, sanitized):
    if sys.platform == "win32":
        pytest.skip("cross-builds on a Linux or macOS host with the dev shell; Windows runs the published executables")
    NativeBindingPackage.require_reader()
    dll = shell.cross_environment(target, tmp_path, monkeypatch)
    generated, plan = tmp_path / "Suite.c", tmp_path / "Suite.json"
    result = transpile(SUITE / "Main.btrc", generated, plan, frontend, request, shell.TARGETS[target][0])
    assert result.returncode == 0, result.stderr
    assert "warning:" not in result.stderr.lower(), result.stderr
    executable = shell.link(
        plan, generated, tmp_path / suite_name(frontend, target, sanitized), [], shell.UBSAN if sanitized else []
    )
    directory = published(target)
    if directory is None:
        return
    directory.mkdir(parents=True, exist_ok=True)
    # The web view's loader ships beside the program, as wgpu-native does.
    for path in (
        executable,
        dll,
        shell.webview2_loader(target, tmp_path),
    ):
        shutil.copy2(path, directory / path.name)
    shutil.copytree(SUITE / "web", directory / "web", dirs_exist_ok=True)


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "ubsan"])
@pytest.mark.parametrize("target", sorted(shell.TARGETS))
@pytest.mark.parametrize("frontend", sorted(shell.FRONTENDS))
@pytest.mark.parametrize("name", [name for name in NAMES if name not in NEEDS or NEEDS[name] in HAS])
def test_windows_conformance_case(name, frontend, target, sanitized):
    if sys.platform != "win32":
        pytest.skip("requires Windows: windows.yml's win32-native job runs the executables the build tests publish")
    directory = published(target)
    if directory is None:
        pytest.skip("BTRC_WIN32_EVIDENCE_DIR names no published Windows conformance executables")
    directory = directory.resolve()
    executable = directory / suite_name(frontend, target, sanitized)
    assert executable.is_file(), sorted(path.name for path in directory.iterdir()) if directory.is_dir() else directory
    environment = {
        **os.environ,
        # The probe sends real input: this session was made for tests.
        "BTRC_UI_PRIVATE_SESSION": "1",
        # A hosted runner cannot be watched: the probe says what it found.
        "BTRC_CONFORMANCE_TRACE": "1",
        "BTRC_CONFORMANCE_WEB": str(directory / "web"),
        "UBSAN_OPTIONS": "halt_on_error=1",
    }
    result = shell.run_shell([str(executable), name], environment, 180)
    report = f"{name} on {target} ({frontend}, {'ubsan' if sanitized else 'plain'})\n{result.stdout}{result.stderr}"
    assert result.returncode == 0 and f"CASE {name} PASS" in result.stdout, report
