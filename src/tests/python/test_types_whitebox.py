"""White-box tests for the pure type-mapping helpers in ir/gen/types.py."""

from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.types import (
    element_type_c,
    format_spec_for_type,
    is_numeric_type,
    is_pointer_type,
    is_string_type,
    mangle_tuple_type,
    type_to_c,
)


def T(base, **kw):
    return TypeExpr(
        base=base,
        generic_args=kw.get("generic_args", []),
        pointer_depth=kw.get("pointer_depth", 0),
        is_const=kw.get("is_const", False),
    )


def test_type_to_c_none_and_primitives():
    assert type_to_c(None) == "void"
    assert type_to_c(T("int")) == "int"
    assert type_to_c(T("string")) == "char*"


def test_type_to_c_thread_mutex_handles():
    assert type_to_c(T("Thread", generic_args=[T("int")])) == "__btrc_thread_t*"
    assert type_to_c(T("Mutex", generic_args=[T("int")])) == "__btrc_mutex_val_t*"


def test_type_to_c_const_qualifier():
    assert type_to_c(T("int", is_const=True)).startswith("const ")


def test_mangle_tuple_type():
    assert mangle_tuple_type(T("Tuple", generic_args=[T("int"), T("string")])) == "btrc_Tuple_int_string"
    assert mangle_tuple_type(T("Tuple")) == "btrc_Tuple"


def test_is_pointer_type():
    assert is_pointer_type(None) is False
    assert is_pointer_type(T("int", pointer_depth=1)) is True
    assert is_pointer_type(T("string")) is True  # string is char*
    assert is_pointer_type(T("int")) is False
    assert is_pointer_type(T("MyClass")) is True  # user classes are heap pointers


def test_is_string_and_numeric():
    assert is_string_type(T("string")) is True
    assert is_string_type(T("int")) is False
    assert is_string_type(None) is False
    assert is_numeric_type(T("double")) is True
    assert is_numeric_type(T("string")) is False
    assert is_numeric_type(None) is False


def test_element_type_c():
    assert element_type_c(T("List", generic_args=[T("int")])) == "int"
    assert element_type_c(T("List")) == "void*"


def test_format_spec_for_type_all_branches():
    assert format_spec_for_type(None) == "%d"
    assert format_spec_for_type(T("int", pointer_depth=1)) == "%p"
    assert format_spec_for_type(T("int")) == "%d"
    assert format_spec_for_type(T("long")) == "%ld"
    assert format_spec_for_type(T("double")) == "%f"
    assert format_spec_for_type(T("char")) == "%c"
    assert format_spec_for_type(T("string")) == "%s"
    assert format_spec_for_type(T("bool")) == "%s"
    assert format_spec_for_type(T("UnknownClass")) == "%d"  # default
