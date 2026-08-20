"""Focused contracts for owned type rendering and type identity policy."""

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.syntax.ast.generated import Program, TypeExpr

IDENTITY = TypeIdentity()


def T(base, **kw):
    return TypeExpr(
        base=base,
        generic_args=kw.get("generic_args", []),
        pointer_depth=kw.get("pointer_depth", 0),
        is_const=kw.get("is_const", False),
    )


def _renderer() -> CTypeLowerer:
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
    )
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    return CTypeLowerer(session, analyzed, IDENTITY)


def test_type_renderer_none_and_primitives():
    renderer = _renderer()

    assert renderer.render(None) == "void"
    assert renderer.render(T("int")) == "int"
    assert renderer.render(T("string")) == "char*"


def test_type_renderer_thread_mutex_handles():
    renderer = _renderer()

    assert renderer.render(T("Thread", generic_args=[T("int")])) == "__btrc_thread_t*"
    assert renderer.render(T("Mutex", generic_args=[T("int")])) == "__btrc_mutex_val_t*"


def test_type_renderer_const_qualifier():
    assert _renderer().render(T("int", is_const=True)).startswith("const ")


def test_mangle_tuple_type():
    assert IDENTITY.generic_symbol("Tuple", [T("int"), T("string")]) == "btrc_Tuple_int_string"
    assert IDENTITY.generic_symbol("Tuple", []) == "btrc_Tuple"


def test_reference_policy_uses_semantic_type_identity():
    classes = {"MyClass": object()}

    assert IDENTITY.is_reference(None, classes) is False
    assert IDENTITY.is_reference(T("int", pointer_depth=1), classes) is True
    assert IDENTITY.is_reference(T("string"), classes) is True
    assert IDENTITY.is_reference(T("int"), classes) is False
    assert IDENTITY.is_reference(T("MyClass"), classes) is True


def test_is_string_and_numeric():
    assert IDENTITY.is_scalar_string(T("string")) is True
    assert IDENTITY.is_scalar_string(T("int")) is False
    assert IDENTITY.is_scalar_string(None) is False
    assert CTypeLowerer.is_numeric_type(T("double")) is True
    assert CTypeLowerer.is_numeric_type(T("string")) is False
    assert CTypeLowerer.is_numeric_type(None) is False


def test_type_renderer_collection_element():
    renderer = _renderer()

    assert renderer.element_type(T("List", generic_args=[T("int")])) == "int"
    assert renderer.element_type(T("List")) == "void*"


def test_type_renderer_format_spec_all_branches():
    renderer = _renderer()

    assert renderer.format_spec(None) == "%d"
    assert renderer.format_spec(T("int", pointer_depth=1)) == "%p"
    assert renderer.format_spec(T("int")) == "%d"
    assert renderer.format_spec(T("long")) == "%ld"
    assert renderer.format_spec(T("double")) == "%f"
    assert renderer.format_spec(T("char")) == "%c"
    assert renderer.format_spec(T("string")) == "%s"
    assert renderer.format_spec(T("bool")) == "%s"
    assert renderer.format_spec(T("UnknownClass")) == "%d"  # default
