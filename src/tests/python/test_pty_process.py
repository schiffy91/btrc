"""The typed PTY owner against real children, through both compilers."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import native_compile as native_compile
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("sanitize", [False, True])
def test_pty_process(tmp_path, native_compile, sanitize):
    if sys.platform not in ("linux", "darwin"):
        pytest.skip("PTYProcess supports Linux and macOS")
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires the explicitly built native header reader")
    source = ROOT / "src/tests/native/terminal/PTYProcess.btrc"
    plan = tmp_path / "pty.link.json"
    compiled = native_compile(source, plan_path=plan, use_cache=False)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    assert not compiled.diagnostics
    generated = tmp_path / "pty.c"
    generated.write_text(compiled.c_source)
    executable = tmp_path / "pty"
    # The generated owner is exercised under ASan/UBSan as well as strict C11.
    flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic-errors"]
    if sanitize:
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    NativePlanBuilder().build(
        plan_path=plan,
        generated_c=generated,
        output=executable,
        optimization=0,
        compile_flags=flags,
        link_flags=flags,
    )
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: PTY process IO, deadlines, exit status and owned cleanup\n"
