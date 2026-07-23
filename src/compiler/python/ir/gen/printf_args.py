"""Portable adaptation of typed values passed through C printf varargs."""

from __future__ import annotations

from dataclasses import dataclass

from ...ast_nodes import TypeExpr
from ..nodes import CType, IRCall, IRCast, IRCommaExpr, IRExpr, IRLiteral, IRTernary
from .type_resolution import canonical_type
from .types import CTypeRenderer


@dataclass(frozen=True)
class PrintfArg:
    """A format fragment and the exact C expression it accepts."""

    format_spec: str
    value: IRExpr


def adapt_printf_arg(
    gen,
    value: IRExpr,
    value_type: TypeExpr | None,
    format_spec: str,
    type_renderer: CTypeRenderer,
) -> PrintfArg:
    """Make one printf argument match its format without duplicating effects.

    Function pointers cannot be converted to ``void*`` portably.  They render as
    an opaque token.  A direct print expression remains in a comma expression
    so it is evaluated exactly once.  F-string values have already been
    assigned to a temporary by their caller; reading that temporary in each
    formatting pass both preserves the evaluation contract and avoids an
    unused-but-set strict-C diagnostic.
    """
    resolved_type = canonical_type(value_type, gen.analyzed.typedef_table) if value_type is not None else None
    format_spec = type_renderer.format_spec(resolved_type) if resolved_type is not None else format_spec

    if (
        resolved_type is not None
        and resolved_type.base == "__fn_ptr"
        and resolved_type.pointer_depth == 0
        and not resolved_type.is_array
    ):
        token = IRLiteral(text='"<function>"')
        discarded = IRCast(target_type=CType(text="void"), expr=value)
        return PrintfArg(
            format_spec="%s",
            value=IRCommaExpr(expressions=[discarded, token]),
        )

    if (
        resolved_type is not None
        and resolved_type.base == "bool"
        and resolved_type.pointer_depth == 0
        and not resolved_type.is_array
    ):
        return PrintfArg(
            format_spec="%s",
            value=IRTernary(
                condition=value,
                true_expr=IRLiteral(text='"true"'),
                false_expr=IRLiteral(text='"false"'),
            ),
        )

    if resolved_type is not None and resolved_type.base == "__fn_ptr":
        return PrintfArg(
            format_spec="%p",
            value=IRCast(target_type=CType(text="void*"), expr=value),
        )

    if (
        resolved_type is not None
        and resolved_type.pointer_depth == 0
        and not resolved_type.is_array
        and resolved_type.base in gen.analyzed.enum_table
    ):
        # C may choose an unsigned compatible type for an enum.  The language
        # contract deliberately renders simple enums as integers, so convert
        # to the exact promoted type required by %d.
        return PrintfArg(
            format_spec="%d",
            value=IRCast(target_type=CType(text="int"), expr=value),
        )

    if (
        resolved_type is not None
        and resolved_type.pointer_depth == 0
        and not resolved_type.is_array
        and resolved_type.base in gen.analyzed.rich_enum_table
    ):
        return PrintfArg(
            format_spec="%s",
            value=IRCall(
                callee=f"{resolved_type.base}_toString",
                args=[value],
            ),
        )

    if _is_by_value_aggregate(gen, resolved_type):
        is_tuple = resolved_type.base == "Tuple" or resolved_type.base.startswith("(")
        token = '"<tuple>"' if is_tuple else '"<struct>"'
        return PrintfArg(
            format_spec="%s",
            value=IRCommaExpr(
                expressions=[
                    IRCast(target_type=CType(text="void"), expr=value),
                    IRLiteral(text=token),
                ]
            ),
        )

    if format_spec == "%s":
        gen.helpers.use("__btrc_string_or_empty")
        return PrintfArg(
            format_spec=format_spec,
            value=IRCall(
                callee="__btrc_string_or_empty",
                args=[value],
                helper_ref="__btrc_string_or_empty",
            ),
        )
    if format_spec == "%p":
        return PrintfArg(
            format_spec=format_spec,
            value=IRCast(target_type=CType(text="void*"), expr=value),
        )
    if format_spec == "%u":
        # Narrow unsigned integer types promote to ``int`` on the supported
        # C targets, while %u requires an ``unsigned int`` argument.  An
        # explicit cast makes the variadic boundary exact for byte/ushort and
        # is harmless when the source is already uint.
        return PrintfArg(
            format_spec=format_spec,
            value=IRCast(target_type=CType(text="unsigned int"), expr=value),
        )
    return PrintfArg(format_spec=format_spec, value=value)


def _is_by_value_aggregate(gen, value_type: TypeExpr | None) -> bool:
    if value_type is None or value_type.pointer_depth > 0 or value_type.is_array:
        return False
    if value_type.base == "Tuple" or value_type.base.startswith("("):
        return True
    struct_name = value_type.base.removeprefix("struct ")
    return struct_name in gen.analyzed.struct_table
