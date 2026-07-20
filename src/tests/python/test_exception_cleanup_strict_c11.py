"""Strict-C execution checks for generated exception cleanup slots."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _strict_build_and_run(
    generated: str,
    tmp_path: Path,
    c_compiler: str,
    optimization: str,
    name: str,
) -> None:
    source = tmp_path / f"{name}.c"
    binary = tmp_path / name
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
    _strict_build_and_run(generated, tmp_path, c_compiler, optimization, "generated_cleanup")


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    ("name", "source"),
    (
        (
            "ordinary_finally_return",
            """
            int cleaned = 0;
            int run() {
                try { return 7; }
                finally { cleaned++; }
            }
            int main() { return run() == 7 && cleaned == 0 ? 0 : 1; }
            """,
        ),
        (
            "generic_finally_return",
            """
            int cleaned = 0;
            class Box<T> {
                public T value;
                public Box(T value) { self.value = value; }
                public int run() {
                    try { return 7; }
                    finally { cleaned++; }
                }
            }
            int main() {
                Box<int> box = new Box<int>(1);
                return box.run() == 7 && cleaned == 0 ? 0 : 1;
            }
            """,
        ),
    ),
)
def test_terminal_finally_paths_are_strict_c11(
    tmp_path: Path,
    c_compiler: str,
    name: str,
    source: str,
) -> None:
    generated = emit_c(source)
    assert "__btrc_finally_pending" not in generated
    _strict_build_and_run(generated, tmp_path, c_compiler, "-O0", name)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_finally_keeps_one_static_storage_object(tmp_path: Path, c_compiler: str) -> None:
    generated = emit_c("""
        int run(bool fail) {
            try {
                if (fail) { throw "boom"; }
            } finally {
                static int calls = 0;
                calls++;
                return calls;
            }
        }
        int main() {
            if (run(false) != 1) { return 1; }
            return run(true) == 2 ? 0 : 2;
        }
    """)
    assert generated.count("static int calls = 0;") == 1
    _strict_build_and_run(generated, tmp_path, c_compiler, "-O0", "finally_static_storage")
