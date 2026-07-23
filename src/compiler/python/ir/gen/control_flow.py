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
    from .lowerer import IRLowerer
    from .types import CTypeRenderer

# Re-export iteration lowering so statements.py can import from one place
from .iterations import _lower_c_for, _lower_for_in, _lower_range_for  # noqa: F401
from .try_control import _lower_throw, _lower_try_catch  # noqa: F401


def _lower_if(
    gen: IRLowerer,
    node: IfStmt,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRIf:
    from .callable_provenance import (
        join_callable_flows,
        lower_isolated_callable_flow,
        snapshot_callable_flow,
    )
    from .statements import lower_block

    cond = _lower_expr(
        gen,
        node.condition,
        type_renderer,
        default_arguments,
    )
    incoming = snapshot_callable_flow(gen)
    then, then_flow = lower_isolated_callable_flow(
        gen,
        lambda: lower_block(
            gen,
            node.then_block,
            type_renderer=type_renderer,
            default_arguments=default_arguments,
        ),
    )
    else_block = None
    else_flow = incoming
    if node.else_block:
        if isinstance(node.else_block, ElseBlock):
            else_block, else_flow = lower_isolated_callable_flow(
                gen,
                lambda: lower_block(
                    gen,
                    node.else_block.body,
                    type_renderer=type_renderer,
                    default_arguments=default_arguments,
                ),
            )
        elif isinstance(node.else_block, ElseIf):
            # Chain: else if → IRIf inside an else block
            inner, else_flow = lower_isolated_callable_flow(
                gen,
                lambda: _lower_if(
                    gen,
                    node.else_block.if_stmt,
                    type_renderer,
                    default_arguments,
                ),
            )
            else_block = IRBlock(stmts=[inner])
    join_callable_flows(gen, then_flow, else_flow)
    return IRIf(condition=cond, then_block=then, else_block=else_block)


def _lower_switch(
    gen: IRLowerer,
    node: SwitchStmt,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRSwitch:
    from .callable_provenance import (
        begin_callable_scope,
        finish_callable_scope,
        join_callable_flows,
        lower_isolated_callable_flow,
        restore_callable_flow,
        snapshot_callable_flow,
    )
    from .cleanup_scopes import cleanup_scope_entry, cleanup_scope_exit
    from .statements import lower_stmt

    val = _lower_expr(
        gen,
        node.value,
        type_renderer,
        default_arguments,
    )
    incoming = snapshot_callable_flow(gen)
    cases = []
    case_flows = []
    fallthrough_flow = None
    gen.push_control_context("switch")
    try:
        for c in node.cases:
            case_val = (
                _lower_expr(
                    gen,
                    c.value,
                    type_renderer,
                    default_arguments,
                )
                if c.value
                else None
            )

            restore_callable_flow(gen, incoming)
            if fallthrough_flow is not None:
                join_callable_flows(gen, incoming, fallthrough_flow)

            def lower_case(case=c, value=case_val):
                enclosing = begin_callable_scope(gen)
                case_stmts = []
                marker = gen.push_cleanup_scope()
                gen.push_managed_scope()
                gen.push_local_ownership_scope()
                gen._c_array_scopes.append({})
                managed_scope_active = True
                try:
                    for statement in case.body:
                        case_stmts.extend(
                            lower_stmt(
                                gen,
                                statement,
                                type_renderer,
                                default_arguments,
                            )
                        )
                    from ..completion import StatementSequence

                    sequence = StatementSequence(case_stmts)
                    falls_through = sequence.may_fall_through()
                    managed = gen.pop_managed_scope()
                    managed_scope_active = False
                    marker_active = gen.cleanup_scope_is_active(marker)
                    marker_referenced = falls_through or sequence.references_variable(marker or "")
                    if marker_active and marker_referenced:
                        case_stmts[:0] = cleanup_scope_entry(gen, marker)
                    if falls_through:
                        case_stmts.extend(gen.lifetime.release_scope(managed))
                        if marker_active and marker_referenced:
                            case_stmts.extend(cleanup_scope_exit(gen, marker))
                    return (
                        IRCase(
                            value=value,
                            body=case_stmts,
                            falls_through=falls_through,
                        ),
                        falls_through,
                    )
                finally:
                    if managed_scope_active:
                        gen.pop_managed_scope()
                    gen._c_array_scopes.pop()
                    gen.pop_local_ownership_scope()
                    gen.pop_cleanup_scope()
                    finish_callable_scope(gen, enclosing)

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


def _lower_delete(
    gen: IRLowerer,
    node: DeleteStmt,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> list[IRStmt]:
    """Lower delete through the shared take-clear destruction boundary."""
    from .manual_destruction import lower_taken_delete
    from .persistent_slots import stabilize_persistent_slot

    gen.mark_borrowed_cycle_seeds()
    target = _lower_expr(
        gen,
        node.expr,
        type_renderer,
        default_arguments,
    )
    obj_type = gen.analyzed.node_types.get(id(node.expr))
    target, edge_owner, owner_decls = stabilize_persistent_slot(
        gen,
        node.expr,
        target,
        render_type=type_renderer.render,
        prefix="__btrc_delete_owner",
    )
    return [
        *owner_decls,
        *lower_taken_delete(
            gen,
            target,
            obj_type,
            type_renderer,
            edge_owner=edge_owner,
        ),
    ]


def _lower_expr(
    gen,
    node,
    type_renderer,
    default_arguments=None,
):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr

    return lower_expr(
        gen,
        node,
        type_renderer,
        default_arguments,
    )
