"""Strict-C execution checks for generated exception cleanup slots."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("optimization", ("-O0", "-O2", "-O3"))
def test_generated_cleanup_slots_survive_strict_optimized_longjmp(
    tmp_path: Path,
    c_compiler: str,
    optimization: str,
):
    generated = emit_c("""
        class Item {
            public int value;
            public Item(int value) { self.value = value; }
        }
        int read(keep Item item) { return item.value; }
        int main() {
            int observed = 0;
            try {
                observed = read(new Item(7));
                throw "boom";
            } catch (string message) {
                if (!message.equals("boom")) { return 2; }
            }
            return observed == 7 ? 0 : 3;
        }
    """)
    source = tmp_path / "generated_cleanup.c"
    binary = tmp_path / "generated_cleanup"
    source.write_text(generated)
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            optimization,
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr
