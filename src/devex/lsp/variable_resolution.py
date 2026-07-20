"""Variable type inference for semantic and degraded LSP snapshots."""

from __future__ import annotations

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    CallExpr,
    ClassDecl,
    ElseBlock,
    ElseIf,
    FunctionDecl,
    Identifier,
    MethodDecl,
    NewExpr,
    Param,
    VarDeclStmt,
)
from src.devex.lsp.builtins import _MEMBER_TABLES
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.scope_utils import decl_list

_PRIMITIVE_TYPES = frozenset({"int", "float", "double", "long", "short", "char", "bool", "void", "unsigned"})
BUILTIN_TYPES = _PRIMITIVE_TYPES | frozenset(_MEMBER_TABLES)


def resolve_variable_type(
    name: str,
    ast: object,
    class_table: dict[str, ClassInfo],
    cursor_line: int | None = None,
    result: AnalysisResult | None = None,
    cursor_col: int | None = None,
) -> str | None:
    """Resolve a variable's base type at an optional source position."""
    if result is not None and cursor_line is not None:
        from src.devex.lsp.definition import DefinitionMap  # lazy: avoid cycle

        dmap = DefinitionMap.from_result(result)
        definition = dmap.find_var_def(
            name,
            cursor_line,
            cursor_col if cursor_col is not None else 10**9,
        )
        if definition is not None:
            return _vardef_type_name(definition, class_table)
        for decl in decl_list(ast):
            if isinstance(decl, VarDeclStmt) and decl.name == name:
                type_name = _var_decl_type(decl, class_table)
                if type_name:
                    return type_name
        return None

    candidates: list[tuple[int, str]] = []
    for decl in decl_list(ast):
        _scan_for_var_types(name, decl, class_table, candidates)
    if cursor_line is not None:
        candidates = [candidate for candidate in candidates if candidate[0] <= cursor_line]
    return max(candidates, default=(0, None), key=lambda candidate: candidate[0])[1]


def _vardef_type_name(definition, class_table: dict[str, ClassInfo]) -> str | None:
    node = definition.node
    if isinstance(node, VarDeclStmt):
        return _var_decl_type(node, class_table)
    if isinstance(node, Param):
        if node.type and _known_type(node.type.base, class_table):
            return node.type.base
        return None
    if definition.kind == "catch":
        return "string"
    return None


def _known_type(type_name: str, class_table: dict[str, ClassInfo]) -> bool:
    return type_name in class_table or type_name in BUILTIN_TYPES


def _scan_for_var_types(
    var_name: str,
    node,
    class_table: dict[str, ClassInfo],
    candidates: list[tuple[int, str]],
) -> None:
    if isinstance(node, VarDeclStmt):
        if node.name == var_name:
            type_name = _var_decl_type(node, class_table)
            if type_name:
                candidates.append((node.line, type_name))
        return

    if isinstance(node, ClassDecl):
        for member in node.members:
            _scan_for_var_types(var_name, member, class_table, candidates)
        return
    if isinstance(node, (FunctionDecl, MethodDecl)):
        for param in node.params:
            if param.name == var_name and param.type and _known_type(param.type.base, class_table):
                candidates.append((param.line, param.type.base))
        if node.body:
            for statement in node.body.statements:
                _scan_for_var_types(var_name, statement, class_table, candidates)
        return

    for attr_name in ("then_block", "else_block", "body", "try_block", "catch_block"):
        child = getattr(node, attr_name, None)
        if child is None:
            continue
        if isinstance(child, ElseBlock) and child.body:
            child = child.body
        elif isinstance(child, ElseIf) and child.if_stmt:
            _scan_for_var_types(var_name, child.if_stmt, class_table, candidates)
            continue
        for statement in getattr(child, "statements", []):
            _scan_for_var_types(var_name, statement, class_table, candidates)


def _var_decl_type(node: VarDeclStmt, class_table: dict[str, ClassInfo]) -> str | None:
    if node.type and _known_type(node.type.base, class_table):
        return node.type.base
    if isinstance(node.initializer, CallExpr):
        callee = node.initializer.callee
        if isinstance(callee, Identifier) and callee.name in class_table:
            return callee.name
    if isinstance(node.initializer, NewExpr):
        type_expr = node.initializer.type
        if type_expr and _known_type(type_expr.base, class_table):
            return type_expr.base
    return None
