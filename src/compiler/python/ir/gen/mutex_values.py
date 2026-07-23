"""Typed value transport and ownership metadata for ``Mutex<T>``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import (
    CType,
    IRCall,
    IRFunctionRef,
    IRLiteral,
    IRSizeof,
)
from .errors import CodegenError
from .value_boxes import (
    box_exact_value,
    canonical_value_type,
    unbox_exact_value,
    value_storage_c_type,
)

if TYPE_CHECKING:
    from ...ast_nodes import TypeExpr
    from .lowerer import IRLowerer
    from .types import CTypeRenderer


def create_mutex_value(
    gen: IRLowerer,
    value,
    value_type: TypeExpr,
    type_renderer: CTypeRenderer,
):
    """Create a mutex that owns an exact copy of ``value``."""
    canonical = canonical_value_type(gen, value_type)
    if canonical is None:
        raise CodegenError("cannot resolve Mutex value type")
    (
        access,
        slot_access,
        context,
        context_size,
        retain,
        release,
        finalize,
        raise_callback,
    ) = _ownership_callbacks(gen, canonical, type_renderer)
    gen.helpers.use("__btrc_mutex_val_create")
    return IRCall(
        callee="__btrc_mutex_val_create",
        args=[
            box_exact_value(
                gen,
                value,
                canonical,
                type_renderer,
                prefix="__btrc_mutex",
            ),
            IRSizeof(operand=CType(text=value_storage_c_type(canonical, type_renderer))),
            access,
            slot_access,
            context,
            context_size,
            retain,
            release,
            finalize,
            raise_callback,
        ],
        helper_ref="__btrc_mutex_val_create",
    )


def get_mutex_value(
    gen: IRLowerer,
    mutex,
    value_type: TypeExpr,
    type_renderer: CTypeRenderer,
):
    """Copy the stored value while locked and return one typed value."""
    gen.helpers.use("__btrc_mutex_val_get")
    payload = IRCall(
        callee="__btrc_mutex_val_get",
        args=[mutex],
        helper_ref="__btrc_mutex_val_get",
    )
    return unbox_exact_value(
        gen,
        payload,
        value_type,
        type_renderer,
        prefix="__btrc_mutex",
    )


def set_mutex_value(
    gen: IRLowerer,
    mutex,
    value,
    value_type: TypeExpr,
    type_renderer: CTypeRenderer,
):
    """Transfer a newly boxed value to the runtime's locked swap."""
    gen.helpers.use("__btrc_mutex_val_set")
    return IRCall(
        callee="__btrc_mutex_val_set",
        args=[
            mutex,
            box_exact_value(
                gen,
                value,
                value_type,
                type_renderer,
                prefix="__btrc_mutex",
            ),
        ],
        helper_ref="__btrc_mutex_val_set",
    )


def _ownership_callbacks(
    gen: IRLowerer,
    value_type: TypeExpr,
    type_renderer: CTypeRenderer,
):
    from .managed_values import is_class_type, is_string_type

    if is_string_type(gen, value_type):
        access = _value_access(gen, value_type, type_renderer)
        return (
            access,
            IRLiteral(text="NULL"),
            IRLiteral(text="NULL"),
            IRLiteral(text="0"),
            _callback(gen, "__btrc_mutex_string_retain"),
            _callback(gen, "__btrc_mutex_string_release"),
            IRLiteral(text="NULL"),
            IRLiteral(text="NULL"),
        )
    if is_class_type(gen, value_type):
        from .arc_ops import arc_type_descriptor

        return (
            _value_access(gen, value_type, type_renderer),
            _slot_access(gen, value_type, type_renderer),
            arc_type_descriptor(gen, value_type),
            IRSizeof(operand=CType(text="__btrc_arc_type")),
            _callback(gen, "__btrc_mutex_arc_retain"),
            _callback(gen, "__btrc_mutex_arc_release"),
            _callback(gen, "__btrc_mutex_arc_finalize"),
            _callback(gen, "__btrc_throw"),
        )
    null = IRLiteral(text="NULL")
    return null, null, null, IRLiteral(text="0"), null, null, null, null


def _value_access(
    gen: IRLowerer,
    value_type: TypeExpr,
    type_renderer: CTypeRenderer,
):
    from .cleanup_slots import ensure_mutex_value_adapter

    name = ensure_mutex_value_adapter(
        gen,
        CType(text=value_storage_c_type(value_type, type_renderer)),
    )
    return IRFunctionRef(name=name)


def _slot_access(
    gen: IRLowerer,
    value_type: TypeExpr,
    type_renderer: CTypeRenderer,
):
    from .cleanup_slots import ensure_arc_slot_adapter

    name = ensure_arc_slot_adapter(
        gen,
        CType(text=value_storage_c_type(value_type, type_renderer)),
    )
    return IRFunctionRef(name=name)


def _callback(gen: IRLowerer, name: str):
    gen.helpers.use(name)
    return IRFunctionRef(name=name)


__all__ = [
    "create_mutex_value",
    "get_mutex_value",
    "set_mutex_value",
]
