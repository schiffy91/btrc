"""Concrete tuple declarations discovered through generic specialization views."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from src.tests.c_toolchains import HOST_C_COMPILERS, requires_host_c_compiler
from src.tests.python.reference_pipeline import emit_c


def test_tuple_declarations_do_not_depend_on_body_discovery_order() -> None:
    first = "(int, (short, char)) outer = (7, ((short)2, 'q'));"
    second = "(char, int) earlier = ('a', 4);"
    declarations = []
    for statements in ((first, second), (second, first)):
        source = "int main() { " + " ".join(statements) + " return outer._0 + earlier._1; }"
        generated = emit_c(source)
        shapes = re.findall(r"^struct (btrc_\w+) \{\n.*?^\};", generated, re.MULTILINE | re.DOTALL)
        assert len(shapes) == 3, shapes
        inner = next(shape for shape in shapes if shape == "btrc_Tuple_short_char")
        outer = next(shape for shape in shapes if shape not in {"btrc_Tuple_short_char", "btrc_Tuple_char_int"})
        assert shapes.index(inner) < shapes.index(outer), shapes
        declarations.append(shapes)
    assert declarations[0] == declarations[1]


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


@requires_host_c_compiler
@pytest.mark.parametrize("source", _INTERNAL_GENERIC_TUPLE_SOURCES)
@pytest.mark.parametrize("c_compiler", HOST_C_COMPILERS, ids=lambda path: Path(path).name)
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
