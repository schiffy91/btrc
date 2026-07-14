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
    CType,
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCase,
    IRDeref,
    IRExprStmt,
    IRIf,
    IRLiteral,
    IRStmt,
    IRSwitch,
    IRVar,
    IRVarDecl,
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
    """Lower delete expr → destroy or free, then set the slot to null."""
    from .managed_local import mark_borrowed_cycle_seeds

    mark_borrowed_cycle_seeds(gen._managed_vars_stack)
    obj = _lower_expr(gen, node.expr)
    obj_type = gen.analyzed.node_types.get(id(node.expr))
    from ..c_types import qualify_volatile_object
    from .types import type_to_c

    value_c = type_to_c(obj_type)
    slot_name = gen.fresh_temp("__btrc_delete_slot")
    value_name = gen.fresh_temp("__btrc_delete_value")
    slot_decl = IRVarDecl(
        c_type=CType(text=f"{qualify_volatile_object(value_c, True)}*"),
        name=slot_name,
        init=IRAddressOf(expr=obj),
    )
    value_decl = IRVarDecl(
        c_type=CType(text=value_c),
        name=value_name,
        init=IRDeref(expr=IRVar(name=slot_name)),
    )
    gen._func_var_decls.extend((slot_decl, value_decl))
    slot = IRDeref(expr=IRVar(name=slot_name))
    value = IRVar(name=value_name)
    from .managed_values import is_class_type, is_string_type, release_value

    if is_class_type(gen, obj_type):
        from .arc_ops import arc_type_descriptor

        helper = "__btrc_arc_destroy"
        gen.use_helper(helper)
        stmts = [
            IRExprStmt(
                expr=IRCall(
                    callee=helper,
                    helper_ref=helper,
                    args=[value, arc_type_descriptor(gen, obj_type)],
                )
            )
        ]
    elif is_string_type(gen, obj_type):
        stmts = [IRExprStmt(expr=release_value(gen, value, obj_type))]
    else:
        # Non-class: just free
        stmts = [IRExprStmt(expr=IRCall(callee="free", args=[value]))]
    destroy = IRIf(
        condition=IRBinOp(left=value, op="!=", right=IRLiteral(text="NULL")),
        then_block=IRBlock(stmts=stmts),
    )
    # Clear the exact slot evaluated above so side-effectful lvalues run once.
    return [slot_decl, value_decl, destroy, IRAssign(target=slot, value=IRLiteral(text="NULL"))]


def _lower_expr(gen, node):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr

    return lower_expr(gen, node)
