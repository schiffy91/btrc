"""Structured full-call ownership sequencing shared by IR generators."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..nodes import (
    CType,
    IRBinOp,
    IRCast,
    IRCommaExpr,
    IRLiteral,
    IRStmtExpr,
    IRVar,
    IRVarDecl,
)
from .managed_values import (
    is_class_type,
    release_value,
    retain_value,
)


@dataclass(frozen=True)
class CallOperand:
    """One source operand evaluated before invoking a managed call."""

    node: object
    type_expr: object
    c_type: str
    keep: bool = False
    owned: bool = False
    transferred: bool = False


def sequence_call_boundary(
    gen,
    operands: list[CallOperand],
    *,
    lower_expr: Callable,
    build_call: Callable,
    result_c_type: str | None,
    result_type=None,
    fresh_temp: Callable[[str], str],
    cleanup_active: bool,
    record_decl: Callable[[IRVarDecl], None],
    promote_result: bool = False,
    activate_cleanup: Callable[[], None] | None = None,
):
    """Evaluate operands once, invoke, then release call-owned references."""
    declarations = []
    prefix = []
    suffix = []
    overrides = {}

    for operand in operands:
        declaration = _temporary(
            fresh_temp,
            record_decl,
            "__btrc_call_operand",
            operand.c_type,
        )
        declarations.append(declaration)
        value = IRVar(name=declaration.name)
        prefix.append(
            IRBinOp(
                left=value,
                op="=",
                right=lower_expr(operand.node),
            )
        )
        if operand.owned:
            _register_temporary(
                gen,
                value,
                operand.type_expr,
                declarations,
                prefix,
                fresh_temp,
                cleanup_active,
                "__btrc_call_operand_cleanup",
                activate_cleanup,
            )
        if operand.keep:
            retained_decl = _temporary(
                fresh_temp,
                record_decl,
                "__btrc_kept_operand",
                operand.c_type,
                IRLiteral(text="NULL"),
            )
            declarations.append(retained_decl)
            retained = IRVar(name=retained_decl.name)
            prefix.extend(
                [
                    retain_value(gen, value, operand.type_expr),
                    IRBinOp(left=retained, op="=", right=value),
                ]
            )
            _register_temporary(
                gen,
                retained,
                operand.type_expr,
                declarations,
                prefix,
                fresh_temp,
                cleanup_active,
                "__btrc_kept_operand_cleanup",
                activate_cleanup,
            )
            suffix.extend(_release_and_clear(gen, retained, operand.type_expr))
        if operand.owned:
            if operand.transferred:
                suffix.append(
                    IRBinOp(
                        left=value,
                        op="=",
                        right=IRLiteral(text="NULL"),
                    )
                )
            else:
                suffix.extend(_release_and_clear(gen, value, operand.type_expr))
        overrides[id(operand.node)] = value

    call = build_call(overrides)
    sequence = list(prefix)
    if result_c_type is not None and result_c_type != "void":
        result_decl = _temporary(
            fresh_temp,
            record_decl,
            "__btrc_call_result",
            result_c_type,
        )
        declarations.append(result_decl)
        result = IRVar(name=result_decl.name)
        sequence.append(IRBinOp(left=result, op="=", right=call))
        if promote_result:
            if result_type is None:
                raise ValueError("managed result promotion requires its semantic type")
            sequence.append(retain_value(gen, result, result_type))
        sequence.extend(suffix)
        sequence.append(result)
    else:
        sequence.append(call)
        sequence.extend(suffix)
        sequence.append(IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0")))
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


def _register_temporary(
    gen,
    value,
    type_expr,
    declarations,
    prefix,
    fresh_temp,
    cleanup_active,
    flag_prefix,
    activate_cleanup,
):
    from .temporary_cleanup import cleanup_registration

    cleanup_decls, cleanup_exprs = cleanup_registration(
        gen,
        value,
        type_expr,
        flag_prefix,
        active=cleanup_active,
        fresh_temp=fresh_temp,
        activate_cleanup=activate_cleanup,
    )
    declarations.extend(cleanup_decls)
    prefix.extend(cleanup_exprs)


def _release_and_clear(gen, value, type_expr):
    from .arc_ops import poll_release_batch

    expressions = [
        release_value(gen, value, type_expr),
        IRBinOp(left=value, op="=", right=IRLiteral(text="NULL")),
    ]
    flush = poll_release_batch(
        gen,
        types=[type_expr] if is_class_type(gen, type_expr) else [],
    )
    if flush is not None:
        expressions.append(flush)
    return expressions


def _temporary(
    fresh_temp,
    record_decl,
    prefix: str,
    c_type: str,
    init=None,
) -> IRVarDecl:
    declaration = IRVarDecl(
        c_type=CType(text=c_type),
        name=fresh_temp(prefix),
        init=init,
    )
    record_decl(declaration)
    return declaration


__all__ = ["CallOperand", "sequence_call_boundary"]
