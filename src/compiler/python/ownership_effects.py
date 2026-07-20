"""Source-level ownership effects shared by analysis and IR planning."""

from __future__ import annotations

from .ast_nodes import DeleteStmt, Identifier, ReleaseStmt, ReturnStmt


def _callable_statements(declaration):
    """Return a callable's block statements, including wrapped lambda blocks."""
    body = getattr(declaration, "body", None)
    statements = getattr(body, "statements", None)
    if statements is not None:
        return statements
    return getattr(getattr(body, "body", None), "statements", ())


def owned_transfer_param_indices(declaration) -> frozenset[int]:
    """Parameters consumed by unconditional leading release/delete statements."""
    body = getattr(declaration, "body", None)
    params = getattr(declaration, "params", None)
    if body is None or not params:
        return frozenset()

    indices = {parameter.name: index for index, parameter in enumerate(params) if not parameter.keep}
    transferred: set[int] = set()
    statements = _callable_statements(declaration)
    for position, statement in enumerate(statements):
        if isinstance(statement, (DeleteStmt, ReleaseStmt)) and isinstance(
            statement.expr,
            Identifier,
        ):
            index = indices.get(statement.expr.name)
            if index is None:
                return frozenset()
            transferred.add(index)
            continue
        if isinstance(statement, ReturnStmt) and statement.value is None and position == len(statements) - 1:
            break
        return frozenset()
    return frozenset(transferred)


__all__ = ["owned_transfer_param_indices"]
