"""Managed call boundaries for property and indexed setter sugar."""

from __future__ import annotations

from collections.abc import Callable

from ...index_protocol import indexed_protocol
from ..nodes import IRCommaExpr
from .call_boundary import CallOperand, sequence_call_boundary
from .managed_values import is_managed_type


def lower_virtual_store_boundary(
    gen,
    node,
    plan,
    *,
    lower_value,
    coerce,
    render_type: Callable,
    fresh_temp: Callable,
    cleanup_active: bool,
    record_decl: Callable,
    owns_result: Callable,
    prepare=None,
    activate_cleanup=None,
):
    """Give setter sugar the same owned-argument boundary as a call."""
    if plan.kind not in {"collection", "property"}:
        return None
    setter = None
    if plan.kind == "collection":
        receiver_type = gen.analyzed.node_types.get(id(node.target.obj))
        protocol = indexed_protocol(receiver_type, gen.analyzed.class_table)
        setter = protocol.setter if protocol is not None else None
        if setter is None:
            return None

    lowered = lower_value(plan.value_type, node.value)
    if prepare is None:
        from .prepared_values import prepare_normal_value

        prepared = prepare_normal_value(
            gen,
            node.value,
            plan.value_type,
            lowered=lowered,
        )
    else:
        prepared = prepare(node.value, plan.value_type, lowered)
    source_type = prepared.effective_type
    managed = is_managed_type(gen, source_type)
    owned = bool(managed and prepared.owned)
    keep = bool(managed and setter is not None and setter.params[1].keep)
    if not managed and not prepared.converted:
        return None
    from .evaluation_order import borrowed_value_can_be_pinned

    operand = CallOperand(
        node=node.value,
        type_expr=source_type,
        c_type=render_type(source_type),
        keep=keep,
        pin=bool(managed and not owned and borrowed_value_can_be_pinned(node.value)),
        owned=owned,
        lowered=prepared.value,
    )

    def build_store(overrides):
        source = overrides[id(node.value)]
        value = coerce(plan.value_type, source_type, source)
        return IRCommaExpr(expressions=[plan.store(value), value])

    # The setter ABI returns an owned assignment result when its RHS already
    # produced +1 or target-directed conversion created +1. The outer target
    # boundary recognizes that contract and does not promote it a second time.
    result_owned = bool(is_managed_type(gen, plan.value_type) or owns_result(node.value) or prepared.converted)
    boundary = sequence_call_boundary(
        gen,
        [operand],
        lower_expr=lambda _value: None,
        build_call=build_store,
        result_c_type=render_type(plan.value_type),
        result_type=plan.value_type,
        fresh_temp=fresh_temp,
        cleanup_active=cleanup_active,
        record_decl=record_decl,
        promote_result=result_owned,
        activate_cleanup=activate_cleanup,
        result_owned=result_owned,
    )
    return plan.wrap([boundary])


__all__ = ["lower_virtual_store_boundary"]
