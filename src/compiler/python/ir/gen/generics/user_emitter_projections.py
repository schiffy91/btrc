"""Owned-receiver field and index projections in generic method bodies."""

from __future__ import annotations

from ....index_protocol import indexed_protocol_info
from ...nodes import IRCall, IRFieldAccess, IRIndex
from ..fields import receiver_uses_arrow
from ..types import mangle_generic_type


def lower_generic_field_access(emitter, expression):
    """Consume an owned receiver while preserving a projected result."""
    result_type = emitter._resolve_expr_type(expression)
    from ....class_storage import custom_property_getter

    custom_getter = custom_property_getter(
        emitter._gen.analyzed.class_table,
        emitter._resolve_expr_type(expression.obj),
        expression.field,
    )
    sequenced = emitter._sequence_owned_nodes(
        [expression.obj],
        expression,
        lambda: _plain_field_access(emitter, expression),
        pin_nodes=[expression.obj] if custom_getter else [],
        promote_result=bool(emitter._is_managed_type(result_type) and not emitter._projection_is_call(expression)),
    )
    if sequenced is not None:
        return sequenced
    return _plain_field_access(emitter, expression)


def lower_generic_index(emitter, expression):
    """Sequence owned receiver/index values and lower collection get calls."""
    receiver_type = emitter._resolve_expr_type(expression.obj)
    protocol_getter = indexed_protocol_info(
        receiver_type,
        emitter._gen.analyzed.class_table,
        method="get",
    )
    sequenced = emitter._sequence_owned_nodes(
        [expression.obj, expression.index],
        expression,
        lambda: _plain_index(emitter, expression),
        pin_nodes=[expression.obj] if protocol_getter is not None else [],
    )
    if sequenced is not None:
        return sequenced
    return _plain_index(emitter, expression)


def _plain_field_access(emitter, expression):
    from ....ast_nodes import Identifier, SelfExpr
    from ...nodes import IRFunctionRef, IRVar

    receiver_type = emitter._resolve_expr_type(expression.obj)
    field = expression.field
    if emitter._gen is not None:
        from ..parameters import source_field_c_name

        field = source_field_c_name(
            emitter._gen.analyzed,
            expression.obj,
            field,
            resolve_type=emitter._resolve_expr_type,
        )
    if (
        isinstance(expression.obj, Identifier)
        and emitter._gen is not None
        and expression.obj.name not in emitter._var_types
    ):
        owner = emitter._gen.analyzed.class_table.get(expression.obj.name)
        if owner is not None:
            if field in owner.static_fields:
                return IRVar(name=f"{expression.obj.name}_{field}")
            method = owner.methods.get(expression.field)
            if method is not None and method.access == "class":
                return IRFunctionRef(name=f"{expression.obj.name}_{expression.field}")
    class_info = (
        emitter._gen.analyzed.class_table.get(receiver_type.base)
        if emitter._gen is not None and receiver_type is not None
        else None
    )
    receiver = IRVar(name="self") if isinstance(expression.obj, SelfExpr) else emitter._expr(expression.obj)
    if isinstance(expression.obj, SelfExpr) and emitter._current_property_backing == field:
        return IRFieldAccess(
            obj=receiver,
            field=f"_prop_{field}",
            arrow=True,
        )
    if class_info is not None and field in class_info.properties:
        prefix = receiver_type.base
        if receiver_type.generic_args and class_info.generic_params:
            prefix = mangle_generic_type(
                receiver_type.base,
                receiver_type.generic_args,
            )
        return IRCall(
            callee=f"{prefix}_get_{field}",
            args=[receiver],
        )
    return IRFieldAccess(
        obj=receiver,
        field=field,
        arrow=bool(
            emitter._gen
            and receiver_uses_arrow(
                emitter._gen,
                receiver_type,
                explicit=expression.arrow,
            )
        ),
    )


def _plain_index(emitter, expression):
    receiver_type = emitter._resolve_expr_type(expression.obj)
    receiver = emitter._expr(expression.obj)
    index = emitter._expr(expression.index)
    if (
        emitter._gen is not None
        and receiver_type is not None
        and indexed_protocol_info(
            receiver_type,
            emitter._gen.analyzed.class_table,
            method="get",
        )
    ):
        class_info = emitter._gen.analyzed.class_table[receiver_type.base]
        target = (
            mangle_generic_type(receiver_type.base, receiver_type.generic_args)
            if receiver_type.generic_args and class_info.generic_params
            else receiver_type.base
        )
        return IRCall(callee=f"{target}_get", args=[receiver, index])
    return IRIndex(obj=receiver, index=index)


__all__ = ["lower_generic_field_access", "lower_generic_index"]
