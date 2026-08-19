"""Behavioral contracts for translation-unit type rendering."""

from __future__ import annotations

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.ir.lowering.session import LoweringSession
from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.syntax.ast.generated import Program, TypeExpr


def _renderer() -> CTypeLowerer:
    analyzed = AnalyzedProgram(
        program=Program(),
        generic_instances={},
        class_table={},
    )
    session = LoweringSession(module=IRModule(), node_types=analyzed.node_types)
    return CTypeLowerer(session, analyzed)


def test_nested_callback_typedefs_are_emitted_dependency_first_and_once() -> None:
    renderer = _renderer()
    inner = TypeExpr(
        base="__fn_ptr",
        generic_args=[TypeExpr(base="int"), TypeExpr(base="string")],
    )
    outer = TypeExpr(
        base="__fn_ptr",
        generic_args=[inner, inner, TypeExpr(base="bool")],
    )

    outer_name = renderer.render(outer)
    declarations = renderer.consume_function_pointer_typedefs()

    assert len(declarations) == 2
    inner_declaration, outer_declaration = declarations
    assert outer_declaration.name == outer_name
    assert outer_declaration.return_type.text == inner_declaration.name
    assert [item.text for item in outer_declaration.param_types] == [
        inner_declaration.name,
        "bool",
    ]
    assert renderer.consume_function_pointer_typedefs() == []
