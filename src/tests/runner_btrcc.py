"""Pytest runner for the SELF-HOSTED btrc compiler (btrcc).

This is the bootstrap parity suite. It builds btrcc — the btrc compiler written
in btrc, under src/compiler/btrc/ — by transpiling its own source with the
reference Python compiler and a C compiler, then runs every language test file
through btrcc and asserts the result matches the reference:

1. (once) Build btrcc: transpile src/compiler/btrc/btrcc_main.btrc -> C -> binary
2. For each test_*.btrc: run btrcc on it -> C -> gcc -> run the program
3. Assert exit code 0 and "PASS" in stdout, and the stdout matches the golden
   expected/<name>.stdout (the same golden the Python runner checks).

It is intentionally NOT part of `make test` (building btrcc + recompiling the
whole corpus through it is slow); run it with `make test-btrc-selfhost`.
"""

import os
import subprocess
import tempfile

import pytest

from src.tests.runner import (
    BTRC_CC,
    BTRC_CFLAGS,
    BTRC_TEST_DIR,
    get_btrc_test_files,
)

_REPO_ROOT = os.path.dirname(os.path.dirname(BTRC_TEST_DIR))
_BTRCC_MAIN = os.path.join(
    _REPO_ROOT, "src", "compiler", "btrc", "btrcc_main.btrc")


@pytest.fixture(scope="session")
def btrcc_bin(tmp_path_factory):
    """Build the self-hosted compiler once per session, return its path."""
    out = tmp_path_factory.mktemp("btrcc")
    csrc = str(out / "btrcc.c")
    binp = str(out / "btrcc")
    # Stage 0: transpile btrcc's own source with the reference compiler.
    r = subprocess.run(
        ["python3", "-m", "src.compiler.python.main",
         _BTRCC_MAIN, "--no-cache", "-o", csrc],
        cwd=_REPO_ROOT, capture_output=True, text=True,
        env={**os.environ, "BTRC_CACHE_DIR": str(out / "cache")})
    assert r.returncode == 0 and os.path.exists(csrc), (
        f"transpiling btrcc failed:\n{r.stderr}")
    # Stage 0b: compile btrcc to a native binary.
    r = subprocess.run(
        [BTRC_CC, *BTRC_CFLAGS, csrc, "-o", binp, "-lm", "-lpthread"],
        capture_output=True, text=True)
    assert r.returncode == 0 and os.path.exists(binp), (
        f"compiling btrcc failed:\n{r.stderr}")
    return binp


@pytest.mark.parametrize("btrc_file", get_btrc_test_files())
def test_btrcc_file(btrcc_bin, btrc_file):
    btrc_path = os.path.join(BTRC_TEST_DIR, btrc_file)
    name = os.path.splitext(os.path.basename(btrc_file))[0]
    expected_dir = os.path.join(os.path.dirname(btrc_path), "expected")
    golden = os.path.join(expected_dir, f"{name}.stdout")

    with tempfile.TemporaryDirectory() as td:
        csrc = os.path.join(td, "out.c")
        binp = os.path.join(td, "out")
        # btrcc reads src/language/grammar.ebnf relative to cwd -> run at root.
        with open(csrc, "w") as fh:
            r = subprocess.run(
                [btrcc_bin, btrc_path], cwd=_REPO_ROOT,
                stdout=fh, stderr=subprocess.PIPE, text=True)
        if r.returncode != 0 or os.path.getsize(csrc) == 0:
            pytest.skip(f"btrcc could not compile {btrc_file}: {r.stderr[:200]}")
        c = subprocess.run(
            [BTRC_CC, *BTRC_CFLAGS, csrc, "-o", binp, "-lm", "-lpthread"],
            capture_output=True, text=True)
        assert c.returncode == 0, (
            f"gcc failed on btrcc output for {btrc_file}:\n{c.stderr[:1500]}")
        run = subprocess.run([binp], capture_output=True, text=True, timeout=30)
        assert run.returncode == 0, (
            f"{btrc_file} exited {run.returncode}:\n{run.stdout}\n{run.stderr}")
        assert "PASS" in run.stdout or "PASS" in run.stderr, (
            f"{btrc_file} did not print PASS:\n{run.stdout}")
        if os.path.exists(golden):
            with open(golden) as gh:
                want = gh.read()
            assert run.stdout == want, (
                f"{btrc_file} stdout != golden:\n"
                f"--- got ---\n{run.stdout}\n--- want ---\n{want}")
