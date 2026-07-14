"""Owned RHS boundaries for property stores in generic specializations."""

from __future__ import annotations

from ...nodes import IRCall, IRCommaExpr
from ..call_boundary import CallOperand
from ..types import mangle_generic_type


def lower_generic_property_assignment(emitter, expression):
    """Call a property setter and consume a caller-owned managed RHS."""
    from ....ast_nodes import FieldAccessExpr

    if expression.op != "=" or not isinstance(
        expression.target,
        FieldAccessExpr,
    ):
        return None
    receiver_type = emitter._resolve_expr_type(expression.target.obj)
    if receiver_type is None:
        return None
    class_info = emitter._gen.analyzed.class_table.get(receiver_type.base)
    prop = class_info.properties.get(expression.target.field) if class_info is not None else None
    value_type = emitter._resolve_expr_type(expression.value)
    if (
        prop is None
        or not prop.has_setter
        or not emitter._is_managed_type(value_type)
        or not emitter._owns_expr(expression.value)
    ):
        return None

    prefix = receiver_type.base
    if receiver_type.generic_args and class_info.generic_params:
        prefix = mangle_generic_type(
            receiver_type.base,
            receiver_type.generic_args,
        )

    operand = CallOperand(
        node=expression.value,
        type_expr=value_type,
        c_type=emitter.iter_value_c(value_type),
        owned=True,
    )

    def setter_then_value():
        value = emitter._expr(expression.value)
        return IRCommaExpr(
            expressions=[
                IRCall(
                    callee=f"{prefix}_set_{expression.target.field}",
                    args=[emitter._expr(expression.target.obj), value],
                ),
                value,
            ]
        )

    property_type = emitter._member_type(
        receiver_type,
        expression.target.field,
    )
    return emitter._sequence_call(
        [operand],
        expression,
        setter_then_value,
        lower_expr=lambda value: emitter._assignment_value(
            property_type,
            value,
        ),
    )


__all__ = ["lower_generic_property_assignment"]
