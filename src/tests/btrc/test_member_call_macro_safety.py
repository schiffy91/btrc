"""Calls through struct members survive a function-like macro of the same name.

The Windows build force-includes src/runtime/windows/btrc_win_compat.h, which
defines `open(...)` as a function-like macro. Interface dispatch calls a
method through its table, `__btrc_methods->open(...)`, and the macro captured
that call while leaving the table's member declaration alone, so the member
and the call disagreed and the Windows compiler build failed. Both compilers
now parenthesize a member callee, `(__btrc_methods->open)(...)`, which a
function-like macro cannot capture.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.c_toolchains import configured_c_compiler

REPO = Path(__file__).resolve().parents[3]
CC = configured_c_compiler()

PROGRAM = """
interface IOpener {
	int open(int count);
}

class CountingOpener implements IOpener {
	public int opened;
	public CountingOpener() { self.opened = 0; }
	public int open(int count) {
		self.opened = self.opened + count;
		return self.opened;
	}
}

int main() {
	IOpener opener = CountingOpener();
	opener.open(2);
	printf("%d\\n", opener.open(3));
	return 0;
}
"""

# The Windows compatibility layer's own definition, force-included the way
# the Windows workflow includes btrc_win_compat.h.
MACRO = "#define open(...) btrc_open(__VA_ARGS__)\n"

pytestmark = pytest.mark.skipif(not CC or shutil.which(CC[0]) is None, reason="needs a C compiler")


def _build_and_run(generated: Path, tmp_path: Path) -> str:
    header = tmp_path / "open_macro.h"
    header.write_text(MACRO)
    binary = tmp_path / f"{generated.stem}.bin"
    built = subprocess.run(
        [*CC, "-std=c11", "-include", str(header), str(generated), "-o", str(binary), "-lm", "-lpthread"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    assert ran.returncode == 0, ran.stderr
    return ran.stdout


def test_reference_compiler_member_calls_resist_function_like_macros(tmp_path: Path) -> None:
    source = tmp_path / "MemberCallMacro.btrc"
    source.write_text(PROGRAM)
    generated = tmp_path / "reference.c"
    transpiled = subprocess.run(
        [sys.executable, "-m", "src.compiler.python.main", str(source), "--no-cache", "-o", str(generated)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
    )
    assert transpiled.returncode == 0, transpiled.stderr
    assert "(__btrc_methods->open)(" in generated.read_text()
    assert _build_and_run(generated, tmp_path) == "5\n"


def test_selfhost_compiler_member_calls_resist_function_like_macros(tmp_path: Path, immutable_btrcc: Path) -> None:
    source = tmp_path / "MemberCallMacro.btrc"
    source.write_text(PROGRAM)
    generated = tmp_path / "selfhost.c"
    transpiled = subprocess.run(
        [str(immutable_btrcc), str(source), "-o", str(generated)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "BTRC_HOME": str(REPO / "src"), "BTRC_CACHE_DIR": str(tmp_path / "cache")},
    )
    assert transpiled.returncode == 0, transpiled.stderr
    assert "(__btrc_methods->open)(" in generated.read_text()
    assert _build_and_run(generated, tmp_path) == "5\n"
