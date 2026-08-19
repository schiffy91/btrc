"""Generic substitution must retain complete array and qualifier metadata."""

import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.syntax.ast.generated import IntLiteral, Program, TypeExpr
from src.compiler.python.ir.lowering.generics import TypeSubstitution
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.analyzer.types import TypeIdentity
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
IDENTITY = TypeIdentity()


def _resolve(
    type_expr: TypeExpr,
    arguments: dict[str, TypeExpr],
    typedefs: dict[str, TypeExpr] | None = None,
) -> TypeExpr:
    resolved = TypeSubstitution(
        arguments=arguments,
        typedefs=typedefs or {},
        identity=IDENTITY,
    ).resolve(type_expr)
    assert resolved is not None
    return resolved


def _renderer() -> CTypeLowerer:
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
    )
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    return CTypeLowerer(session, analyzed, IDENTITY)


def test_nullable_parameter_substitution_merges_metadata_without_stacking_reference_layers():
    use_size = IntLiteral(value=4, raw="4")
    placeholder = TypeExpr(
        base="T",
        pointer_depth=1,
        is_array=True,
        array_size=use_size,
        is_const=True,
        is_nullable=True,
        is_static=True,
        line=7,
        col=11,
    )
    mapped = TypeExpr(
        base="Item",
        generic_args=[TypeExpr(base="int")],
        pointer_depth=2,
        is_extern=True,
        is_volatile=True,
        line=2,
        col=3,
    )

    result = _resolve(placeholder, {"T": mapped})

    assert result.base == "Item"
    assert [argument.base for argument in result.generic_args] == ["int"]
    # ``T?`` carries a provisional pointer layer until T is known.  Item** is
    # already reference-shaped, so nullable annotates that value rather than
    # turning the array element into Item***.
    assert result.pointer_depth == 2
    assert result.is_array is True
    assert result.array_size is use_size
    assert result.is_const is True
    assert result.is_nullable is True
    assert result.is_static is True
    assert result.is_extern is True
    assert result.is_volatile is True
    assert (result.line, result.col) == (7, 11)


def test_substitution_falls_back_to_mapped_bounds_and_preserves_owner_metadata():
    mapped_size = IntLiteral(value=8, raw="8")
    mapped = TypeExpr(
        base="int",
        is_array=True,
        array_size=mapped_size,
        is_volatile=True,
    )
    owner = TypeExpr(
        base="Box",
        generic_args=[TypeExpr(base="T")],
        pointer_depth=1,
        is_array=True,
        is_const=True,
        is_nullable=True,
        is_static=True,
        is_extern=True,
        line=13,
        col=17,
    )

    direct = _resolve(TypeExpr(base="T"), {"T": mapped})
    nested = _resolve(owner, {"T": TypeExpr(base="string")})

    assert direct.is_array is True
    assert direct.array_size is mapped_size
    assert direct.is_volatile is True
    assert nested.generic_args == [TypeExpr(base="string")]
    assert nested.pointer_depth == 1
    assert nested.is_array is True
    assert nested.is_const is True
    assert nested.is_nullable is True
    assert nested.is_static is True
    assert nested.is_extern is True
    assert (nested.line, nested.col) == (13, 17)


@pytest.mark.parametrize(
    ("mapped", "storage_c", "element_c"),
    [
        (TypeExpr(base="string"), "char**", "char*"),
        (TypeExpr(base="int"), "int*", "int"),
        (TypeExpr(base="Item", pointer_depth=1), "Item**", "Item*"),
    ],
)
def test_generic_array_layout_retains_the_mapped_element_type(
    mapped: TypeExpr,
    storage_c: str,
    element_c: str,
):
    storage = _resolve(
        TypeExpr(base="T", is_array=True),
        {"T": mapped},
    )
    element = replace(storage, is_array=False, array_size=None)

    renderer = _renderer()
    assert renderer.render(storage) == storage_c
    assert renderer.render(element) == element_c


@pytest.mark.skipif(
    not COMPILERS or sys.platform == "win32",
    reason="requires a hosted C11 compiler",
)
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_generic_string_and_scalar_arrays_compile_and_run_under_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    c_source = emit_c("""
        class Slice<T> {
            public T[] data;
            public Slice(T[] values) { self.data = values; }
            public T at(int index) { return self.data[index]; }
        }

        int main() {
            string words[2] = {"first", "second"};
            int values[3] = {3, 5, 8};
            Slice<string> strings = new Slice<string>(words);
            Slice<int> integers = new Slice<int>(values);
            if (strings.at(1) != "second") { return 1; }
            if (integers.at(2) != 8) { return 2; }
            return 0;
        }
    """)
    string_struct = c_source.split("struct btrc_Slice_string {", 1)[1].split(
        "};",
        1,
    )[0]
    integer_struct = c_source.split("struct btrc_Slice_int {", 1)[1].split(
        "};",
        1,
    )[0]
    assert "char** data;" in string_struct
    assert "int* data;" in integer_struct
    assert "static char* btrc_Slice_string_at(" in c_source
    assert "static int btrc_Slice_int_at(" in c_source

    source = tmp_path / "generic_arrays.c"
    binary = tmp_path / "generic_arrays"
    source.write_text(c_source)

    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1",
            str(source),
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
