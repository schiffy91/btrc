"""The self-hosted helper selection closes declared dependencies transitively."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

# A try block with no managed values in it. Nothing in the lowered IR names an
# ARC helper, so __btrc_run_cleanups reaches __btrc_is_destroyed purely by the
# scan of its own source text, and __btrc_is_destroyed's declared dependencies
# are reachable no other way. Adding a managed local to this program hides the
# defect, because then the IR names those helpers directly.
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


@pytest.mark.skipif(not COMPILERS, reason="needs a C compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS)
def test_source_discovered_helpers_keep_their_declared_dependencies(
    semantic_btrcc: Path,
    tmp_path: Path,
    c_compiler: str,
) -> None:
    """A helper reached only by a source scan must still bring its dependencies.

    Selection reaches helpers two ways: names appearing in lowered IR, and names
    appearing in another helper's source. Closing declared dependencies once,
    before the source scan, drops the dependencies of everything the scan
    introduces. The omission is invisible in the emitted text -- the calls are
    all there -- and only shows up as C that calls undefined runtime functions,
    so this compiles the result and rejects implicit declarations.
    """

    result, generated = _compile_source(semantic_btrcc, tmp_path, CLEANUP_SOURCE, no_stdlib=False)
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "__btrc_is_destroyed" in emitted, "fixture no longer exercises the source-scan path"

    binary = tmp_path / "program"
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Werror=implicit-function-declaration",
            "-O0",
            str(generated),
            "-o",
            str(binary),
            "-lm",
            "-lpthread",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert compiled.returncode == 0, compiled.stderr

    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    assert "PASS" in run.stdout
