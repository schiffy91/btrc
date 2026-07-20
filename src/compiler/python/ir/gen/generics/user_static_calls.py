"""Ordinary class-qualified calls inside generic specializations."""

from ....ast_nodes import FieldAccessExpr, Identifier
from ...nodes import IRCall
from .user_call_arguments import order_generic_call_arguments


def lower_ordinary_static_call(
    emitter,
    expression,
    args,
    arg_names,
    params,
):
    callee = expression.callee
    if not isinstance(callee, FieldAccessExpr):
        return None
    receiver = callee.obj
    if not isinstance(receiver, Identifier) or receiver.name in emitter._var_types:
        return None
    class_info = emitter._gen.analyzed.class_table.get(receiver.name)
    method = class_info.methods.get(callee.field) if class_info else None
    if method is None or method.access != "class":
        return None
    args = order_generic_call_arguments(
        emitter,
        params,
        expression.args,
        arg_names,
        args,
    )
    return IRCall(
        callee=f"{receiver.name}_{callee.field}",
        args=args,
    )


__all__ = ["lower_ordinary_static_call"]
