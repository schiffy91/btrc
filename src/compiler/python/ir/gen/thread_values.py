"""Portable value transport across the pthread ``void*`` result ABI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import TypeExpr
from ...reference_semantics import is_reference_type
from ..nodes import (
    CType,
    IRCast,
    IRLiteral,
    IRSizeof,
    IRVar,
)
from .handle_values import consume_addressable_handle
from .types import type_to_c
from .value_boxes import (
    box_exact_value,
    canonical_value_type,
    is_scalar_void,
    unbox_exact_value,
)

if TYPE_CHECKING:
    from .generator import IRGenerator


def box_thread_result(
    gen: IRGenerator,
    expr,
    result_type: TypeExpr | None,
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
        prefix="__btrc_thread",
    )


def unbox_thread_result(
    gen: IRGenerator,
    payload_call,
    result_type: TypeExpr | None,
):
    """Copy a boxed value before freeing its transport allocation."""
    canonical = canonical_value_type(gen, result_type)
    if canonical is None or is_scalar_void(canonical):
        return payload_call
    if not _requires_box(gen, canonical):
        return IRCast(
            target_type=CType(text=type_to_c(result_type)),
            expr=payload_call,
        )

    return unbox_exact_value(
        gen,
        payload_call,
        canonical,
        prefix="__btrc_thread",
    )


def consume_thread_handle(gen: IRGenerator, obj):
    """Move an addressable handle out of its source slot exactly once."""
    return consume_addressable_handle(
        gen,
        obj,
        handle_c_type="__btrc_thread_t",
        prefix="__btrc_thread",
    )


def thread_result_disposal_args(
    gen: IRGenerator,
    result_type: TypeExpr | None,
):
    """Describe how scope cleanup must dispose an unclaimed thread result."""
    canonical = canonical_value_type(gen, result_type)
    null = IRLiteral(text="NULL")
    zero = IRLiteral(text="0")
    if canonical is None or is_scalar_void(canonical):
        return [null, zero, null]

    from .managed_values import is_class_type, is_string_type

    if is_string_type(gen, canonical):
        return [
            null,
            zero,
            _disposal_callback(gen, "__btrc_thread_string_dispose"),
        ]
    if is_class_type(gen, canonical):
        from .arc_ops import arc_type_descriptor

        return [
            arc_type_descriptor(gen, canonical),
            IRSizeof(operand=CType(text="__btrc_arc_type")),
            _disposal_callback(gen, "__btrc_thread_arc_dispose"),
        ]
    if _requires_box(gen, canonical):
        return [
            null,
            zero,
            _disposal_callback(gen, "__btrc_thread_box_dispose"),
        ]
    return [null, zero, null]


def _disposal_callback(gen: IRGenerator, name: str):
    gen.use_helper(name)
    return IRVar(name=name)


def _requires_box(gen: IRGenerator, type_expr: TypeExpr) -> bool:
    # ISO C does not define conversions between function pointers and void*.
    if type_expr.base == "__fn_ptr":
        return True
    return not is_reference_type(
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
