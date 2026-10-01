"""Regenerate the corpus goldens through the corpus runner's own build path.

Each runnable ``.btrc`` corpus program is transpiled by the Python reference
compiler, compiled with the runner's C compiler and flags (``BTRC_CC``,
``BTRC_CFLAGS``, and the GPU runtime flags), and run under the runner's time
limit. A golden is written only for a program that exits 0 and prints PASS:
``expected/<Stem>.stdout`` always, and ``expected/<Stem>.stderr`` when the
program wrote to stderr (a stale ``.stderr`` golden is removed when it did
not). A case the runner would skip is reported and left alone; any failure
leaves its goldens untouched and makes the command exit 1.

Pass corpus-relative paths (``basics/Hello.btrc``) to regenerate only those.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from src.tests import runner


class GoldenGenerator:
    """Writes the goldens for corpus programs that pass under the runner's build."""

    def __init__(self, corpus: str = runner.BTRC_TEST_DIR) -> None:
        self.corpus = os.path.abspath(corpus)

    def generate(self, selected: list[str]) -> int:
        cases = selected or runner.get_btrc_test_files()
        written = skipped = failed = 0
        for relative in cases:
            try:
                self.generate_one(relative)
            except pytest.skip.Exception as skip:
                print(f"  SKIP {relative}: {skip.msg}")
                skipped += 1
            except Exception as error:
                print(f"  FAIL {relative}: {error}")
                failed += 1
            else:
                print(f"  OK   {relative}")
                written += 1
        print(f"\nGenerated {written} golden files ({skipped} skipped, {failed} failed)")
        return 1 if failed else 0

    def generate_one(self, relative: str) -> None:
        btrc_path = os.path.join(self.corpus, relative)
        c_source = runner._transpile_python(btrc_path, relative)
        with tempfile.TemporaryDirectory(prefix="btrc-golden-") as directory:
            c_path = os.path.join(directory, "program.c")
            binary = os.path.join(directory, "program")
            with open(c_path, "w") as c_file:
                c_file.write(c_source)
            built = subprocess.run(
                runner._gcc_flags(c_source, c_path, binary),
                capture_output=True,
                text=True,
                timeout=runner.C_COMPILE_TIMEOUT,
            )
            if built.returncode != 0:
                raise RuntimeError(f"C compile failed:\n{built.stderr[:2000]}")
            runner._require_test_capabilities(btrc_path)
            ran = subprocess.run([binary], capture_output=True, text=True, timeout=runner.BTRC_RUN_TIMEOUT)
        if ran.returncode != 0:
            raise RuntimeError(f"program exited with {ran.returncode}:\n{ran.stderr[:2000]}")
        if "PASS" not in ran.stdout:
            raise RuntimeError("program did not print PASS")
        expected = os.path.join(os.path.dirname(btrc_path), "expected")
        stem = os.path.join(expected, os.path.basename(relative).removesuffix(".btrc"))
        os.makedirs(expected, exist_ok=True)
        with open(stem + ".stdout", "w") as golden:
            golden.write(ran.stdout)
        if ran.stderr:
            with open(stem + ".stderr", "w") as golden:
                golden.write(ran.stderr)
        elif os.path.exists(stem + ".stderr"):
            os.unlink(stem + ".stderr")


if __name__ == "__main__":
    sys.exit(GoldenGenerator().generate(sys.argv[1:]))
