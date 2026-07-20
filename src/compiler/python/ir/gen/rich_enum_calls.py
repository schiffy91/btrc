"""Rich-enum constructor target resolution shared by call lowerers."""

from __future__ import annotations

from ...ast_nodes import FieldAccessExpr, Identifier
from ..nodes import IRCall


def rich_enum_variant_target(gen, node, *, identifier_is_local=None):
    """Return ``(enum_name, variant)`` for a lexical type-qualified call."""

    callee = getattr(node, "callee", None)
    if not isinstance(callee, FieldAccessExpr) or not isinstance(callee.obj, Identifier):
        return None
    owner = callee.obj.name
    is_local = identifier_is_local or gen.local_ownership_declared
    if is_local(owner):
        return None
    declaration = gen.analyzed.rich_enum_table.get(owner)
    if declaration is None:
        return None
    variant = next(
        (candidate for candidate in declaration.variants if candidate.name == callee.field),
        None,
    )
    return (owner, variant) if variant is not None else None


def lower_generic_rich_enum_call(emitter, expression, params, args, arg_names):
    """Lower a variant call from a monomorphized generic body."""

    target = rich_enum_variant_target(
        emitter._gen,
        expression,
        identifier_is_local=lambda name: name in emitter._var_types,
    )
    if target is None:
        return None
    from .generics.user_call_arguments import order_generic_call_arguments

    ordered = order_generic_call_arguments(
        emitter,
        params,
        expression.args,
        arg_names,
        args,
    )
    return IRCall(callee=f"{target[0]}_{target[1].name}", args=ordered)


__all__ = ["lower_generic_rich_enum_call", "rich_enum_variant_target"]
