"""Target type substitutions active only while lowering synthesized defaults."""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar

from ...type_identity import substitute_type_expr

_SUBSTITUTIONS = ContextVar("btrc_call_default_substitutions", default=None)
_DECLARATION = ContextVar("btrc_default_declaration", default=None)


@contextmanager
def default_argument_scope(
    param,
    is_default=True,
    *,
    function_name: str | None = None,
    source_file: str = "",
    line_map=None,
):
    substitutions = getattr(param, "default_type_map", None) if is_default and param is not None else None
    type_token = _SUBSTITUTIONS.set(substitutions) if substitutions else None
    declaration_token = _DECLARATION.set((function_name, source_file, line_map)) if function_name is not None else None
    try:
        yield
    finally:
        if declaration_token is not None:
            _DECLARATION.reset(declaration_token)
        if type_token is not None:
            _SUBSTITUTIONS.reset(type_token)


def resolve_default_type(type_expr):
    substitutions = _SUBSTITUTIONS.get()
    if not substitutions or type_expr is None:
        return type_expr
    return substitute_type_expr(type_expr, substitutions)


def resolve_default_predefined_identifier(node):
    """Freeze context-sensitive predefined identifiers at the declaration."""

    declaration = _DECLARATION.get()
    if declaration is None:
        return None
    function_name, source_file, line_map = declaration
    source_line = node.line or 0
    if line_map is not None:
        mapped = line_map(source_line)
        if mapped is not None:
            mapped_file, source_line = mapped
            if not source_file:
                source_file = mapped_file
    if node.name == "__func__":
        return json.dumps(function_name)
    if node.name == "__LINE__":
        return str(source_line)
    if node.name == "__FILE__" and source_file:
        return json.dumps(source_file)
    return None


def lower_call_argument(gen, param, node, *, is_default=False):
    from .expressions import lower_expr

    with default_argument_scope(param, is_default):
        return lower_expr(gen, node)


def call_argument_type(gen, param, node, *, is_default=False):
    with default_argument_scope(param, is_default):
        return resolve_default_type(gen.analyzed.node_types.get(id(node)))


def in_call_argument_context(param, is_default, operation):
    with default_argument_scope(param, is_default):
        return operation()


__all__ = [
    "call_argument_type",
    "default_argument_scope",
    "in_call_argument_context",
    "lower_call_argument",
    "resolve_default_predefined_identifier",
    "resolve_default_type",
]
