"""Explicit terminal-lifetime bookkeeping for managed locals."""

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier
from ..nodes import IRAssign, IRLiteral, IRVar


def end_manual_destroy_lifetime(gen, expression):
    """Return the nulling assignment for a terminal ``local.destroy()`` call.

    Nulling makes any previously registered exception cleanup a no-op. A
    ``free()`` method only clears contents and intentionally does not end the
    instance's lifetime.
    """
    if not isinstance(expression, CallExpr):
        return None
    callee = expression.callee
    if not isinstance(callee, FieldAccessExpr) or callee.field != "destroy":
        return None
    receiver = callee.obj
    if not isinstance(receiver, Identifier):
        return None
    return IRAssign(
        target=IRVar(name=receiver.name),
        value=IRLiteral(text="NULL"),
    )
