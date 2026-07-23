"""Range and C-style loop lowering."""

from __future__ import annotations

from ...ast_nodes import CForStmt, ForInitExpr, ForInitVar
from ..nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRExprStmt,
    IRFor,
    IRLiteral,
    IRStmt,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)


def _lower_range_for(
    gen,
    var_name: str,
    args: list,
    body,
    type_renderer,
    default_arguments=None,
) -> list[IRStmt]:
    """Lower ``for x in range(...)`` to one structured C loop."""
    from .expressions import lower_expr
    from .statements import _lower_loop_body

    start = IRLiteral(text="0")
    end = IRLiteral(text="0")
    step = IRLiteral(text="1")
    if args:
        if len(args) == 1:
            end = lower_expr(
                gen,
                args[0],
                type_renderer,
                default_arguments,
            )
        else:
            start = lower_expr(
                gen,
                args[0],
                type_renderer,
                default_arguments,
            )
            end = lower_expr(
                gen,
                args[1],
                type_renderer,
                default_arguments,
            )
        if len(args) >= 3:
            step = lower_expr(
                gen,
                args[2],
                type_renderer,
                default_arguments,
            )
    gen.push_local_ownership_scope()
    from .callable_provenance import (
        begin_callable_scope,
        declare_callable_shadow,
        finish_callable_scope,
    )

    enclosing_callables = begin_callable_scope(gen)
    try:
        c_name = gen.declare_local_ownership(var_name)
        declare_callable_shadow(gen, var_name)
        body_block = _lower_loop_body(
            gen,
            body,
            type_renderer,
            default_arguments,
        )

        condition = IRBinOp(left=IRVar(name=c_name), op="<", right=end)
        update = IRUnaryOp(op="++", operand=IRVar(name=c_name), prefix=False)
        if len(args) >= 3:
            condition = IRTernary(
                condition=IRBinOp(left=step, op=">", right=IRLiteral(text="0")),
                true_expr=condition,
                false_expr=IRBinOp(left=IRVar(name=c_name), op=">", right=end),
            )
            update = IRBinOp(left=IRVar(name=c_name), op="+=", right=step)
        return [
            IRFor(
                init=IRVarDecl(c_type=CType(text="int"), name=c_name, init=start),
                condition=condition,
                update=update,
                body=body_block,
            )
        ]
    finally:
        finish_callable_scope(gen, enclosing_callables)
        gen.pop_local_ownership_scope()


def _lower_c_for(
    gen,
    node: CForStmt,
    type_renderer,
    default_arguments=None,
) -> IRStmt:
    """Lower a C-style loop with one exact lexical initializer lifetime."""
    from .callable_provenance import (
        begin_callable_scope,
        finish_callable_scope,
        join_callable_flows,
        lower_isolated_callable_flow,
        snapshot_callable_flow,
    )
    from .expressions import lower_expr
    from .statements import _lower_loop_body
    from .variables import _lower_var_decl

    enclosing = begin_callable_scope(gen)
    enclosing_closures = gen.context.callable_environments.copy()
    cleanup_marker = None
    managed_scope_active = False
    local_scope_active = False
    c_scope_active = False
    try:
        init_node = None
        prefix: list[IRStmt] = []
        if isinstance(node.init, ForInitVar):
            declaration = node.init.var_decl
            cleanup_marker = gen.push_cleanup_scope()
            gen.push_managed_scope()
            managed_scope_active = True
            gen.push_local_ownership_scope()
            local_scope_active = True
            gen._c_array_scopes.append({})
            c_scope_active = True
            # A declaration initializer can need retain, cleanup registration,
            # or Thread ownership statements that cannot live in a C for-clause.
            # Hoist the complete structured declaration into the loop's own
            # block rather than duplicating those ownership rules here.
            prefix.extend(
                _lower_var_decl(
                    gen,
                    declaration,
                    type_renderer,
                    default_arguments,
                )
            )
        elif isinstance(node.init, ForInitExpr):
            init_node = IRExprStmt(
                expr=lower_expr(
                    gen,
                    node.init.expression,
                    type_renderer,
                    default_arguments,
                )
            )

        condition = (
            lower_expr(
                gen,
                node.condition,
                type_renderer,
                default_arguments,
            )
            if node.condition
            else IRLiteral(text="1")
        )
        body = _lower_loop_body(
            gen,
            node.body,
            type_renderer,
            default_arguments,
        )
        update = None
        if node.update:
            before_update = snapshot_callable_flow(gen)
            update, update_flow = lower_isolated_callable_flow(
                gen,
                lambda: lower_expr(
                    gen,
                    node.update,
                    type_renderer,
                    default_arguments,
                ),
            )
            join_callable_flows(gen, before_update, update_flow)
        loop = IRFor(
            init=init_node,
            condition=condition,
            update=update,
            body=body,
        )
        if not managed_scope_active:
            return loop

        from ..completion import StatementSequence
        from .cleanup_scopes import cleanup_scope_entry, cleanup_scope_exit

        scoped_statements = [*prefix, loop]
        sequence = StatementSequence(scoped_statements)
        falls_through = sequence.may_fall_through()
        managed = gen.pop_managed_scope()
        managed_scope_active = False
        marker_active = gen.cleanup_scope_is_active(cleanup_marker)
        marker_referenced = falls_through or sequence.references_variable(cleanup_marker or "")
        if marker_active and marker_referenced:
            scoped_statements[:0] = cleanup_scope_entry(gen, cleanup_marker)
        if falls_through:
            scoped_statements.extend(gen.lifetime.release_scope(managed))
            if marker_active and marker_referenced:
                scoped_statements.extend(cleanup_scope_exit(gen, cleanup_marker))
        return IRBlock(stmts=scoped_statements)
    finally:
        if managed_scope_active:
            gen.pop_managed_scope()
        if c_scope_active:
            gen._c_array_scopes.pop()
        if local_scope_active:
            gen.pop_local_ownership_scope()
        if cleanup_marker is not None:
            gen.pop_cleanup_scope()
        gen.context.callable_environments = enclosing_closures
        finish_callable_scope(gen, enclosing)


__all__ = ["_lower_c_for", "_lower_range_for"]
