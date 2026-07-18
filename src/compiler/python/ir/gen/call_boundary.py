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
from .call_boundary_cleanup import (
    register_temporary as _register_temporary,
)
from .call_boundary_cleanup import (
    release_and_clear as _release_and_clear,
)
from .call_boundary_cleanup import (
    temporary as _temporary,
)
from .managed_values import is_managed_type, retain_value


@dataclass(frozen=True)
class CallOperand:
    """One source operand evaluated before invoking a managed call."""

    node: object
    type_expr: object
    c_type: str
    keep: bool = False
    pin: bool = False
    owned: bool = False
    transferred: bool = False
    lowered: object | None = None


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
    result_owned: bool = False,
):
    """Evaluate operands once, invoke, then release call-owned references."""
    declarations = []
    prefix = []
    handoffs = []
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
                right=operand.lowered if operand.lowered is not None else lower_expr(operand.node),
            )
        )
        if operand.owned:
            _register_temporary(
                gen,
                declaration,
                operand.type_expr,
                declarations,
                prefix,
                fresh_temp,
                cleanup_active,
                "__btrc_call_operand_cleanup",
                activate_cleanup,
            )
        if operand.keep or operand.pin:
            retained_decl = _temporary(
                fresh_temp,
                record_decl,
                "__btrc_kept_operand",
                operand.c_type,
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
                retained_decl,
                operand.type_expr,
                declarations,
                prefix,
                fresh_temp,
                cleanup_active,
                "__btrc_kept_operand_cleanup",
                activate_cleanup,
            )
            suffix.extend(
                _release_and_clear(
                    gen,
                    retained,
                    operand.type_expr,
                    declarations,
                    fresh_temp,
                    record_decl,
                    operand.c_type,
                )
            )
        call_value = value
        if operand.owned:
            if operand.transferred:
                handoff_decl = _temporary(
                    fresh_temp,
                    record_decl,
                    "__btrc_transferred_operand",
                    operand.c_type,
                )
                declarations.append(handoff_decl)
                call_value = IRVar(name=handoff_decl.name)
                handoffs.extend(
                    [
                        IRBinOp(left=call_value, op="=", right=value),
                        IRBinOp(
                            left=value,
                            op="=",
                            right=IRLiteral(text="NULL"),
                        ),
                    ]
                )
            else:
                suffix.extend(
                    _release_and_clear(
                        gen,
                        value,
                        operand.type_expr,
                        declarations,
                        fresh_temp,
                        record_decl,
                        operand.c_type,
                    )
                )
        overrides[id(operand.node)] = call_value

    call = build_call(overrides)
    sequence = [*prefix, *handoffs]
    if result_c_type is not None and result_c_type != "void":
        result_decl = _temporary(
            fresh_temp,
            record_decl,
            "__btrc_call_result",
            result_c_type,
        )
        # GCC's -Wclobbered tracks this synthesized result across a later
        # setjmp even when the declaration's lexical block has ended (notably
        # Terminal.promptPassword). Stable storage metadata is harmless for
        # ordinary calls and keeps strict -Werror builds deterministic.
        result_decl.is_volatile = True
        declarations.append(result_decl)
        result = IRVar(name=result_decl.name)
        sequence.append(IRBinOp(left=result, op="=", right=call))
        if promote_result:
            if result_type is None:
                raise ValueError("managed result promotion requires its semantic type")
            sequence.append(retain_value(gen, result, result_type))
        protect_result = bool(
            cleanup_active
            and result_type is not None
            and (result_owned or promote_result)
            and is_managed_type(gen, result_type)
        )
        if protect_result:
            # Operand cleanup runs after the call and may throw. Register the
            # newly owned result before that suffix, then transfer it through a
            # cleared handoff slot once cleanup succeeds.
            _register_temporary(
                gen,
                result_decl,
                result_type,
                declarations,
                sequence,
                fresh_temp,
                cleanup_active,
                "__btrc_call_result_cleanup",
                activate_cleanup,
            )
            handoff_decl = _temporary(
                fresh_temp,
                record_decl,
                "__btrc_call_result_handoff",
                result_c_type,
            )
            declarations.append(handoff_decl)
            handoff = IRVar(name=handoff_decl.name)
        sequence.extend(suffix)
        if protect_result:
            sequence.extend(
                [
                    IRBinOp(left=handoff, op="=", right=result),
                    IRBinOp(
                        left=result,
                        op="=",
                        right=IRLiteral(text="NULL"),
                    ),
                    handoff,
                ]
            )
        else:
            sequence.append(result)
    else:
        sequence.append(call)
        sequence.extend(suffix)
        sequence.append(IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0")))
    return IRStmtExpr(
        stmts=declarations,
        result=IRCommaExpr(expressions=sequence),
    )


__all__ = ["CallOperand", "sequence_call_boundary"]
