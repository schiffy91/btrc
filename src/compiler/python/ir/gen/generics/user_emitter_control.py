"""Control-flow statement lowering for monomorphized generic methods."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRBinOp,
    IRBlock,
    IRCall,
    IRDoWhile,
    IRExprStmt,
    IRFor,
    IRIf,
    IRLiteral,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)


class _UserGenericControlMixin:
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

        return IRIf(condition=cond, then_block=then_block,
                    else_block=else_block)

    def _cfor_stmt(self, s) -> IRFor:
        from ....ast_nodes import ForInitExpr, ForInitVar
        init_node = None
        if s.init:
            if isinstance(s.init, ForInitVar):
                vd = s.init.var_decl
                c_type = self.resolve_c(vd.type)
                init_expr = self._expr(vd.initializer) if vd.initializer else None
                init_node = IRVarDecl(c_type=CType(text=c_type), name=vd.name,
                                      init=init_expr)
            elif isinstance(s.init, ForInitExpr):
                init_node = IRExprStmt(expr=self._expr(s.init.expression))
        cond_node = self._expr(s.condition) if s.condition else None
        update_node = self._expr(s.update) if s.update else None
        body_stmts = self.emit_stmts(s.body.statements)
        return IRFor(init=init_node, condition=cond_node, update=update_node,
                     body=IRBlock(stmts=body_stmts))

    def _forin_stmt(self, s) -> list:
        from ....ast_nodes import CallExpr, Identifier
        if (isinstance(s.iterable, CallExpr) and
                isinstance(s.iterable.callee, Identifier) and
                s.iterable.callee.name == "range"):
            return self._range_forin_stmt(s)
        return self._iterable_forin_stmt(s)

    def _range_forin_stmt(self, s) -> list:
        args = s.iterable.args
        if len(args) == 1:
            end_expr = self._expr(args[0])
            init_node = IRVarDecl(c_type=CType(text="int"),
                                  name=s.var_name,
                                  init=IRLiteral(text="0"))
            cond_node = IRBinOp(left=IRVar(name=s.var_name), op="<",
                                right=end_expr)
            upd_node = IRUnaryOp(op="++",
                                 operand=IRVar(name=s.var_name),
                                 prefix=False)
        elif len(args) >= 2:
            start_expr = self._expr(args[0])
            end_expr = self._expr(args[1])
            init_node = IRVarDecl(c_type=CType(text="int"),
                                  name=s.var_name, init=start_expr)
            cond_node = IRBinOp(left=IRVar(name=s.var_name), op="<",
                                right=end_expr)
            upd_node = IRUnaryOp(op="++",
                                 operand=IRVar(name=s.var_name),
                                 prefix=False)
        else:
            init_node = IRVarDecl(c_type=CType(text="int"),
                                  name=s.var_name,
                                  init=IRLiteral(text="0"))
            cond_node = IRLiteral(text="0")
            upd_node = None
        body_stmts = self.emit_stmts(s.body.statements)
        return [IRFor(init=init_node, condition=cond_node,
                      update=upd_node, body=IRBlock(stmts=body_stmts))]

    def _iterable_forin_stmt(self, s) -> list:
        iter_type = self._resolve_expr_type(s.iterable)
        if not (iter_type and getattr(iter_type, "generic_args", None) and self._gen):
            return []
        cls = self._gen.analyzed.class_table.get(iter_type.base)
        if not (cls and "iterLen" in cls.methods and "iterGet" in cls.methods):
            return []
        from ..types import mangle_generic_type
        mangled = mangle_generic_type(iter_type.base, iter_type.generic_args)
        it = self._fresh_temp("__iter")
        n = self._fresh_temp("__n")
        idx = self._fresh_temp("__i")
        iter_c = self._ttc(iter_type)
        if not iter_c.endswith("*"):
            iter_c += "*"
        body_stmts = self.emit_stmts(s.body.statements)
        body_stmts.insert(0, IRVarDecl(
            c_type=CType(text=self.iter_value_c(iter_type.generic_args[0])),
            name=s.var_name,
            init=IRCall(callee=f"{mangled}_iterGet",
                        args=[IRVar(name=it), IRVar(name=idx)])))
        var2 = getattr(s, "var_name2", None)
        if var2 and "iterValueAt" in cls.methods and len(iter_type.generic_args) > 1:
            body_stmts.insert(1, IRVarDecl(
                c_type=CType(text=self.iter_value_c(iter_type.generic_args[1])),
                name=var2,
                init=IRCall(callee=f"{mangled}_iterValueAt",
                            args=[IRVar(name=it), IRVar(name=idx)])))
        return [
            IRVarDecl(c_type=CType(text=iter_c), name=it,
                      init=self._expr(s.iterable)),
            IRVarDecl(c_type=CType(text="int"), name=n,
                      init=IRCall(callee=f"{mangled}_iterLen",
                                  args=[IRVar(name=it)])),
            IRFor(init=IRVarDecl(c_type=CType(text="int"), name=idx,
                                 init=IRLiteral(text="0")),
                  condition=IRBinOp(left=IRVar(name=idx), op="<",
                                    right=IRVar(name=n)),
                  update=IRUnaryOp(op="++", operand=IRVar(name=idx),
                                   prefix=False),
                  body=IRBlock(stmts=body_stmts)),
        ]

    def _while_stmt(self, s) -> IRWhile:
        body_stmts = self.emit_stmts(s.body.statements)
        return IRWhile(condition=self._expr(s.condition),
                       body=IRBlock(stmts=body_stmts))

    def _dowhile_stmt(self, s) -> IRDoWhile:
        body_stmts = self.emit_stmts(s.body.statements)
        return IRDoWhile(body=IRBlock(stmts=body_stmts),
                         condition=self._expr(s.condition))
