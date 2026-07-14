"""Owned synthetic iterable lifetimes for ordinary ``for-in`` lowering."""

from __future__ import annotations

from ..nodes import IRAssign, IRLiteral, IRStmt, IRVar
from .managed_local import ManagedLocal


def iterable_result_is_owned(gen, expression, type_expr) -> bool:
    """Whether the loop receives a fresh managed iterable reference."""
    from .managed_values import is_managed_type

    if not is_managed_type(gen, type_expr):
        return False
    from .ownership import owns_result

    return owns_result(gen, expression)


def begin_owned_iterable(
    gen,
    expression,
    type_expr,
    name: str,
    prefix: list[IRStmt],
) -> ManagedLocal | None:
    """Track an owned hoist while its loop body is being lowered."""
    if not iterable_result_is_owned(gen, expression, type_expr):
        return None
    from .managed_values import is_string_type, runtime_name
    from .variables import _maybe_register_cleanup

    owner = ManagedLocal(
        name=name,
        type_name=runtime_name(gen, type_expr),
        cycle_seed=not is_string_type(gen, type_expr),
    )
    gen.register_managed_var(owner.name, owner.type_name, cycle_seed=owner.cycle_seed)
    _maybe_register_cleanup(gen, owner.name, owner.type_name, prefix)
    return owner


def finish_owned_iterable(gen, owner: ManagedLocal | None) -> list[IRStmt]:
    """Release one owned hoist after exhaustion or a loop ``break``."""
    if owner is None:
        return []
    from .arc import _emit_scope_release

    gen.unregister_managed_var(owner.name)
    result = _emit_scope_release([owner], gen)
    # A try-scope registration may remain until its enclosing lexical marker.
    # Null the still-live slot so a later throw cannot release it twice.
    result.append(
        IRAssign(
            target=IRVar(name=owner.name),
            value=IRLiteral(text="NULL"),
        )
    )
    return result


__all__ = [
    "begin_owned_iterable",
    "finish_owned_iterable",
    "iterable_result_is_owned",
]
