"""Concrete tuple declarations discovered through generic specialization views."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

_INTERNAL_GENERIC_TUPLE_SOURCES = (
    pytest.param(
        """
        class Box<T> {
            public Box() {}
            public int unpack(T value) {
                (T, int) pair = (value, 7);
                return pair._1;
            }
        }

        int main() {
            Box<int> box = new Box<int>();
            return box.unpack(3) == 7 ? 0 : 1;
        }
        """,
        id="generic-class-body",
    ),
    pytest.param(
        """
        class Maker {
            public Maker() {}
            public int unpack<T>(T value) {
                (T, int) pair = (value, 9);
                return pair._1;
            }
        }

        int main() {
            Maker maker = new Maker();
            return maker.unpack(3) == 9 ? 0 : 1;
        }
        """,
        id="generic-method-body",
    ),
)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("source", _INTERNAL_GENERIC_TUPLE_SOURCES)
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_internal_generic_tuple_shapes_are_declared_before_specialized_bodies(
    tmp_path: Path,
    source: str,
    c_compiler: str,
) -> None:
    c_source = emit_c(source)

    assert c_source.count("struct btrc_Tuple_int_int {") == 1
    assert "btrc_Tuple_T_int" not in c_source

    generated = tmp_path / "generic_tuple.c"
    binary = tmp_path / "generic_tuple"
    generated.write_text(c_source)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1",
            str(generated),
            "-lm",
            "-pthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    subprocess.run(
        [binary],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


__all__ = []
