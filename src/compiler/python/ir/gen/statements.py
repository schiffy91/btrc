"""Statement lowering: AST stmt -> IRStmt.

Main dispatch (lower_block and lower_stmt).
Variable declarations live in variables.py; ARC scope-release logic
lives in arc.py; control-flow lowering lives in control_flow.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    Block,
    BreakStmt,
    CForStmt,
    ContinueStmt,
    DeleteStmt,
    DoWhileStmt,
    ExprStmt,
    ForInStmt,
    IfStmt,
    KeepStmt,
    ParallelForStmt,
    ReleaseStmt,
    ReturnStmt,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
    VarDeclStmt,
    WhileStmt,
)
from ..nodes import (
    IRBlock,
    IRBreak,
    IRContinue,
    IRDoWhile,
    IRExprStmt,
    IRStmt,
    IRWhile,
)
from .arc import (
    _emit_control_exit_release,
    _emit_scope_release,
    _lower_release,
)
from .cleanup_scopes import (
    cleanup_scope_entry,
    cleanup_scope_exit,
    control_cleanup_exit,
)
from .errors import unsupported_node
from .expressions import lower_expr
from .variables import _lower_var_decl

if TYPE_CHECKING:
    from .lowerer import IRLowerer
    from .types import CTypeRenderer


def lower_block(
    gen: IRLowerer,
    block: Block | None,
    *,
    iteration_bindings=(),
    local_bindings=(),
    callable_bindings=(),
    callable_abis=(),
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRBlock:
    """Lower a btrc Block to an IRBlock."""
    if block is None:
        return IRBlock()
    local_bindings = tuple(local_bindings)
    iteration_bindings = tuple(iteration_bindings)
    enclosing_closures = gen.context.callable_environments.copy()
    from .callable_provenance import (
        begin_callable_scope,
        bind_borrowed_callable,
        bind_callable_abi,
        declare_callable_shadow,
        finish_callable_scope,
    )

    enclosing_callables = begin_callable_scope(gen)
    marker = gen.push_cleanup_scope()
    gen.push_managed_scope()
    gen.push_local_ownership_scope()
    c_bindings = {name: False for name in local_bindings}
    c_bindings.update({binding.name: False for binding in iteration_bindings})
    gen._c_array_scopes.append(c_bindings)
    stmts = []
    try:
        for name in local_bindings:
            gen.declare_local_ownership(name)
            declare_callable_shadow(gen, name)
        for binding in callable_bindings:
            if isinstance(binding, tuple):
                name, type_expr = binding
            else:
                name, type_expr = binding.name, binding.type
            bind_borrowed_callable(gen, name, type_expr)
        for binding, return_abi in callable_abis:
            bind_callable_abi(gen, binding.name, binding.type, return_abi)
        if iteration_bindings:
            from .iteration_bindings import emit_iteration_bindings

            stmts.extend(emit_iteration_bindings(gen, iteration_bindings))
        for statement in block.statements:
            _emit_line_marker(gen, statement, stmts)
            stmts.extend(
                lower_stmt(
                    gen,
                    statement,
                    type_renderer,
                    default_arguments,
                )
            )
        from ..completion import (
            sequence_may_fall_through,
            sequence_references_variable,
        )

        falls_through = sequence_may_fall_through(stmts)
        managed = gen.pop_managed_scope()
        marker_active = gen.cleanup_scope_is_active(marker)
        marker_referenced = falls_through or sequence_references_variable(stmts, marker or "")
        if marker_active and marker_referenced:
            stmts[:0] = cleanup_scope_entry(gen, marker)
        if falls_through:
            stmts.extend(_emit_scope_release(managed, gen))
            if marker_active and marker_referenced:
                stmts.extend(cleanup_scope_exit(gen, marker))
    finally:
        gen._c_array_scopes.pop()
        gen.pop_local_ownership_scope()
        gen.pop_cleanup_scope()
        gen.context.callable_environments = enclosing_closures
        finish_callable_scope(gen, enclosing_callables)
    return IRBlock(stmts=stmts)


def _emit_line_marker(gen: IRLowerer, ast_stmt, out: list) -> None:
    """In --debug mode, prepend a ``#line`` marker mapping this statement back to
    its .btrc source, so the compiled binary's DWARF points at btrc source."""
    if not (gen.debug and gen.line_map):
        return
    line = getattr(ast_stmt, "line", 0)
    if not line:
        return
    mapped = gen.line_map(line)
    if not mapped:
        return
    from ..nodes import IRLineMarker

    out.append(IRLineMarker(file=mapped[0], line=mapped[1]))


