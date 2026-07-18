"""Single-evaluation, ownership-safe f-string lowering."""

from __future__ import annotations

from ...ast_nodes import (
    CallExpr,
    FieldAccessExpr,
    FStringExpr,
    FStringLiteral,
    FStringText,
    StringLiteral,
    TypeExpr,
)
from ..nodes import (
    CType,
    IRBinOp,
    IRCall,
    IRCast,
    IRCommaExpr,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .call_boundary import CallOperand, sequence_call_boundary
from .prepared_values import prepare_value, prepared_value_pin_flags
from .printf_args import adapt_printf_arg
from .stringable import has_to_string
from .type_resolution import canonical_type
from .types import format_spec_for_type


def lower_fstring(gen, node: FStringLiteral):
    """Lower a normal f-string through the shared typed implementation."""
    from .expressions import lower_expr
    from .ownership import owns_result
    from .types import type_to_c

    return lower_typed_fstring(
        gen,
        node,
        lower_value=lambda value: lower_expr(gen, value),
        type_of=lambda value: gen.analyzed.node_types.get(id(value)),
        owns=lambda value: owns_result(gen, value),
        render_type=type_to_c,
        fresh_temp=gen.fresh_temp,
        cleanup_active=gen.exception_cleanup_active(),
        record_decl=gen._func_var_decls.append,
    )


def lower_typed_fstring(
    gen,
    node,
    *,
    lower_value,
    type_of,
    owns,
    render_type,
    fresh_temp,
    cleanup_active,
    record_decl,
    activate_cleanup=None,
):
    """Format interpolations once and consume any caller-owned arguments."""
    format_parts = []
    prepared_items = []
    argument_specs = []
    for part in node.parts:
        if isinstance(part, FStringText):
            format_parts.append(part.text.replace("%", "%%"))
            continue
        if not isinstance(part, FStringExpr):
            continue
        expression = part.expression
        source_type = canonical_type(
            type_of(expression),
            gen.analyzed.typedef_table,
        )
        target_type = TypeExpr(base="string") if has_to_string(gen.analyzed, source_type) else source_type
        prepared = prepare_value(
            gen,
            expression,
            target_type,
            lower_expr=lower_value,
            type_of=type_of,
            owns_result=owns,
            render_type=render_type,
            fresh_temp=fresh_temp,
            cleanup_active=cleanup_active,
            record_decl=record_decl,
            activate_cleanup=activate_cleanup,
        )
        spec = "%s" if prepared.converted else format_spec_for_type(source_type)
        if source_type is None:
            spec = _untracked_format(expression, spec)
        c_type = (
            render_type(prepared.effective_type)
            if prepared.effective_type is not None
            else "char*"
            if spec == "%s"
            else "int"
        )
        prepared_items.append((expression, prepared, c_type))
        argument_specs.append((expression, prepared.effective_type, spec, len(format_parts)))
        format_parts.append(spec)

    format_text = "".join(format_parts)
    if not prepared_items:
        return IRLiteral(text=f'"{format_text}"')

    prepared_pairs = [(expression, prepared) for expression, prepared, _c_type in prepared_items]
    pins = prepared_value_pin_flags(
        gen,
        prepared_pairs,
        type_of=type_of,
    )
    operands = [
        CallOperand(
            node=expression,
            type_expr=prepared.effective_type,
            c_type=c_type,
            pin=pins[index],
            owned=prepared.owned,
            lowered=prepared.value,
        )
        for index, (expression, prepared, c_type) in enumerate(prepared_items)
    ]

    gen.use_helper("__btrc_string_alloc")
    string_type = TypeExpr(base="string")

    def build(overrides):
        arguments = []
        formats = list(format_parts)
        for expression, value_type, spec, part_index in argument_specs:
            adapted = adapt_printf_arg(
                gen,
                overrides[id(expression)],
                value_type,
                spec,
            )
            formats[part_index] = adapted.format_spec
            arguments.append(adapted.value)
        fmt = IRLiteral(text=f'"{"".join(formats)}"')
        length = fresh_temp("__fstr_len")
        buffer = fresh_temp("__fstr_buf")
        declarations = [
            IRVarDecl(c_type=CType(text="int"), name=length),
            IRVarDecl(c_type=CType(text="char*"), name=buffer),
        ]
        for declaration in declarations:
            record_decl(declaration)
        size = IRBinOp(
            left=IRCast(
                target_type=CType(text="size_t"),
                expr=IRVar(name=length),
            ),
            op="+",
            right=IRLiteral(text="1"),
        )
        sequence = [
            IRBinOp(
                left=IRVar(name=length),
                op="=",
                right=IRCall(
                    callee="snprintf",
                    args=[IRLiteral(text="NULL"), IRLiteral(text="0"), fmt, *arguments],
                ),
            ),
            IRBinOp(
                left=IRVar(name=buffer),
                op="=",
                right=IRCall(
                    callee="__btrc_string_alloc",
                    args=[IRVar(name=length)],
                    helper_ref="__btrc_string_alloc",
                ),
            ),
            IRCall(
                callee="snprintf",
                args=[IRVar(name=buffer), size, fmt, *arguments],
            ),
            IRVar(name=buffer),
        ]
        return IRStmtExpr(
            stmts=declarations,
            result=IRCommaExpr(expressions=sequence),
        )

    return sequence_call_boundary(
        gen,
        operands,
        lower_expr=lower_value,
        build_call=build,
        result_c_type="char*",
        result_type=string_type,
        fresh_temp=fresh_temp,
        cleanup_active=cleanup_active,
        record_decl=record_decl,
        activate_cleanup=activate_cleanup,
        result_owned=True,
    )


def _untracked_format(expression, fallback):
    if isinstance(expression, (FStringLiteral, StringLiteral)):
        return "%s"
    if isinstance(expression, CallExpr) and isinstance(
        expression.callee,
        FieldAccessExpr,
    ):
        if expression.callee.field in {
            "capitalize",
            "join",
            "repeat",
            "replace",
            "reverse",
            "split",
            "str",
            "substring",
            "toLower",
            "toString",
            "toUpper",
            "trim",
        }:
            return "%s"
    return fallback or "%d"


__all__ = ["lower_fstring", "lower_typed_fstring"]
