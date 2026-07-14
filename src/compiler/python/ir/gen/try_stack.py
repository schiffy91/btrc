"""Structured IR primitives for generated setjmp try-stack control."""

from ..nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFieldAccess,
    IRIndex,
    IRLiteral,
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


def finally_state_declarations(pending_name, error_name):
    """Declare the state used to rethrow after a finally-only handler."""
    return [
        IRVarDecl(
            c_type=CType(text="bool"),
            name=pending_name,
            init=IRLiteral(text="false"),
        ),
        IRVarDecl(
            c_type=CType(text="char"),
            name=error_name,
            array_size=IRLiteral(text="1024"),
            init=IRLiteral(text='""'),
        ),
    ]


def capture_finally_error(pending_name, error_name):
    """Copy the active runtime error into a finally-only handler's state."""
    return [
        IRAssign(
            target=IRVar(name=pending_name),
            value=IRLiteral(text="true"),
        ),
        IRExprStmt(
            expr=IRCall(
                callee="strncpy",
                args=[
                    IRCast(
                        target_type=CType(text="char*"),
                        expr=IRVar(name=error_name),
                    ),
                    IRVar(name="__btrc_error_msg"),
                    IRLiteral(text="1023"),
                ],
            )
        ),
        IRAssign(
            target=IRIndex(
                obj=IRVar(name=error_name),
                index=IRLiteral(text="1023"),
            ),
            value=IRLiteral(text="'\\0'"),
        ),
    ]


def finally_error_message(error_name):
    """View volatile setjmp-preserved storage through a read-only C API."""
    return IRCast(
        target_type=CType(text="const char*"),
        expr=IRVar(name=error_name),
    )


__all__ = [
    "capture_finally_error",
    "finally_error_message",
    "finally_state_declarations",
    "pop_try_frames",
    "setjmp_success_condition",
]
