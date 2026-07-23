"""Structural and behavioral contracts for translation-unit type rendering."""

from __future__ import annotations

import ast
from pathlib import Path

from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.types import CTypeRenderer

IR_GEN = Path(__file__).parents[2] / "compiler" / "python" / "ir" / "gen"
LEGACY_NAMES = {
    "_fn_ptr_typedefs",
    "_typedef_types",
    "element_type_c",
    "fn_ptr_typedef_name",
    "fn_ptr_typedef_scope",
    "format_spec_for_type",
    "get_fn_ptr_typedefs",
    "reset_fn_ptr_typedefs",
    "type_render_scope",
    "type_to_c",
    "typedef_base_is_reference",
}


def test_type_rendering_has_no_ambient_state_or_legacy_api() -> None:
    assert not (IR_GEN / "type_render_context.py").exists()
    assert "ContextVar" not in (IR_GEN / "types.py").read_text()

    violations = []
    for path in IR_GEN.rglob("*.py"):
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in LEGACY_NAMES:
                violations.append(f"{path.name}:{node.lineno}: {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in LEGACY_NAMES:
                violations.append(f"{path.name}:{node.lineno}: {node.attr}")

    assert violations == []


def test_ir_lowerer_constructs_one_renderer_without_generator_reach_through() -> None:
    lowerer_path = IR_GEN / "lowerer.py"
    lowerer_tree = ast.parse(lowerer_path.read_text())
    constructions = [
        node
        for node in ast.walk(lowerer_tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "CTypeRenderer"
    ]
    assert len(constructions) == 1

    reach_through = []
    for path in IR_GEN.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or node.attr != "type_renderer":
                continue
            if isinstance(node.value, ast.Name) and node.value.id in {
                "gen",
                "lowerer",
            }:
                reach_through.append(f"{path.name}:{node.lineno}")

    assert reach_through == []


def test_nested_callback_typedefs_are_emitted_dependency_first_and_once() -> None:
    renderer = CTypeRenderer()
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
