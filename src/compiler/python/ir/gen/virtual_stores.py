"""Managed call boundaries for property and indexed setter sugar."""

from __future__ import annotations

from collections.abc import Callable

from ...index_protocol import indexed_protocol
from ..nodes import IRCommaExpr
from .call_boundary import CallOperand
from .managed_values import is_managed_type
from .types import CTypeRenderer


def lower_virtual_store_boundary(
    gen,
    node,
    plan,
    *,
    ownership,
    lower_value,
    coerce,
    type_renderer: CTypeRenderer,
    owns_result: Callable,
    render_type: Callable | None = None,
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

    render = render_type or type_renderer.render
    if prepare is None:
        from .prepared_values import prepare_normal_value

        prepared = prepare_normal_value(
            gen,
            node.value,
            plan.value_type,
            type_renderer,
            lower_value=lambda value: lower_value(plan.value_type, value),
        )
    else:
        prepared = prepare(node.value, plan.value_type)
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
        c_type=render(source_type),
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
    boundary = ownership.boundaries.sequence(
        [operand],
        lower_expr=lambda _value: None,
        build_call=build_store,
        result_c_type=render(plan.value_type),
        result_type=plan.value_type,
        promote_result=result_owned,
        activate_cleanup=activate_cleanup,
        result_owned=result_owned,
    )
    return plan.wrap([boundary])


__all__ = ["lower_virtual_store_boundary"]
