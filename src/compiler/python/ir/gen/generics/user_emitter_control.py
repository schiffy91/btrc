"""Control-flow statement lowering for monomorphized generic methods."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRCase,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRIf,
    IRLiteral,
    IRSwitch,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)
from .user_emitter_exceptions import _UserGenericExceptionMixin
from .user_emitter_scopes import (
    emit_scoped_stmts,
    pop_control_context,
    push_control_context,
)


class _UserGenericControlMixin(_UserGenericExceptionMixin):
    def _loop_stmts(self, statements, *, iteration_bindings=()):
        push_control_context(self, "loop")
        try:
            return emit_scoped_stmts(
                self,
                statements,
                iteration_bindings=iteration_bindings,
            )
        finally:
            pop_control_context(self)

    def _if_stmt(self, s) -> IRIf:
        from ....ast_nodes import Block, ElseBlock, ElseIf

        cond = self._expr(s.condition)
        then_stmts = []
        if s.then_block:
            then_stmts = self.emit_stmts(s.then_block.statements)
        then_block = IRBlock(stmts=then_stmts)

        else_block = None
        if s.else_block:
            eb = s.else_block
            if isinstance(eb, ElseBlock):
                eb = eb.body
            if isinstance(eb, Block):
                else_stmts = self.emit_stmts(eb.statements)
                else_block = IRBlock(stmts=else_stmts)
            elif isinstance(eb, ElseIf):
                else_block = IRBlock(stmts=[self._if_stmt(eb.if_stmt)])

        return IRIf(condition=cond, then_block=then_block, else_block=else_block)

    def _cfor_stmt(self, s) -> IRFor:
        from ....ast_nodes import ForInitExpr, ForInitVar

        init_node = None
        if s.init:
            if isinstance(s.init, ForInitVar):
                vd = s.init.var_decl
                c_type = self.resolve_c(vd.type)
                init_expr = self._expr(vd.initializer) if vd.initializer else None
                init_node = IRVarDecl(c_type=CType(text=c_type), name=vd.name, init=init_expr)
            elif isinstance(s.init, ForInitExpr):
                init_node = IRExprStmt(expr=self._expr(s.init.expression))
        cond_node = self._expr(s.condition) if s.condition else None
        update_node = self._expr(s.update) if s.update else None
        body_stmts = self._loop_stmts(s.body.statements)
        return IRFor(init=init_node, condition=cond_node, update=update_node, body=IRBlock(stmts=body_stmts))

    def _forin_stmt(self, s) -> list:
        from ....ast_nodes import CallExpr, Identifier

        if (
            isinstance(s.iterable, CallExpr)
            and isinstance(s.iterable.callee, Identifier)
            and s.iterable.callee.name == "range"
        ):
            return self._range_forin_stmt(s)
        return self._iterable_forin_stmt(s)

    def _range_forin_stmt(self, s) -> list:
        from ..errors import CodegenError

        args = s.iterable.args
        if len(args) == 1:
            end_expr = self._expr(args[0])
            init_node = IRVarDecl(c_type=CType(text="int"), name=s.var_name, init=IRLiteral(text="0"))
            cond_node = IRBinOp(left=IRVar(name=s.var_name), op="<", right=end_expr)
            upd_node = IRUnaryOp(op="++", operand=IRVar(name=s.var_name), prefix=False)
        elif len(args) == 2:
            start_expr = self._expr(args[0])
            end_expr = self._expr(args[1])
            init_node = IRVarDecl(c_type=CType(text="int"), name=s.var_name, init=start_expr)
            cond_node = IRBinOp(left=IRVar(name=s.var_name), op="<", right=end_expr)
            upd_node = IRUnaryOp(op="++", operand=IRVar(name=s.var_name), prefix=False)
        elif len(args) == 3:
            start_expr = self._expr(args[0])
            end_expr = self._expr(args[1])
            step_expr = self._expr(args[2])
            init_node = IRVarDecl(c_type=CType(text="int"), name=s.var_name, init=start_expr)
            cond_node = IRTernary(
                condition=IRBinOp(left=step_expr, op=">", right=IRLiteral(text="0")),
                true_expr=IRBinOp(left=IRVar(name=s.var_name), op="<", right=end_expr),
                false_expr=IRBinOp(left=IRVar(name=s.var_name), op=">", right=end_expr),
            )
            upd_node = IRBinOp(left=IRVar(name=s.var_name), op="+=", right=step_expr)
        else:
            raise CodegenError(f"range() expects 1 to 3 arguments, got {len(args)}")
        body_stmts = self._loop_stmts(s.body.statements)
        return [IRFor(init=init_node, condition=cond_node, update=upd_node, body=IRBlock(stmts=body_stmts))]

    def _iterable_forin_stmt(self, s) -> list:
        from .user_emitter_iteration_protocol import (
            lower_iterable_forin,
        )

        return lower_iterable_forin(self, s)

    def _string_forin_stmt(self, statement) -> list:
        from .user_emitter_iteration_protocol import lower_string_forin

        return lower_string_forin(self, statement)

    def _while_stmt(self, s) -> IRWhile:
        body_stmts = self._loop_stmts(s.body.statements)
        return IRWhile(condition=self._expr(s.condition), body=IRBlock(stmts=body_stmts))

    def _dowhile_stmt(self, s) -> IRDoWhile:
        body_stmts = self._loop_stmts(s.body.statements)
        return IRDoWhile(body=IRBlock(stmts=body_stmts), condition=self._expr(s.condition))

    def _switch_stmt(self, statement) -> IRSwitch:
        cases = []
        push_control_context(self, "switch")
        try:
            for clause in statement.cases:
                value = self._expr(clause.value) if clause.value else None
                outer_types = self._var_types.copy()
                try:
                    body = self.emit_stmts(clause.body)
                finally:
                    self._var_types = outer_types
                cases.append(IRCase(value=value, body=body))
        finally:
            pop_control_context(self)
        return IRSwitch(value=self._expr(statement.value), cases=cases)
