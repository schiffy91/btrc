"""White-box tests for owned type rendering and stateless type policies."""

from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.types import (
    CTypeRenderer,
    is_numeric_type,
    is_pointer_type,
    is_string_type,
    mangle_tuple_type,
)


def T(base, **kw):
    return TypeExpr(
        base=base,
        generic_args=kw.get("generic_args", []),
        pointer_depth=kw.get("pointer_depth", 0),
        is_const=kw.get("is_const", False),
    )


def test_type_renderer_none_and_primitives():
    renderer = CTypeRenderer()

    assert renderer.render(None) == "void"
    assert renderer.render(T("int")) == "int"
    assert renderer.render(T("string")) == "char*"


def test_type_renderer_thread_mutex_handles():
    renderer = CTypeRenderer()

    assert renderer.render(T("Thread", generic_args=[T("int")])) == "__btrc_thread_t*"
    assert renderer.render(T("Mutex", generic_args=[T("int")])) == "__btrc_mutex_val_t*"


def test_type_renderer_const_qualifier():
    assert CTypeRenderer().render(T("int", is_const=True)).startswith("const ")


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


def test_type_renderer_collection_element():
    renderer = CTypeRenderer()

    assert renderer.element_type(T("List", generic_args=[T("int")])) == "int"
    assert renderer.element_type(T("List")) == "void*"


def test_type_renderer_format_spec_all_branches():
    renderer = CTypeRenderer()

    assert renderer.format_spec(None) == "%d"
    assert renderer.format_spec(T("int", pointer_depth=1)) == "%p"
    assert renderer.format_spec(T("int")) == "%d"
    assert renderer.format_spec(T("long")) == "%ld"
    assert renderer.format_spec(T("double")) == "%f"
    assert renderer.format_spec(T("char")) == "%c"
    assert renderer.format_spec(T("string")) == "%s"
    assert renderer.format_spec(T("bool")) == "%s"
    assert renderer.format_spec(T("UnknownClass")) == "%d"  # default
