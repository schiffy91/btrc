"""Bootstrap fixed-point test for the self-hosted compiler (btrcc).

The self-hosted compiler is only truly "self-hosting" if it can compile its OWN
source and the result is stable: compiling the compiler with itself, then again
with that output, must yield byte-identical C (a fixed point). This walks the
three-stage bootstrap and asserts the fixed point:

    btrcc1 = cc(  btrcpy(compiler source) )      # reference-built (stage 1)
    btrcc2 = cc( btrcc1(compiler source) )       # self-built     (stage 2)
    btrcc3.c =   btrcc2(compiler source)         # self-built again (stage 3)
    assert btrcc2.c == btrcc3.c                  # FIXED POINT

It also confirms the self-built compiler is functional (compiles a sample
program to its golden output). Uses whatever C compiler `BTRC_CC` selects
(default `cc`), so it runs under gcc and clang alike.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
BTRC_MAIN = os.path.join("src", "compiler", "btrc", "btrcc_main.btrc")
CC = shlex.split(os.environ.get("BTRC_CC", "cc"))
CFLAGS = shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11"))
BOOTSTRAP_TIMEOUT = int(os.environ.get("BTRC_BOOTSTRAP_TIMEOUT_SECONDS", "1200"))

pytestmark = pytest.mark.skipif(
    not CC or shutil.which(CC[0]) is None,
    reason="needs a C compiler",
)


def _run(cmd, **kw):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, **kw)


def _transpile_with_python(out_c: str) -> None:
    """Stage 1 source: reference compiler transpiles the btrcc source to C."""
    # Use "python3" (on PATH), not sys.executable: under xdist the worker's
    # sys.executable can point at a nix env-wrapper path that isn't directly
    # exec'able from a subprocess. This matches runner.py's btrcc_bin fixture.
    r = _run(["python3", "-m", "src.compiler.python.main", BTRC_MAIN, "--no-cache", "-o", out_c])
    assert r.returncode == 0 and os.path.exists(out_c), f"btrcpy failed to transpile btrcc:\n{r.stderr[:2000]}"


def _cc(src_c: str, out_bin: str) -> None:
    r = _run([*CC, *CFLAGS, src_c, "-o", out_bin, "-lm", "-lpthread"])
    assert r.returncode == 0 and os.path.exists(out_bin), (
        f"{' '.join(CC)} failed to build {os.path.basename(src_c)}:\n{r.stderr[:3000]}"
    )


def _btrcc(binary: str, in_btrc: str, out_c: str) -> None:
    """Run a btrcc binary on a .btrc file, capturing emitted C to out_c."""
    r = _run([binary, in_btrc], timeout=BOOTSTRAP_TIMEOUT)
    assert r.returncode == 0 and r.stdout.strip(), f"{os.path.basename(binary)} failed on {in_btrc}:\n{r.stderr[:2000]}"
    with open(os.path.join(REPO, out_c), "w") as f:
        f.write(r.stdout)


def test_bootstrap_fixed_point(tmp_path):
    d = str(tmp_path)
    c1, b1 = os.path.join(d, "btrcc1.c"), os.path.join(d, "btrcc1")
    c2, b2 = os.path.join(d, "btrcc2.c"), os.path.join(d, "btrcc2")
    c3 = os.path.join(d, "btrcc3.c")

    # Stage 1: reference compiler builds btrcc1.
    _transpile_with_python(c1)
    _cc(c1, b1)

    # Stage 2: btrcc1 compiles its OWN source -> btrcc2 (the self-built compiler).
    _btrcc(b1, BTRC_MAIN, c2)
    _cc(c2, b2)

    # Stage 3: btrcc2 compiles its OWN source again.
    _btrcc(b2, BTRC_MAIN, c3)

    # The self-built compiler reproduces itself bit-for-bit: a true fixed point.
    with open(c2) as f2, open(c3) as f3:
        assert f2.read() == f3.read(), (
            "bootstrap not at a fixed point: btrcc2.c != btrcc3.c (the self-built compiler does not reproduce itself)"
        )


def test_self_built_compiler_is_functional(tmp_path):
    """The stage-2 (self-built) compiler must compile a program to its golden."""
    d = str(tmp_path)
    c1, b1 = os.path.join(d, "btrcc1.c"), os.path.join(d, "btrcc1")
    c2, b2 = os.path.join(d, "btrcc2.c"), os.path.join(d, "btrcc2")
    _transpile_with_python(c1)
    _cc(c1, b1)
    _btrcc(b1, BTRC_MAIN, c2)
    _cc(c2, b2)

    sample = os.path.join("src", "tests", "classes", "test_inherited_operator_overload.btrc")
    prog_c = os.path.join(d, "sample.c")
    prog_bin = os.path.join(d, "sample")
    _btrcc(b2, sample, prog_c)
    _cc(prog_c, prog_bin)
    run = subprocess.run([prog_bin], capture_output=True, text=True, timeout=30)
    assert run.returncode == 0, f"sample crashed: {run.stderr[:1000]}"
    golden = os.path.join(REPO, "src", "tests", "classes", "expected", "test_inherited_operator_overload.stdout")
    with open(golden) as g:
        assert run.stdout == g.read(), "self-built compiler output != golden"
