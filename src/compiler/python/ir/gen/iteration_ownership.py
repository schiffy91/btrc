"""Owned synthetic iterable lifetimes for ordinary ``for-in`` lowering."""

from __future__ import annotations

from ..nodes import IRAssign, IRExprStmt, IRLiteral, IRStmt, IRVar
from .managed_local import ManagedLocal


def iterable_result_is_owned(gen, expression, type_expr) -> bool:
    """Whether the loop receives a fresh managed iterable reference."""

    if not gen.managed_values.is_managed(type_expr):
        return False

    return gen.ownership.owns_result(expression)


def begin_owned_iterable(
    gen,
    expression,
    type_expr,
    name: str,
    prefix: list[IRStmt],
) -> ManagedLocal | None:
    """Own one managed iterable for the complete lowered loop lifetime.

    A fresh expression transfers its existing +1 into the synthetic local.
    A borrowed expression is retained after its exact-once hoist.  Registering
    either form before lowering the body makes return/throw cleanup see it,
    while the loop control marker keeps it live across continue and break.
    """

    if not gen.managed_values.is_managed(type_expr):
        return None
    if not iterable_result_is_owned(gen, expression, type_expr):
        prefix.append(
            IRExprStmt(
                expr=gen.lifetime.retain_value(
                    IRVar(name=name),
                    type_expr,
                )
            )
        )

    owner = ManagedLocal(
        name=name,
        type_name=gen.managed_values.runtime_name(type_expr),
        cycle_seed=not gen.managed_values.is_string(type_expr),
    )
    gen.register_managed_var(owner.name, owner.type_name, cycle_seed=owner.cycle_seed)
    gen.lifetime.register_named_cleanup(
        owner.name,
        owner.type_name,
        prefix,
    )
    return owner


def finish_owned_iterable(gen, owner: ManagedLocal | None) -> list[IRStmt]:
    """Release one owned hoist after exhaustion or a loop ``break``."""
    if owner is None:
        return []
    gen.unregister_managed_var(owner.name)
    result = gen.lifetime.release_scope([owner])
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
