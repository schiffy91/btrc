"""A Win32 window subclass from the real MinGW commctrl.h, through both compilers.

Stored C registrations (package-manifest.md, "Stored C registrations") were
designed against comctl32's SetWindowSubclass/RemoveWindowSubclass. This test
imports the real declarations from zig's MinGW-w64 headers for windows-x64 and
windows-arm64, compiles the program with both compilers and links it with zig
against user32 and comctl32. When BTRC_WIN32_EVIDENCE_DIR is set, each
executable is copied there; windows.yml's win32-native job runs them on a
Windows runner and checks their output. On this host the test proves the
import, the generated C and the link, not the execution.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.results import CompilerOptions
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.native_import_fixtures import zig_libc

REPO = Path(__file__).resolve().parents[3]
EXPECTED = "win32-subclass first=42 after=0 cancelled=1 destroyed=1 open=0"
TARGETS = {"windows-x64": "x86_64", "windows-arm64": "aarch64"}

MANIFEST = """manifest-version = 1
[package]
name = "win32Subclass"
[[native.bindings]]
module = "Win32"
header = "Win32.h"
language = "c"
standard = "c11"
os = ["windows"]
symbols = ["CreateWindowExA", "DestroyWindow", "SendMessageW", "SetWindowSubclass", "RemoveWindowSubclass", "DefSubclassProc", "WM_USER", "HWND_MESSAGE"]
[native.bindings.callbacks."SetWindowSubclass.pfnSubclass"]
interface = "IWindowSubclass"
context = ["uIdSubclass", "dwRefData"]
context-index = [4, 5]
lifetime = "stored"
executor = "caller"
failure = "abort"
registration-status = "nonzero"
activation-failure = "unpublished"
unregister = "RemoveWindowSubclass"
unregister-status = "nonzero"
captured-handles = ["hWnd"]
cancellation = "entry-barrier"
"""

PROGRAM = """import Library.Callback;
import ./Win32.btrc;
#include <stdio.h>
int destroyed = 0;
class Subclass implements IWindowSubclass {
	public LRESULT invoke(HWND window, UINT message, WPARAM wParam, LPARAM lParam) {
		if (message != WM_USER) { return DefSubclassProc(window, message, wParam, lParam); }
		return lParam + 1;
	}
	public void __del__() { destroyed++; }
}
int main() {
	HWND window = CreateWindowExA(0, "STATIC", "btrc", 0, 0, 0, 0, 0, HWND_MESSAGE, null, null, null);
	if (window == null) {
		printf("win32-subclass no window\\n");
		return 1;
	}
	var scope = CallbackScope();
	ICallbackRegistration registration = SetWindowSubclass(window, Subclass(), scope);
	LRESULT first = SendMessageW(window, WM_USER, 0, 41);
	bool cancelled = scope.cancel() == CALLBACK_CANCELLATION_COMPLETE;
	LRESULT after = SendMessageW(window, WM_USER, 0, 41);
	DestroyWindow(window);
	printf("win32-subclass first=%lld after=%lld cancelled=%d destroyed=%d open=%d\\n", (long long)first, (long long)after, (int)cancelled, destroyed, (int)registration.isOpen());
	return first == 42 && after == 0 && cancelled && destroyed == 1 && !registration.isOpen() ? 0 : 2;
}
"""


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    (root / "btrc.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "Win32.h").write_text(
        "#define WIN32_LEAN_AND_MEAN\n#include <windows.h>\n#include <commctrl.h>\n", encoding="utf-8"
    )
    (root / "src/Win32.btrc").write_text("// Native wrapper module.\n", encoding="utf-8")
    source = root / "src/Main.btrc"
    source.write_text(PROGRAM, encoding="utf-8")
    return source


def transpile(frontend, source, target, request, monkeypatch):
    sysroot = zig_libc()
    triple = {"windows-x64": "x86_64-w64-windows-gnu", "windows-arm64": "aarch64-w64-windows-gnu"}[target]
    monkeypatch.setenv("BTRC_NATIVE_TARGET", triple)
    monkeypatch.setenv("BTRC_NATIVE_SYSROOT", str(sysroot))
    if frontend == "reference":
        result = Compiler().compile(
            source.read_text(encoding="utf-8"),
            str(source),
            CompilerOptions(include_stdlib=False, use_cache=False, target=target),
        )
        assert result.successful, (result.failure, result.diagnostics)
        return result.c_source
    btrcc = request.getfixturevalue("immutable_btrcc")
    completed = subprocess.run(
        [str(btrcc), "--no-stdlib", "--no-cache", "--target", target, str(source)],
        env={**os.environ, "BTRC_HOME": str(REPO / "src")},
        capture_output=True,
        text=True,
        timeout=TOOL_TIMEOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


@pytest.mark.parametrize("target", sorted(TARGETS))
@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_win32_window_subclass_builds_from_real_headers(project, frontend, target, request, monkeypatch, tmp_path):
    generated = tmp_path / "Main.c"
    generated.write_text(transpile(frontend, project, target, request, monkeypatch), encoding="utf-8")
    executable = tmp_path / f"win32-subclass-{frontend}-{target}.exe"
    built = subprocess.run(
        [
            shutil.which("zig"),
            "cc",
            "-target",
            f"{TARGETS[target]}-windows-gnu",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            "-I",
            str(REPO / "src/runtime/windows"),
            "-include",
            str(REPO / "src/runtime/windows/btrc_win_compat.h"),
            "-I",
            str(project.parent.parent),
            str(generated),
            "-o",
            str(executable),
            "-lcomctl32",
            "-luser32",
            "-lm",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    assert executable.read_bytes()[:2] == b"MZ"
    evidence = os.environ.get("BTRC_WIN32_EVIDENCE_DIR")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, Path(evidence) / executable.name)
    if sys.platform == "win32":
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=60, check=False)
        assert ran.returncode == 0 and ran.stdout.strip() == EXPECTED, (ran.returncode, ran.stdout, ran.stderr)
