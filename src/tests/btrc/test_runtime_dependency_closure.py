"""Self-hosted runtime-helper reachability follows C tokens, not prose."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import _compile_source
from src.tests.c_toolchains import HOST_C_COMPILERS, requires_host_c_compiler
from src.tests.runner import BTRC_TRANSPILE_TIMEOUT

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


# A try block with no managed values still registers cleanup slots, whose helper
# contains an explanatory comment naming the cleanup runner.  That prose must
# not make the runner live when no emitted statement can call it.
CLEANUP_SOURCE = """
int main() {
    try {
        print("no error");
    } catch (string error) {
        print("should not reach");
    }
    print("PASS");
    return 0;
}
"""


@requires_host_c_compiler
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS)
def test_helper_comment_does_not_materialize_an_unused_runtime_function(
    semantic_btrcc: Path,
    tmp_path: Path,
    c_compiler: str,
) -> None:
    """Comments cannot create reachability or Clang-O0 unused functions."""

    result, generated = _compile_source(semantic_btrcc, tmp_path, CLEANUP_SOURCE, no_stdlib=False)
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "static inline void __btrc_register_cleanup_kind(" in emitted
    assert "static inline void __btrc_run_cleanups(" not in emitted

    binary = tmp_path / "program"
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O0",
            str(generated),
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=BTRC_TRANSPILE_TIMEOUT,
    )
    assert compiled.returncode == 0, compiled.stderr

    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "PASS" in run.stdout
