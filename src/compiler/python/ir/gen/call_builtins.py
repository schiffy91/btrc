"""Lowering for built-in calls that need type-directed IR."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    CallExpr,
    FieldAccessExpr,
    FStringLiteral,
    StringLiteral,
)
from ..nodes import IRCall, IRLiteral, IRTernary
from .errors import CodegenError
from .mutex_values import create_mutex_value
from .types import format_spec_for_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_print(gen: IRGenerator, args: list):
    """Lower ``print`` to one typed ``printf`` call."""
    from .expressions import lower_expr
    from .stringable import has_to_string, to_string_call

    if not args:
        return IRCall(callee="printf", args=[IRLiteral(text='"\\n"')])

    formats = []
    ir_args = []
    for arg in args:
        ir_arg = lower_expr(gen, arg)
        arg_type = gen.analyzed.node_types.get(id(arg))
        fmt = format_spec_for_type(arg_type)

        if has_to_string(gen.analyzed, arg_type):
            ir_arg = to_string_call(gen, arg_type, ir_arg)
            fmt = "%s"

        if arg_type is None:
            if isinstance(arg, (FStringLiteral, StringLiteral)):
                fmt = "%s"
            elif isinstance(arg, CallExpr):
                callee = arg.callee
                if getattr(callee, "name", None) in ("toString", "str"):
                    fmt = "%s"
                if isinstance(callee, FieldAccessExpr) and callee.field in _STRING_METHODS:
                    fmt = "%s"

        if arg_type and arg_type.base == "bool":
            ir_arg = IRTernary(
                condition=ir_arg,
                true_expr=IRLiteral(text='"true"'),
                false_expr=IRLiteral(text='"false"'),
            )
            fmt = "%s"

        formats.append(fmt)
        ir_args.append(ir_arg)

    format_string = " ".join(formats) + "\\n"
    return IRCall(
        callee="printf",
        args=[IRLiteral(text=f'"{format_string}"'), *ir_args],
    )


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
    gen: IRGenerator,
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
