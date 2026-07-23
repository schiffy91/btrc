"""Lowering for built-in calls that need type-directed IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr,
    FieldAccessExpr,
    FStringLiteral,
    StringLiteral,
    TypeExpr,
)
from ..nodes import IRCall, IRFieldAccess, IRLiteral
from .errors import CodegenError
from .mutex_values import create_mutex_value
from .printf_args import adapt_printf_arg
from .type_resolution import canonical_type
from .types import format_spec_for_type, is_string_type

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def lower_print(gen: IRLowerer, args: list, lowered_args: list):
    """Lower ``print`` to one typed ``printf`` call."""
    from .expressions import lower_expr

    return lower_typed_print(
        gen,
        args,
        lower_value=lambda arg: lower_expr(gen, arg),
        resolve_type=lambda arg: gen.analyzed.node_types.get(id(arg)),
        lowered_values=lowered_args,
    )


def lower_typed_print(
    gen,
    args,
    *,
    lower_value,
    resolve_type,
    lowered_values=None,
):
    """Lower print with caller-provided value and concrete-type resolution."""
    from .stringable import has_to_string

    if not args:
        return IRCall(callee="printf", args=[IRLiteral(text='"\\n"')])

    formats = []
    ir_args = []
    for index, arg in enumerate(args):
        ir_arg = lowered_values[index] if lowered_values is not None else lower_value(arg)
        arg_type = canonical_type(
            resolve_type(arg),
            gen.analyzed.typedef_table,
        )
        fmt = format_spec_for_type(arg_type)
        boundary_type = arg_type

        if has_to_string(gen.analyzed, arg_type):
            fmt = "%s"
            boundary_type = TypeExpr(base="string")

        if arg_type is None:
            if isinstance(arg, (FStringLiteral, StringLiteral)):
                fmt = "%s"
            elif isinstance(arg, CallExpr):
                callee = arg.callee
                if getattr(callee, "name", None) in ("toString", "str"):
                    fmt = "%s"
                if isinstance(callee, FieldAccessExpr) and callee.field in _STRING_METHODS:
                    fmt = "%s"

        adapted = adapt_printf_arg(gen, ir_arg, boundary_type, fmt)
        formats.append(adapted.format_spec)
        ir_args.append(adapted.value)

    format_string = " ".join(formats) + "\\n"
    return IRCall(
        callee="printf",
        args=[IRLiteral(text=f'"{format_string}"'), *ir_args],
    )


def lower_len(gen, value, value_type):
    """Lower semantic string length through the checked runtime helper."""
    resolved = canonical_type(value_type, gen.analyzed.typedef_table)
    if is_string_type(resolved):
        gen.helpers.use("__btrc_string_length")
        return IRCall(
            callee="__btrc_string_length",
            args=[value],
            helper_ref="__btrc_string_length",
        )
    return IRFieldAccess(obj=value, field="len", arrow=True)


_STRING_METHODS = frozenset(
    (
        "toString",
        "str",
        "trim",
        "toUpper",
        "toLower",
        "substring",
        "replace",
        "repeat",
        "reverse",
        "capitalize",
        "join",
        "split",
    )
)


def lower_mutex_constructor(
    gen: IRLowerer,
    ast_args,
    ir_args,
    value_type=None,
):
    """Lower ``Mutex(value)`` to the opaque runtime handle constructor."""
    if not ast_args:
        raise CodegenError("Mutex construction requires one initial value")
    value_type = value_type or gen.analyzed.node_types.get(id(ast_args[0]))
    if value_type is None:
        raise CodegenError("cannot resolve Mutex initializer type")
    return create_mutex_value(
        gen,
        ir_args[0],
        value_type,
    )
