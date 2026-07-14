"""Control flow statement lowering: if, switch, delete, try/catch, throw."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    DeleteStmt,
    ElseBlock,
    ElseIf,
    IfStmt,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
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
from .try_stack import (
    capture_finally_error,
    finally_error_message,
    finally_state_declarations,
    pop_try_frames,
    setjmp_success_condition,
)

if TYPE_CHECKING:
    from .generator import IRGenerator

# Re-export iteration lowering so statements.py can import from one place
from .iterations import _lower_c_for, _lower_for_in, _lower_range_for  # noqa: F401


def _lower_if(gen: IRGenerator, node: IfStmt) -> IRIf:
    from .statements import lower_block

    cond = _lower_expr(gen, node.condition)
    then = lower_block(gen, node.then_block)
    else_block = None
    if node.else_block:
        if isinstance(node.else_block, ElseBlock):
            else_block = lower_block(gen, node.else_block.body)
        elif isinstance(node.else_block, ElseIf):
            # Chain: else if → IRIf inside an else block
            inner = _lower_if(gen, node.else_block.if_stmt)
            else_block = IRBlock(stmts=[inner])
    return IRIf(condition=cond, then_block=then, else_block=else_block)


def _lower_switch(gen: IRGenerator, node: SwitchStmt) -> IRSwitch:
    from .arc import _emit_scope_release
    from .statements import lower_stmt

    val = _lower_expr(gen, node.value)
    cases = []
    gen.push_control_context("switch")
    try:
        for c in node.cases:
            case_val = _lower_expr(gen, c.value) if c.value else None
            case_stmts = []
            gen.push_managed_scope()
            try:
                for s in c.body:
                    case_stmts.extend(lower_stmt(gen, s))
            except Exception:
                gen.pop_managed_scope()
                raise
            from ..completion import sequence_may_fall_through

            falls_through = sequence_may_fall_through(case_stmts)
            managed = gen.pop_managed_scope()
            if falls_through:
                case_stmts.extend(_emit_scope_release(managed, gen))
            cases.append(IRCase(value=case_val, body=case_stmts))
    finally:
        gen.pop_control_context()
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


def _require_setjmp(gen: IRGenerator):
    """Ensure <setjmp.h> is included.

    Registered at the lowering site so try/catch/throw anywhere — including
    inside lambda bodies, which the generator's declaration pre-scan does
    not reach — always pulls in the header.
    """
    gen.require_runtime_include("setjmp.h")


def _lower_try_catch(gen: IRGenerator, node: TryCatchStmt) -> list[IRStmt]:
    """Lower try/catch to setjmp/longjmp boilerplate."""
    # Mark that everything lowered for this construct (try body, catch, finally)
    # lives inside a try/catch, so class-pointer returns get laundered against
    # the gcc -O2 setjmp cross-branch miscompilation (see _lower_return).
    gen.in_trycatch_depth += 1
    try:
        return _lower_try_catch_inner(gen, node)
    finally:
        gen.in_trycatch_depth -= 1


def _lower_try_catch_inner(gen: IRGenerator, node: TryCatchStmt) -> list[IRStmt]:
    from .statements import lower_block

    _require_setjmp(gen)
    gen.use_helper("__btrc_trycatch_globals")
    gen.use_helper("__btrc_push_try")
    gen.use_helper("__btrc_throw")
    stmts: list[IRStmt] = []
    finally_only = node.catch_block is None and node.finally_block is not None
    pending_name = gen.fresh_temp("__btrc_finally_pending") if finally_only else ""
    error_name = gen.fresh_temp("__btrc_finally_error") if finally_only else ""

    stmts.append(IRExprStmt(expr=IRCall(callee="__btrc_push_try", args=[], helper_ref="__btrc_push_try")))

    # if (setjmp(...) == 0) { try block } else { catch block }
    gen.in_try_depth += 1
    gen.push_control_context("try")
    try:
        try_body = lower_block(gen, node.try_block)
    finally:
        gen.pop_control_context()
        gen.in_try_depth -= 1
    # Normal exit: discard cleanup registrations (scope release already freed them)
    # then decrement try level
    if gen._used_helpers & {
        "__btrc_register_cleanup",
        "__btrc_register_direct_cleanup",
    }:
        gen.use_helper("__btrc_discard_cleanups")
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
    if finally_only:
        stmts.extend(finally_state_declarations(pending_name, error_name))
        catch_body = IRBlock(stmts=capture_finally_error(pending_name, error_name))
    else:
        catch_bindings = []
        if node.catch_var:
            gen.use_helper("__btrc_strdup")
            gen.use_helper("__btrc_str_track")
            from ...ast_nodes import TypeExpr
            from .iteration_bindings import IterationBinding

            catch_bindings.append(
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
            )
        catch_body = lower_block(
            gen,
            node.catch_block,
            iteration_bindings=catch_bindings,
        )
        if node.catch_var:
            declaration_index = next(
                index
                for index, statement in enumerate(catch_body.stmts)
                if isinstance(statement, IRVarDecl) and statement.name == node.catch_var
            )
            catch_body.stmts.insert(
                declaration_index + 1,
                IRExprStmt(expr=IRVar(name=node.catch_var)),
            )

    stmts.append(
        IRIf(
            condition=setjmp_success_condition(),
            then_block=try_body,
            else_block=catch_body,
        )
    )

    if node.finally_block:
        finally_stmts = lower_block(gen, node.finally_block)
        stmts.extend(finally_stmts.stmts)
        if finally_only:
            stmts.append(
                IRIf(
                    condition=IRVar(name=pending_name),
                    then_block=IRBlock(
                        stmts=[
                            IRExprStmt(
                                expr=IRCall(
                                    callee="__btrc_throw",
                                    args=[finally_error_message(error_name)],
                                    helper_ref="__btrc_throw",
                                )
                            )
                        ]
                    ),
                )
            )

    return stmts


def _lower_throw(gen: IRGenerator, node: ThrowStmt) -> list[IRStmt]:
    _require_setjmp(gen)
    gen.use_helper("__btrc_throw")
    expr = _lower_expr(gen, node.expr)
    return [IRExprStmt(expr=IRCall(callee="__btrc_throw", args=[expr], helper_ref="__btrc_throw"))]


def _lower_expr(gen, node):
    """Convenience wrapper to avoid circular import at module level."""
    from .expressions import lower_expr

    return lower_expr(gen, node)
