"""Typed value transport and ownership metadata for ``Mutex<T>``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import CType, IRCall, IRLiteral, IRSizeof, IRVar
from .errors import CodegenError
from .handle_values import consume_addressable_handle
from .value_boxes import (
    box_exact_value,
    canonical_value_type,
    unbox_exact_value,
    value_storage_c_type,
)

if TYPE_CHECKING:
    from ...ast_nodes import TypeExpr
    from .generator import IRGenerator


def create_mutex_value(gen: IRGenerator, value, value_type: TypeExpr):
    """Create a mutex that owns an exact copy of ``value``."""
    canonical = canonical_value_type(gen, value_type)
    if canonical is None:
        raise CodegenError("cannot resolve Mutex value type")
    context, context_size, retain, release = _ownership_callbacks(gen, canonical)
    gen.use_helper("__btrc_mutex_val_create")
    return IRCall(
        callee="__btrc_mutex_val_create",
        args=[
            box_exact_value(
                gen,
                value,
                canonical,
                prefix="__btrc_mutex",
            ),
            IRSizeof(operand=CType(text=value_storage_c_type(canonical))),
            context,
            context_size,
            retain,
            release,
        ],
        helper_ref="__btrc_mutex_val_create",
    )


def get_mutex_value(gen: IRGenerator, mutex, value_type: TypeExpr):
    """Copy the stored value while locked and return one typed value."""
    gen.use_helper("__btrc_mutex_val_get")
    payload = IRCall(
        callee="__btrc_mutex_val_get",
        args=[mutex],
        helper_ref="__btrc_mutex_val_get",
    )
    return unbox_exact_value(
        gen,
        payload,
        value_type,
        prefix="__btrc_mutex",
    )


def set_mutex_value(
    gen: IRGenerator,
    mutex,
    value,
    value_type: TypeExpr,
):
    """Transfer a newly boxed value to the runtime's locked swap."""
    gen.use_helper("__btrc_mutex_val_set")
    return IRCall(
        callee="__btrc_mutex_val_set",
        args=[
            mutex,
            box_exact_value(
                gen,
                value,
                value_type,
                prefix="__btrc_mutex",
            ),
        ],
        helper_ref="__btrc_mutex_val_set",
    )


def consume_mutex_handle(gen: IRGenerator, obj):
    """Move an addressable mutex handle before destroying it."""
    return consume_addressable_handle(
        gen,
        obj,
        handle_c_type="__btrc_mutex_val_t",
        prefix="__btrc_mutex",
    )


def _ownership_callbacks(gen: IRGenerator, value_type: TypeExpr):
    from .managed_values import is_class_type, is_string_type

    if is_string_type(gen, value_type):
        return (
            IRLiteral(text="NULL"),
            IRLiteral(text="0"),
            _callback(gen, "__btrc_mutex_string_retain"),
            _callback(gen, "__btrc_mutex_string_release"),
        )
    if is_class_type(gen, value_type):
        from .arc_ops import arc_type_descriptor

        return (
            arc_type_descriptor(gen, value_type),
            IRSizeof(operand=CType(text="__btrc_arc_type")),
            _callback(gen, "__btrc_mutex_arc_retain"),
            _callback(gen, "__btrc_mutex_arc_release"),
        )
    null = IRLiteral(text="NULL")
    return null, IRLiteral(text="0"), null, null


def _callback(gen: IRGenerator, name: str):
    gen.use_helper(name)
    return IRVar(name=name)


__all__ = [
    "consume_mutex_handle",
    "create_mutex_value",
    "get_mutex_value",
    "set_mutex_value",
]
