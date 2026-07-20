"""Lexical facts used by conservative opaque-borrow effect analysis."""

from dataclasses import fields, is_dataclass

from ..ast_nodes import (
    DeleteStmt,
    Identifier,
    KeepStmt,
    LambdaExpr,
    ReleaseStmt,
    ThrowStmt,
    VarDeclStmt,
)

_LOCATION_FIELDS = frozenset({"line", "col", "source_file"})


def raw_expression_mentions_parameter(node, name: str) -> bool:
    if node is None:
        return False
    if isinstance(node, Identifier):
        return node.name == name
    if isinstance(node, LambdaExpr):
        if any(parameter.name == name for parameter in node.params):
            return False
        return raw_expression_mentions_parameter(node.body, name)
    if isinstance(node, (str, int, float, bool)):
        return False
    if isinstance(node, (list, tuple)):
        return any(raw_expression_mentions_parameter(item, name) for item in node)
    if not is_dataclass(node):
        return False
    return any(
        raw_expression_mentions_parameter(getattr(node, field.name), name)
        for field in fields(node)
        if field.name not in _LOCATION_FIELDS
    )


def raw_statement_consumes_parameter(node, name: str) -> bool:
    return isinstance(node, (DeleteStmt, KeepStmt, ReleaseStmt, ThrowStmt)) and (
        raw_expression_mentions_parameter(node.expr, name)
    )


def raw_local_names(declaration) -> frozenset[str]:
    names = {parameter.name for parameter in (getattr(declaration, "params", ()) or ())}

    def collect(node) -> None:
        if node is None or isinstance(node, (str, int, float, bool)):
            return
        if isinstance(node, (list, tuple)):
            for item in node:
                collect(item)
            return
        if not is_dataclass(node):
            return
        if isinstance(node, VarDeclStmt):
            names.add(node.name)
        for field in fields(node):
            if field.name not in _LOCATION_FIELDS:
                collect(getattr(node, field.name))

    collect(getattr(declaration, "body", None))
    return frozenset(names)


__all__ = [
    "raw_expression_mentions_parameter",
    "raw_local_names",
    "raw_statement_consumes_parameter",
]
