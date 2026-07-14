"""Exception lowering for monomorphized generic method bodies."""

from __future__ import annotations

from ...nodes import (
    IRBlock,
    IRCall,
    IRExprStmt,
    IRIf,
    IRVar,
    IRVarDecl,
)
from ..try_stack import (
    capture_finally_error,
    finally_state_declarations,
    pop_try_frames,
    setjmp_success_condition,
)
from .user_emitter_scopes import pop_control_context, push_control_context


class _UserGenericExceptionMixin:
    """Structured try/throw lowering shared by generic class methods."""

    def _throw_stmt(self, statement):
        if self._gen:
            self._gen.require_runtime_include("setjmp.h")
            self._gen.use_helper("__btrc_throw")
        return [
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_throw",
                    args=[self._expr(statement.expr)],
                    helper_ref="__btrc_throw",
                )
            )
        ]

    def _try_catch_stmt(self, statement):
        from ..errors import CodegenError

        if not self._gen:
            raise CodegenError("generic try/catch lowering requires a generator")
        self._gen.require_runtime_include("setjmp.h")
        self._gen.use_helper("__btrc_trycatch_globals")
        self._gen.use_helper("__btrc_push_try")
        self._gen.use_helper("__btrc_throw")
        self._trycatch_depth += 1
        try:
            return self._try_catch_inner(statement)
        finally:
            self._trycatch_depth -= 1

    def _try_catch_inner(self, statement):
        finally_only = statement.catch_block is None and statement.finally_block is not None
        pending_name = self._fresh_temp("__btrc_finally_pending") if finally_only else ""
        error_name = self._fresh_temp("__btrc_finally_error") if finally_only else ""
        result = [IRExprStmt(expr=IRCall(callee="__btrc_push_try", args=[], helper_ref="__btrc_push_try"))]

        self._try_depth += 1
        push_control_context(self, "try")
        try:
            try_stmts = self.emit_stmts(statement.try_block.statements)
        finally:
            pop_control_context(self)
            self._try_depth -= 1
        try_stmts.extend(pop_try_frames(1))
        try_block = IRBlock(stmts=try_stmts)

        if finally_only:
            result.extend(finally_state_declarations(pending_name, error_name))
            catch_block = IRBlock(stmts=capture_finally_error(pending_name, error_name))
        else:
            catch_bindings = []
            if statement.catch_var:
                from ....ast_nodes import TypeExpr
                from ..iteration_bindings import IterationBinding

                self._gen.use_helper("__btrc_strdup")
                self._gen.use_helper("__btrc_str_track")
                catch_bindings.append(
                    IterationBinding(
                        name=statement.catch_var,
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
                    ),
                )
            from .user_emitter_scopes import emit_scoped_stmts

            catch_stmts = emit_scoped_stmts(
                self,
                (statement.catch_block.statements if statement.catch_block is not None else ()),
                iteration_bindings=catch_bindings,
            )
            if statement.catch_var:
                declaration_index = next(
                    index
                    for index, node in enumerate(catch_stmts)
                    if isinstance(node, IRVarDecl) and node.name == statement.catch_var
                )
                catch_stmts.insert(
                    declaration_index + 1,
                    IRExprStmt(expr=IRVar(name=statement.catch_var)),
                )
            catch_block = IRBlock(stmts=catch_stmts)

        result.append(
            IRIf(
                condition=setjmp_success_condition(),
                then_block=try_block,
                else_block=catch_block,
            )
        )

        if statement.finally_block is not None:
            result.extend(self.emit_stmts(statement.finally_block.statements))
            if finally_only:
                result.append(
                    IRIf(
                        condition=IRVar(name=pending_name),
                        then_block=IRBlock(
                            stmts=[
                                IRExprStmt(
                                    expr=IRCall(
                                        callee="__btrc_throw",
                                        args=[IRVar(name=error_name)],
                                        helper_ref="__btrc_throw",
                                    )
                                )
                            ]
                        ),
                    )
                )
        return result
