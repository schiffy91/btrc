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

import filecmp
import os
import tempfile
import unittest

from src.tests.btrc.bootstrap_harness import (
    EXE_SUFFIX,
    REPO,
    compile_c,
    run_btrcc,
    run_stage,
    snapshot_compiler_inputs,
    transpile_with_python,
)
from src.tests.c_toolchains import host_c_compiler


@unittest.skipUnless(host_c_compiler() is not None, "needs a C compiler")
class TestBootstrap(unittest.TestCase):
    def test_bootstrap_fixed_point_and_self_built_compiler_is_functional(self):
        """Prove the fixed point, then exercise that same self-built compiler."""
        with tempfile.TemporaryDirectory(prefix="btrc-bootstrap-") as d:
            project_root, data_root, compiler_source = snapshot_compiler_inputs(d)
            c1 = os.path.join(d, "btrcc1.c")
            b1 = os.path.join(d, f"btrcc1{EXE_SUFFIX}")
            c2 = os.path.join(d, "btrcc2.c")
            b2 = os.path.join(d, f"btrcc2{EXE_SUFFIX}")
            c3 = os.path.join(d, "btrcc3.c")

            # Stage 1: reference compiler builds btrcc1.
            transpile_with_python(project_root, data_root, compiler_source, c1)
            compile_c(c1, b1, workdir=project_root)

            # Stage 2: btrcc1 compiles its OWN source -> btrcc2.
            run_btrcc(b1, compiler_source, c2, data_root=data_root, workdir=project_root)
            compile_c(c2, b2, workdir=project_root)

            # Stage 3: btrcc2 compiles its OWN source again.
            run_btrcc(b2, compiler_source, c3, data_root=data_root, workdir=project_root)

            self.assertTrue(
                filecmp.cmp(c2, c3, shallow=False),
                "bootstrap not at a fixed point: btrcc2.c != btrcc3.c "
                "(the self-built compiler does not reproduce itself)",
            )

            sample = os.path.join(REPO, "src", "tests", "classes", "InheritedOperatorOverload.btrc")
            prog_c = os.path.join(d, "sample.c")
            prog_bin = os.path.join(d, f"sample{EXE_SUFFIX}")
            run_btrcc(b2, sample, prog_c, data_root=data_root, workdir=project_root)
            compile_c(prog_c, prog_bin, workdir=project_root)
            run = run_stage([prog_bin], cwd=project_root, timeout=30)
            self.assertEqual(run.returncode, 0, f"sample crashed: {run.stderr[:1000]}")
            golden = os.path.join(
                REPO,
                "src",
                "tests",
                "classes",
                "expected",
                "InheritedOperatorOverload.stdout",
            )
            with open(golden) as expected:
                self.assertEqual(run.stdout, expected.read(), "self-built compiler output != golden")


if __name__ == "__main__":
    unittest.main()
