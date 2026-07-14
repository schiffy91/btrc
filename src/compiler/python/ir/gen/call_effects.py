"""Conservative source-call ownership effects."""

from __future__ import annotations

from ...ast_nodes import (
    CallExpr,
    DeleteStmt,
    FieldAccessExpr,
    Identifier,
    ReturnStmt,
)


def callable_for_call(gen, node: CallExpr):
    """Resolve the source declaration targeted by ``node`` when possible."""
    callee = node.callee
    if isinstance(callee, FieldAccessExpr):
        receiver_type = gen.analyzed.node_types.get(id(callee.obj))
        if receiver_type is not None:
            class_info = gen.analyzed.class_table.get(receiver_type.base)
            if class_info is not None:
                method = class_info.methods.get(callee.field)
                if method is not None:
                    return method
        if isinstance(callee.obj, Identifier):
            class_info = gen.analyzed.class_table.get(callee.obj.name)
            if class_info is not None:
                return class_info.methods.get(callee.field)
        return None

    if not isinstance(callee, Identifier):
        return None
    class_info = gen.analyzed.class_table.get(callee.name)
    if class_info is not None:
        return class_info.constructor
    return gen.analyzed.function_table.get(callee.name)


def owned_transfer_param_indices(declaration) -> frozenset[int]:
    """Return parameters that unconditionally consume caller-owned values.

    ``delete`` force-destroys its lvalue.  A fresh result passed directly to a
    callable therefore transfers its one reference when the callable consists
    of unconditional leading parameter deletes and an optional bare return.
    Keep this proof deliberately narrow: branching, later effects, and valued
    returns do not establish a transfer contract.
    """
    body = getattr(declaration, "body", None)
    params = getattr(declaration, "params", None)
    if body is None or not params:
        return frozenset()

    indices = {parameter.name: index for index, parameter in enumerate(params) if not parameter.keep}
    transferred: set[int] = set()
    statements = body.statements
    for position, statement in enumerate(statements):
        if isinstance(statement, DeleteStmt) and isinstance(statement.expr, Identifier):
            index = indices.get(statement.expr.name)
            if index is None:
                return frozenset()
            transferred.add(index)
            continue
        if isinstance(statement, ReturnStmt) and statement.value is None and position == len(statements) - 1:
            break
        return frozenset()
    return frozenset(transferred)


__all__ = ["callable_for_call", "owned_transfer_param_indices"]
