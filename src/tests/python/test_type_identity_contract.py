"""Canonical generic type identity, diagnostics, and strict runtime contracts."""

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.errors import CodegenError
from src.compiler.python.ir.gen.generics.core import _resolve_type
from src.compiler.python.ir.gen.generics.methods_mono import (
    generic_method_instance_name,
)
from src.compiler.python.ir.gen.types import (
    fn_ptr_typedef_name,
    is_string_type,
    mangle_generic_type,
    mangle_tuple_type,
    mangle_type_name,
    reset_fn_ptr_typedefs,
)
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.type_identity import (
    TypeShapeError,
    type_shape_key,
)
from src.tests.python.test_codegen import emit_c


def _type(base: str, **kwargs) -> TypeExpr:
    return TypeExpr(base=base, **kwargs)


def _analyze(source: str):
    program = Parser(Lexer(source, "<type-identity>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def test_shape_key_distinguishes_recursive_pointer_nullable_and_array_shape():
    scalar = _type("int")
    pointer = _type("int", pointer_depth=1)
    nullable = _type("int", pointer_depth=1, is_nullable=True)
    array = _type("int", is_array=True)
    nested = _type("Box", generic_args=[array])

    keys = {type_shape_key(item) for item in (scalar, pointer, nullable, array, nested)}

    assert len(keys) == 5
    assert type_shape_key(_type("Box", generic_args=[scalar])) != type_shape_key(nested)


def test_safe_legacy_symbols_and_simple_shape_suffixes_are_stable():
    assert mangle_generic_type("Vector", [_type("int")]) == "btrc_Vector_int"
    assert mangle_generic_type("Map", [_type("string"), _type("int")]) == "btrc_Map_string_int"
    assert mangle_generic_type("Vector", [_type("int", is_array=True)]) == "btrc_Vector_int_a"
    assert mangle_generic_type("Vector", [_type("int", pointer_depth=1, is_array=True)]) == "btrc_Vector_int_p1_a"
    assert (
        mangle_generic_type(
            "Vector",
            [_type("int", pointer_depth=1, is_nullable=True, is_array=True)],
        )
        == "btrc_Vector_int_p1_n_a"
    )


def test_reserved_encoding_separates_nested_underscore_and_ambiguous_shapes():
    nested = _type(
        "A",
        generic_args=[_type("int")],
        pointer_depth=1,
    )
    legacy_collision = _type("A_int_p1")
    assert mangle_type_name(nested).startswith("ZQt")
    assert mangle_generic_type("Holder", [nested]) != mangle_generic_type("Holder", [legacy_collision])

    assert mangle_generic_type("Holder_A", [_type("int")]) != (mangle_generic_type("Holder", [_type("A_int")]))
    ambiguous_left = [
        _type("int", pointer_depth=1),
        _type("a"),
    ]
    ambiguous_right = [
        _type("int"),
        _type("p1", is_array=True),
    ]
    left = mangle_generic_type("Pair", ambiguous_left)
    right = mangle_generic_type("Pair", ambiguous_right)
    assert left.startswith("btrc_ZQg")
    assert right.startswith("btrc_ZQg")
    assert left != right


def test_multiword_c_bases_use_injective_identifier_safe_components():
    multiword = mangle_type_name(_type("unsigned int"))
    underscored = mangle_type_name(_type("unsigned_int"))

    assert multiword == "ZQtb24_756e7369676e656420696e74p0n0o0a0q0k0"
    assert underscored == "ZQtb24_756e7369676e65645f696e74p0n0o0a0q0k0"
    assert multiword != underscored
    assert " " not in multiword


def test_declared_one_letter_class_does_not_capture_shadowed_type_parameter():
    source = """
        class T {}
        class Inner<U> { public U value; }
        class Outer<T> { public Inner<T> child; }
        int main() { Outer<int> value; return 0; }
    """
    result = _analyze(source)

    assert result.errors == []
    assert [args[0].base for args in result.generic_instances["Inner"]] == ["int"]
    assert all(args[0].base != "T" for args in result.generic_instances["Inner"])
    assert [args[0].base for args in result.generic_instances["Outer"]] == ["int"]
    c_source = emit_c(source)
    assert "btrc_Inner_int" in c_source
    assert "btrc_Inner_T" not in c_source


def test_nullable_and_explicit_pointer_method_instances_do_not_collide():
    pointer = _type("int", pointer_depth=1)
    nullable = _type("int", pointer_depth=1, is_nullable=True)

    assert mangle_type_name(pointer) == "int_p1"
    assert mangle_type_name(nullable) == "int_p1_n"
    assert generic_method_instance_name("Picker", (), "identity", (pointer,)) == "Picker_identity_int_p1"
    assert generic_method_instance_name("Picker", (), "identity", (nullable,)) == "Picker_identity_int_p1_n"


def test_string_classification_accepts_only_collapsed_scalar_strings():
    assert is_string_type(_type("string"))
    assert is_string_type(_type("string", pointer_depth=1, is_nullable=True))
    assert not is_string_type(_type("string", is_array=True))
    assert not is_string_type(_type("string", pointer_depth=1))
    assert not is_string_type(_type("string", pointer_depth=2, is_nullable=True))


def test_nested_array_composition_is_analyzer_error_and_codegen_guard():
    result = _analyze("""
        class Buffer<T> { public T[] data; }
        void run() { Buffer<int[]> invalid; }
    """)

    assert any("nested array composition" in error.lower() for error in result.errors)
    with pytest.raises(CodegenError, match="nested array composition"):
        _resolve_type(
            _type("T", is_array=True),
            {"T": _type("int", is_array=True)},
        )


@pytest.mark.parametrize("qualifier", ("const", "static", "extern", "volatile"))
def test_qualified_class_generic_arguments_are_rejected(qualifier: str):
    result = _analyze(f"""
        class Box<T> {{ public Box() {{}} }}
        void run() {{ Box<{qualifier} int> invalid; }}
    """)

    assert any(f"cannot be {qualifier}-qualified" in error.lower() for error in result.errors)
    with pytest.raises(TypeShapeError, match=f"{qualifier}-qualified"):
        mangle_generic_type("Box", [_type("int", **{f"is_{qualifier}": True})])


def test_qualified_method_generic_argument_is_rejected():
    result = _analyze("""
        class Picker {
            public U identity<U>(U value) { return value; }
        }
        void run() {
            Picker picker = Picker();
            const int value = 7;
            picker.identity(value);
        }
    """)

    assert any("cannot be const-qualified" in error.lower() for error in result.errors)


def test_qualified_nested_class_specialization_is_rejected():
    result = _analyze("""
        class Box<T> { public T value; }
        class Envelope<T> { public Box<const T> value; }
        void run() { Envelope<int> invalid; }
    """)

    assert any("cannot be const-qualified" in error.lower() for error in result.errors)


def test_qualified_structural_type_arguments_remain_supported():
    qualified = _type("int", is_const=True)
    fn_ptr = _type(
        "__fn_ptr",
        generic_args=[_type("void"), qualified],
    )
    tuple_type = _type(
        "Tuple",
        generic_args=[qualified, _type("int")],
    )

    result = _analyze("""
        void consume(__fn_ptr<void, const int> callback,
                     Tuple<const int, int> values) {}
    """)

    assert result.errors == []
    assert result.generic_instances == {}
    assert fn_ptr_typedef_name(fn_ptr).startswith("__btrc_fn_ZQf")
    assert mangle_tuple_type(tuple_type).startswith("btrc_ZQg")
    reset_fn_ptr_typedefs()
