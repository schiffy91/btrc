"""Structural and context-isolation contracts for managed-value owners."""

from __future__ import annotations

import ast
from pathlib import Path

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.ir.gen.generics.user_emitter import (
    _UserGenericEmitter,
)
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.gen.managed_local import ManagedLocal
from src.compiler.python.ir.nodes import CType, IRLiteral, IRVarDecl
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

_OWNER_DIRECTORY = Path(__file__).parents[2] / "compiler" / "python" / "ir" / "gen"
_OWNER_MODULES = (
    "arc.py",
    "cleanup_slots.py",
    "cycle_metadata.py",
    "generics/user_emitter.py",
    "managed_local.py",
    "managed_values.py",
    "ownership_lifetime.py",
)
_DELETED_BEHAVIOR_MODULES = (
    "arc_cycles.py",
    "arc_ops.py",
    "arc_type_names.py",
    "cleanup_registration.py",
    "cycle_type_resolution.py",
    "edge_arc.py",
    "generics/user_emitter_boundary.py",
    "generics/user_emitter_cleanup.py",
    "managed_type_classifier.py",
    "polymorphic_cycles.py",
    "temporary_cleanup.py",
)


def _lowerer() -> IRLowerer:
    source = """
        class Item {}
        class Box<T> { public T value; }
        int main() {
            Box<Item> value = new Box<Item>();
            return 0;
        }
    """
    program = Parser(Lexer(source, "<owners>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors, analyzed.errors
    return IRLowerer(analyzed)


def test_managed_owner_modules_have_no_module_level_behavior():
    for module_name in _OWNER_MODULES:
        tree = ast.parse(
            (_OWNER_DIRECTORY / module_name).read_text(),
            filename=module_name,
        )
        functions = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert not functions, f"{module_name} has unowned module behavior: {functions}"


def test_managed_owners_do_not_hide_static_or_class_namespaces():
    for module_name in _OWNER_MODULES:
        tree = ast.parse(
            (_OWNER_DIRECTORY / module_name).read_text(),
            filename=module_name,
        )
        forbidden = []
        for owner in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            for method in (node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))):
                decorators = {decorator.id for decorator in method.decorator_list if isinstance(decorator, ast.Name)}
                if decorators & {"staticmethod", "classmethod"}:
                    forbidden.append(f"{owner.name}.{method.name}")
        assert not forbidden, f"{module_name} has pseudo-namespace methods: {forbidden}"


def test_obsolete_managed_behavior_modules_are_deleted():
    assert not [module_name for module_name in _DELETED_BEHAVIOR_MODULES if (_OWNER_DIRECTORY / module_name).exists()]


def test_generic_lifetime_binding_isolates_cleanup_declarations():
    lowerer = _lowerer()
    assert all(retained is not lowerer for retained in vars(lowerer.managed_releases).values())
    item_type = TypeExpr(base="Item")
    emitter = _UserGenericEmitter(
        {"T": item_type},
        lowerer.type_identity.specialization_symbol(
            "Box",
            [item_type],
        ),
        lowerer.type_renderer,
        gen=lowerer,
        cls_info=lowerer.analyzed.class_table["Box"],
    )
    lifetime = emitter._boundary_lifetime

    assert lifetime is not lowerer.lifetime
    assert lifetime.context is emitter.context
    assert lifetime.cleanup_scope is emitter
    assert lifetime.values is lowerer.managed_values
    assert lifetime.cycles is lowerer.cycles
    assert lifetime.cleanup_slots is lowerer.cleanup_slots
    assert lifetime.helpers is lowerer.helpers

    root_declarations = lowerer.context.function_declarations
    root_before = tuple(root_declarations)
    marker = "__generic_cleanup_scope"
    emitter._cleanup_scope_markers.append(marker)
    emitter._try_depth = 1
    slot = IRVarDecl(
        c_type=CType(text="struct Item*"),
        name="generic_value",
        init=IRLiteral(text="NULL"),
    )
    emitter._func_var_decls.append(slot)

    cleanup_declarations, cleanup_expressions = lifetime.cleanup_registration(
        slot,
        item_type,
        "__generic_cleanup_flag",
    )
    release_statements = lifetime.release_scope([ManagedLocal("generic_value", "Item", False)])

    assert cleanup_declarations
    assert cleanup_expressions
    assert release_statements
    assert marker in emitter._active_cleanup_markers
    assert all(declaration in emitter.context.function_declarations for declaration in cleanup_declarations)
    assert tuple(root_declarations) == root_before