def lower_stmt(
    gen: IRLowerer,
    node,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> list[IRStmt]:
    """Lower a single AST statement to one or more IRStmts."""
    from .control_flow import (
        _lower_c_for,
        _lower_delete,
        _lower_for_in,
        _lower_if,
        _lower_switch,
        _lower_throw,
        _lower_try_catch,
    )

    if isinstance(node, VarDeclStmt):
        return _lower_var_decl(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, ReturnStmt):
        from .gpu_cpu_fallback import lower_gpu_cpu_item_return

        gpu_return = lower_gpu_cpu_item_return(
            gen,
            node,
            type_renderer,
            default_arguments,
        )
        if gpu_return is not None:
            return gpu_return
        from .arc_returns import lower_return

        return lower_return(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, IfStmt):
        return [
            _lower_if(
                gen,
                node,
                type_renderer,
                default_arguments,
            )
        ]

    if isinstance(node, WhileStmt):
        return [
            IRWhile(
                condition=lower_expr(
                    gen,
                    node.condition,
                    type_renderer,
                    default_arguments,
                ),
                body=_lower_loop_body(
                    gen,
                    node.body,
                    type_renderer,
                    default_arguments,
                ),
            )
        ]

    if isinstance(node, DoWhileStmt):
        return [
            IRDoWhile(
                body=_lower_loop_body(
                    gen,
                    node.body,
                    type_renderer,
                    default_arguments,
                    may_skip=False,
                ),
                condition=lower_expr(
                    gen,
                    node.condition,
                    type_renderer,
                    default_arguments,
                ),
            )
        ]

    if isinstance(node, ForInStmt):
        return _lower_for_in(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, CForStmt):
        return [
            _lower_c_for(
                gen,
                node,
                type_renderer,
                default_arguments,
            )
        ]

    if isinstance(node, ParallelForStmt):
        # Parallel for -> regular for (no GPU support yet)
        return _lower_for_in(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, SwitchStmt):
        return [
            _lower_switch(
                gen,
                node,
                type_renderer,
                default_arguments,
            )
        ]

    if isinstance(node, BreakStmt):
        from .arc_returns import _emit_try_pop
        from .callable_loop_flow import record_callable_loop_exit

        record_callable_loop_exit(gen, "break")
        try_pop = _emit_try_pop(gen, gen.exited_try_depth({"loop", "switch"}))
        return (
            _emit_control_exit_release(gen, {"loop", "switch"})
            + control_cleanup_exit(gen, {"loop", "switch"})
            + try_pop
            + [IRBreak()]
        )

    if isinstance(node, ContinueStmt):
        from .arc_returns import _emit_try_pop
        from .callable_loop_flow import record_callable_loop_exit

        record_callable_loop_exit(gen, "continue")
        try_pop = _emit_try_pop(gen, gen.exited_try_depth({"loop"}))
        return (
            _emit_control_exit_release(gen, {"loop"}) + control_cleanup_exit(gen, {"loop"}) + try_pop + [IRContinue()]
        )

    if isinstance(node, ExprStmt):
        from .expression_statements import lower_expression_statement

        return lower_expression_statement(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, DeleteStmt):
        return _lower_delete(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, TryCatchStmt):
        return _lower_try_catch(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, ThrowStmt):
        return _lower_throw(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    if isinstance(node, Block):
        # Bare block statement: { ... }
        return [
            lower_block(
                gen,
                node,
                type_renderer=type_renderer,
                default_arguments=default_arguments,
            )
        ]

    if isinstance(node, KeepStmt):
        # Nullable ownership values make keep a guarded retain.
        expr = lower_expr(
            gen,
            node.expr,
            type_renderer,
            default_arguments,
        )
        from .arc_ops import retain_if_present

        return [IRExprStmt(expr=retain_if_present(gen, expr))]

    if isinstance(node, ReleaseStmt):
        # release expr -> if (--expr->__rc <= 0) destroy(expr); expr = NULL;
        return _lower_release(gen, node, type_renderer)

    raise unsupported_node("statement", node)


def _lower_loop_body(
    gen: IRLowerer,
    body: Block | None,
    type_renderer: CTypeRenderer,
    default_arguments=None,
    *,
    iteration_bindings=(),
    local_bindings=(),
    may_skip: bool = True,
) -> IRBlock:
    from .callable_loop_flow import lower_loop_body

    return lower_loop_body(
        gen,
        body,
        lower_block=lower_block,
        iteration_bindings=iteration_bindings,
        local_bindings=local_bindings,
        may_skip=may_skip,
        type_renderer=type_renderer,
        default_arguments=default_arguments,
    )
