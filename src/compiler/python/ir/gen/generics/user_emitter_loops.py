"""Lexically scoped C-for and range lowering for generic methods."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRExprStmt,
    IRFor,
    IRLiteral,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
)
from .user_emitter_bindings import (
    declare_source_binding,
    pop_source_binding_scope,
    push_source_binding_scope,
)


def lower_generic_cfor(emitter, statement) -> IRBlock:
    """Lower a C-style loop inside its complete lexical ownership scope."""
    from ....ast_nodes import ForInitExpr, ForInitVar
    from .user_callable_provenance import (
        join_callable_flows,
        lower_isolated_callable_flow,
        snapshot_callable_flow,
    )
    from .user_emitter_scope_frames import (
        complete_generic_scope,
        enter_generic_scope,
        leave_generic_scope,
    )

    frame = enter_generic_scope(emitter)
    try:
        prefix = []
        init_node = None
        if statement.init:
            if isinstance(statement.init, ForInitVar):
                # A header declaration cannot be referenced after the C loop.
                # Lift it into this structured block so ARC and dynamic cleanup
                # both retain a live, declaration-specific slot until loop exit.
                prefix.extend(emitter._var_decl(statement.init.var_decl))
            elif isinstance(statement.init, ForInitExpr):
                init_node = IRExprStmt(expr=emitter._expr(statement.init.expression))
        condition = emitter._expr(statement.condition) if statement.condition else None
        body = emitter._loop_stmts(statement.body.statements)
        update = None
        if statement.update:
            before_update = snapshot_callable_flow(emitter)
            update, update_flow = lower_isolated_callable_flow(
                emitter,
                lambda: emitter._expr(statement.update),
            )
            join_callable_flows(emitter, before_update, update_flow)
        prefix.append(
            IRFor(
                init=init_node,
                condition=condition,
                update=update,
                body=IRBlock(stmts=body),
            )
        )
        return IRBlock(stmts=complete_generic_scope(emitter, frame, prefix))
    finally:
        leave_generic_scope(emitter, frame)


def lower_generic_range_forin(emitter, statement) -> list:
    """Lower range operands before activating the loop-variable binding."""
    from ....ast_nodes import TypeExpr
    from ..errors import CodegenError
    from .user_callable_provenance import (
        begin_callable_scope,
        bind_generic_local_callable,
        finish_callable_scope,
    )

    arguments = statement.iterable.args
    if len(arguments) == 1:
        start = IRLiteral(text="0")
        end = emitter._expr(arguments[0])
        step = None
    elif len(arguments) == 2:
        start = emitter._expr(arguments[0])
        end = emitter._expr(arguments[1])
        step = None
    elif len(arguments) == 3:
        start = emitter._expr(arguments[0])
        end = emitter._expr(arguments[1])
        step = emitter._expr(arguments[2])
    else:
        raise CodegenError(f"range() expects 1 to 3 arguments, got {len(arguments)}")

    enclosing_callables = begin_callable_scope(emitter)
    outer_types = emitter._var_types.copy()
    push_source_binding_scope(emitter)
    try:
        loop_type = TypeExpr(base="int")
        c_name = declare_source_binding(emitter, statement.var_name)
        emitter._var_types[statement.var_name] = loop_type
        bind_generic_local_callable(
            emitter,
            statement.var_name,
            loop_type,
            None,
        )
        loop_var = IRVar(name=c_name)
        init = IRVarDecl(
            c_type=CType(text="int"),
            name=c_name,
            init=start,
        )
        if step is None:
            condition = IRBinOp(left=loop_var, op="<", right=end)
            update = IRUnaryOp(op="++", operand=loop_var, prefix=False)
        else:
            condition = IRTernary(
                condition=IRBinOp(
                    left=step,
                    op=">",
                    right=IRLiteral(text="0"),
                ),
                true_expr=IRBinOp(left=loop_var, op="<", right=end),
                false_expr=IRBinOp(left=loop_var, op=">", right=end),
            )
            update = IRBinOp(left=loop_var, op="+=", right=step)
        body = emitter._loop_stmts(statement.body.statements)
    finally:
        pop_source_binding_scope(emitter)
        emitter._var_types = outer_types
        finish_callable_scope(emitter, enclosing_callables)
    return [
        IRFor(
            init=init,
            condition=condition,
            update=update,
            body=IRBlock(stmts=body),
        )
    ]


__all__ = ["lower_generic_cfor", "lower_generic_range_forin"]
