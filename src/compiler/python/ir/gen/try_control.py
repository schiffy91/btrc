"""Try/catch/finally and throw lowering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import ThrowStmt, TryCatchStmt
from ...control_termination import block_must_terminate
from ..nodes import IRBlock, IRCall, IRExprStmt, IRIf, IRStmt, IRVar
from .try_stack import (
    capture_finally_error,
    finally_state_declarations,
    pop_try_frames,
    rethrow_finally_error,
    setjmp_success_condition,
)

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def _require_setjmp(gen: IRLowerer):
    """Register the header even for try/throw nested inside lifted bodies."""
    gen.require_runtime_include("setjmp.h")


def _lower_try_catch(gen: IRLowerer, node: TryCatchStmt) -> list[IRStmt]:
    """Lower try/catch to setjmp/longjmp boilerplate."""
    gen.in_trycatch_depth += 1
    try:
        return _lower_try_catch_inner(gen, node)
    finally:
        gen.in_trycatch_depth -= 1


def _lower_try_catch_inner(gen: IRLowerer, node: TryCatchStmt) -> list[IRStmt]:
    from .callable_provenance import (
        begin_exceptional_callable_capture,
        finish_exceptional_callable_capture,
        join_callable_flows,
        lower_isolated_callable_flow,
        snapshot_callable_flow,
    )
    from .statements import lower_block

    _require_setjmp(gen)
    gen.helpers.use("__btrc_trycatch_globals")
    gen.helpers.use("__btrc_push_try")
    gen.helpers.use("__btrc_throw")
    stmts: list[IRStmt] = []
    finally_only = node.catch_block is None and node.finally_block is not None
    try_terminates = finally_only and block_must_terminate(node.try_block)
    pending_name = gen.fresh_temp("__btrc_finally_pending") if finally_only and not try_terminates else None
    error_name = gen.fresh_temp("__btrc_finally_error") if finally_only else ""
    stmts.append(
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_push_try",
                args=[],
                helper_ref="__btrc_push_try",
            )
        )
    )

    gen.in_try_depth += 1
    gen.push_control_context("try")
    exceptional_capture = begin_exceptional_callable_capture(gen)
    try:
        try_body, try_flow = lower_isolated_callable_flow(
            gen,
            lambda: lower_block(gen, node.try_block),
        )
    finally:
        exceptional_flows = finish_exceptional_callable_capture(
            gen,
            exceptional_capture,
        )
        gen.pop_control_context()
        gen.in_try_depth -= 1
    if gen.helpers.roots & {
        "__btrc_register_cleanup",
        "__btrc_register_direct_cleanup",
    }:
        gen.helpers.use("__btrc_discard_cleanups")
        try_body.stmts.append(
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_discard_cleanups",
                    args=[IRVar(name="__btrc_try_top")],
                    helper_ref="__btrc_discard_cleanups",
                )
            )
        )
    try_body.stmts.extend(pop_try_frames(1))
    # With no checked-throws effect system, any callback state reached while
    # lowering the try is conservatively visible to its exceptional edge.
    join_callable_flows(gen, *exceptional_flows, try_flow)
    exceptional_entry = snapshot_callable_flow(gen)
    if finally_only:
        stmts.extend(finally_state_declarations(error_name, pending_name))
        catch_body = IRBlock(stmts=capture_finally_error(error_name, pending_name))
        catch_flow = exceptional_entry
    else:
        catch_bindings = _catch_bindings(gen, node)
        catch_body, catch_flow = lower_isolated_callable_flow(
            gen,
            lambda: lower_block(
                gen,
                node.catch_block,
                iteration_bindings=catch_bindings,
            ),
        )

    join_callable_flows(gen, try_flow, catch_flow)
    stmts.append(
        IRIf(
            condition=setjmp_success_condition(),
            then_block=try_body,
            else_block=catch_body,
        )
    )
    if node.finally_block:
        stmts.extend(lower_block(gen, node.finally_block).stmts)
        if finally_only:
            stmts.append(rethrow_finally_error(error_name, pending_name))
    return stmts


def _catch_bindings(gen, node):
    if not node.catch_var:
        return []
    from ...ast_nodes import TypeExpr
    from .iteration_bindings import IterationBinding

    gen.helpers.use("__btrc_strdup")
    gen.helpers.use("__btrc_str_track")
    return [
        IterationBinding(
            name=node.catch_var,
            c_type="char*",
            type_expr=TypeExpr(base="string"),
            value=IRCall(
                callee="__btrc_str_track",
                args=[
                    IRCall(
                        callee="__btrc_strdup",
                        args=[IRVar(name="__btrc_error_msg")],
                        helper_ref="__btrc_strdup",
                    )
                ],
                helper_ref="__btrc_str_track",
            ),
            owned=True,
        )
    ]


def _lower_throw(gen: IRLowerer, node: ThrowStmt) -> list[IRStmt]:
    _require_setjmp(gen)
    gen.helpers.use("__btrc_throw")
    from .expressions import lower_expr

    expr = lower_expr(gen, node.expr)
    return [
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_throw",
                args=[expr],
                helper_ref="__btrc_throw",
            )
        )
    ]


__all__ = ["_lower_throw", "_lower_try_catch"]
