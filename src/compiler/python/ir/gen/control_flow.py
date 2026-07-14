"""Control flow statement lowering: if, switch, delete, try/catch, throw."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    DeleteStmt,
    ElseBlock,
    ElseIf,
    IfStmt,
    SwitchStmt,
)
from ..nodes import (
    IRBlock,
    IRCase,
    IRIf,
    IRStmt,
    IRSwitch,
)

if TYPE_CHECKING:
    from .generator import IRGenerator

# Re-export iteration lowering so statements.py can import from one place
from .iterations import _lower_c_for, _lower_for_in, _lower_range_for  # noqa: F401
from .try_control import _lower_throw, _lower_try_catch  # noqa: F401


def _lower_if(gen: IRGenerator, node: IfStmt) -> IRIf:
    from .callable_provenance import (
        join_callable_flows,
        lower_isolated_callable_flow,
        snapshot_callable_flow,
    )
    from .statements import lower_block

    cond = _lower_expr(gen, node.condition)
    incoming = snapshot_callable_flow(gen)
    then, then_flow = lower_isolated_callable_flow(
        gen,
        lambda: lower_block(gen, node.then_block),
    )
    else_block = None
    else_flow = incoming
    if node.else_block:
        if isinstance(node.else_block, ElseBlock):
            else_block, else_flow = lower_isolated_callable_flow(
                gen,
                lambda: lower_block(gen, node.else_block.body),
            )
        elif isinstance(node.else_block, ElseIf):
            # Chain: else if → IRIf inside an else block
            inner, else_flow = lower_isolated_callable_flow(
                gen,
                lambda: _lower_if(gen, node.else_block.if_stmt),
            )
            else_block = IRBlock(stmts=[inner])
    join_callable_flows(gen, then_flow, else_flow)
    return IRIf(condition=cond, then_block=then, else_block=else_block)


def _lower_switch(gen: IRGenerator, node: SwitchStmt) -> IRSwitch:
    from .arc import _emit_scope_release
    from .callable_provenance import (
        begin_callable_scope,
        finish_callable_scope,
        join_callable_flows,
        lower_isolated_callable_flow,
        restore_callable_flow,
        snapshot_callable_flow,
    )
    from .statements import lower_stmt

    val = _lower_expr(gen, node.value)
    incoming = snapshot_callable_flow(gen)
    cases = []
    case_flows = []
    fallthrough_flow = None
    gen.push_control_context("switch")
    try:
        for c in node.cases:
            case_val = _lower_expr(gen, c.value) if c.value else None

            restore_callable_flow(gen, incoming)
            if fallthrough_flow is not None:
                join_callable_flows(gen, incoming, fallthrough_flow)

            def lower_case(case=c, value=case_val):
                enclosing = begin_callable_scope(gen)
                case_stmts = []
                gen.push_managed_scope()
                try:
                    for statement in case.body:
                        case_stmts.extend(lower_stmt(gen, statement))
                except Exception:
                    gen.pop_managed_scope()
                    raise
                finally:
                    finish_callable_scope(gen, enclosing)
                from ..completion import sequence_may_fall_through

                falls_through = sequence_may_fall_through(case_stmts)
                managed = gen.pop_managed_scope()
                if falls_through:
                    case_stmts.extend(_emit_scope_release(managed, gen))
                return IRCase(value=value, body=case_stmts), falls_through

            lowered_result, case_flow = lower_isolated_callable_flow(gen, lower_case)
            lowered_case, falls_through = lowered_result
            cases.append(lowered_case)
            case_flows.append(case_flow)
            fallthrough_flow = case_flow if falls_through else None
    finally:
        gen.pop_control_context()
    if not any(case.value is None for case in node.cases):
        case_flows.append(incoming)
    join_callable_flows(gen, *case_flows)
    return IRSwitch(value=val, cases=cases)


def _lower_delete(gen: IRGenerator, node: DeleteStmt) -> list[IRStmt]:
    """Lower delete through the shared take-clear destruction boundary."""
    from .managed_local import mark_borrowed_cycle_seeds
    from .manual_destruction import lower_taken_delete
    from .persistent_slots import stabilize_persistent_slot

    mark_borrowed_cycle_seeds(gen._managed_vars_stack)
    target = _lower_expr(gen, node.expr)
    obj_type = gen.analyzed.node_types.get(id(node.expr))
    target, edge_owner, owner_decls = stabilize_persistent_slot(
        gen,
        node.expr,
        target,
        prefix="__btrc_delete_owner",
    )
    return [
        *owner_decls,
        *lower_taken_delete(
            gen,
            target,
            obj_type,
            edge_owner=edge_owner,
        ),
    ]


def _lower_expr(gen, node):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr

    return lower_expr(gen, node)
