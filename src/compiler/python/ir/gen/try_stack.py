"""Structured IR primitives for generated setjmp try-stack control."""

from ..nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFieldAccess,
    IRIf,
    IRIndex,
    IRLiteral,
    IRSizeof,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)


def setjmp_success_condition():
    """Build ``setjmp(current_frame.env) == 0`` without rendered C."""
    frame = IRIndex(
        obj=IRVar(name="__btrc_try_stack"),
        index=IRVar(name="__btrc_try_top"),
    )
    return IRBinOp(
        left=IRCall(
            callee="setjmp",
            args=[IRFieldAccess(obj=frame, field="env", arrow=True)],
        ),
        op="==",
        right=IRLiteral(text="0"),
    )


def pop_try_frames(depth: int) -> list[IRExprStmt]:
    """Discard ``depth`` active generated try frames."""
    if depth <= 0:
        return []
    top = IRVar(name="__btrc_try_top")
    if depth == 1:
        expression = IRUnaryOp(op="--", operand=top, prefix=False)
    else:
        expression = IRBinOp(
            left=top,
            op="-=",
            right=IRLiteral(text=str(depth)),
        )
    return [IRExprStmt(expr=expression)]


def finally_state_declarations(error_name, pending_name=None):
    """Declare stable state for an exception crossing a finally body."""
    declarations = []
    if pending_name is not None:
        declarations.append(
            IRVarDecl(
                c_type=CType(text="bool"),
                name=pending_name,
                init=IRLiteral(text="false"),
            )
        )
    declarations.append(
        IRVarDecl(
            c_type=CType(text="char"),
            name=error_name,
            array_size=IRLiteral(text="1024"),
            init=IRLiteral(text='""'),
        )
    )
    return declarations


def capture_finally_error(error_name, pending_name=None):
    """Copy the active runtime error into a finally-only handler's state."""
    statements = []
    if pending_name is not None:
        statements.append(
            IRAssign(
                target=IRVar(name=pending_name),
                value=IRLiteral(text="true"),
            )
        )
    statements.append(
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_copy_error_message",
                args=[
                    IRCast(
                        target_type=CType(text="char*"),
                        expr=IRVar(name=error_name),
                    ),
                    IRSizeof(operand=IRVar(name=error_name)),
                    IRVar(name="__btrc_error_msg"),
                ],
                helper_ref="__btrc_copy_error_message",
            )
        )
    )
    return statements


def finally_error_message(error_name):
    """View volatile setjmp-preserved storage through a read-only C API."""
    return IRCast(
        target_type=CType(text="const char*"),
        expr=IRVar(name=error_name),
    )


def rethrow_finally_error(error_name, pending_name=None):
    """Build the structured rethrow after a single shared finally body."""
    rethrow = IRExprStmt(
        expr=IRCall(
            callee="__btrc_throw",
            args=[finally_error_message(error_name)],
            helper_ref="__btrc_throw",
        )
    )
    if pending_name is None:
        return rethrow
    return IRIf(
        condition=IRVar(name=pending_name),
        then_block=IRBlock(stmts=[rethrow]),
    )


__all__ = [
    "capture_finally_error",
    "finally_error_message",
    "finally_state_declarations",
    "pop_try_frames",
    "rethrow_finally_error",
    "setjmp_success_condition",
]
