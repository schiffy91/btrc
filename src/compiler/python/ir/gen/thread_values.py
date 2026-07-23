"""Portable value transport across the pthread ``void*`` result ABI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import TypeExpr
from ..nodes import (
    CType,
    IRCast,
    IRFunctionRef,
    IRLiteral,
    IRSizeof,
)
from .handle_values import consume_addressable_handle
from .types import CTypeRenderer
from .value_boxes import (
    box_exact_value,
    canonical_value_type,
    is_scalar_void,
    unbox_exact_value,
)

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def box_thread_result(
    gen: IRLowerer,
    expr,
    result_type: TypeExpr | None,
    type_renderer: CTypeRenderer,
):
    """Return one ``void*`` payload without changing the result's bits."""
    canonical = canonical_value_type(gen, result_type)
    if canonical is None or is_scalar_void(canonical):
        return IRLiteral(text="NULL")
    if not _requires_box(gen, canonical):
        return IRCast(target_type=CType(text="void*"), expr=expr)

    return box_exact_value(
        gen,
        expr,
        canonical,
        type_renderer,
        prefix="__btrc_thread",
    )


def unbox_thread_result(
    gen: IRLowerer,
    payload_call,
    result_type: TypeExpr | None,
    type_renderer: CTypeRenderer,
):
    """Copy a boxed value before freeing its transport allocation."""
    canonical = canonical_value_type(gen, result_type)
    if canonical is None or is_scalar_void(canonical):
        return payload_call
    if not _requires_box(gen, canonical):
        return IRCast(
            target_type=CType(text=type_renderer.render(result_type)),
            expr=payload_call,
        )

    return unbox_exact_value(
        gen,
        payload_call,
        canonical,
        type_renderer,
        prefix="__btrc_thread",
    )


def consume_thread_handle(gen: IRLowerer, obj):
    """Move an addressable handle out of its source slot exactly once."""
    return consume_addressable_handle(
        gen,
        obj,
        handle_c_type="__btrc_thread_t",
        prefix="__btrc_thread",
    )


def thread_result_disposal_args(
    gen: IRLowerer,
    result_type: TypeExpr | None,
):
    """Describe how scope cleanup must dispose an unclaimed thread result."""
    canonical = canonical_value_type(gen, result_type)
    null = IRLiteral(text="NULL")
    zero = IRLiteral(text="0")
    if canonical is None or is_scalar_void(canonical):
        return [null, zero, null, null]

    from .managed_values import is_class_type, is_string_type

    if is_string_type(gen, canonical):
        return [
            null,
            zero,
            _disposal_callback(gen, "__btrc_thread_string_dispose"),
            null,
        ]
    if is_class_type(gen, canonical):
        from .arc_ops import arc_type_descriptor

        return [
            arc_type_descriptor(gen, canonical),
            IRSizeof(operand=CType(text="__btrc_arc_type")),
            _disposal_callback(gen, "__btrc_thread_arc_dispose"),
            _disposal_callback(gen, "__btrc_throw"),
        ]
    if _requires_box(gen, canonical):
        return [
            null,
            zero,
            _disposal_callback(gen, "__btrc_thread_box_dispose"),
            null,
        ]
    return [null, zero, null, null]


def _disposal_callback(gen: IRLowerer, name: str):
    gen.helpers.use(name)
    return IRFunctionRef(name=name)


def _requires_box(gen: IRLowerer, type_expr: TypeExpr) -> bool:
    # ISO C does not define conversions between function pointers and void*.
    if type_expr.base == "__fn_ptr":
        return True
    return not gen.type_identity.is_reference(
        type_expr,
        gen.analyzed.class_table,
        gen.analyzed.interface_table,
    )


__all__ = [
    "box_thread_result",
    "consume_thread_handle",
    "thread_result_disposal_args",
    "unbox_thread_result",
]
