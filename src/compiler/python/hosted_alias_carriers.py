"""Resolved hosted return-alias operands for raw-carrier traversal."""

from __future__ import annotations

from .ast_nodes import CallExpr, Identifier
from .hosted_abi import hosted_return_alias_parameter


def hosted_alias_argument(expression, hosted_call_ids):
    """Return the aliased argument only for an analyzer-resolved hosted call."""
    if (
        not isinstance(expression, CallExpr)
        or not isinstance(expression.callee, Identifier)
        or id(expression) not in hosted_call_ids
    ):
        return None
    index = hosted_return_alias_parameter(expression.callee.name)
    if index is None or not 0 <= index < len(expression.args):
        return None
    return expression.args[index]


__all__ = ["hosted_alias_argument"]
