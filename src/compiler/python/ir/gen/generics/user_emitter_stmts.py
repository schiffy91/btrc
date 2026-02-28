"""Statement emission and IR-to-text helpers for user-defined generics."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...nodes import (
    CType, IRAssign, IRBinOp, IRBlock, IRBreak, IRCall, IRCast,
    IRContinue, IRDoWhile, IRExpr, IRExprStmt, IRFieldAccess, IRFor,
    IRIf, IRIndex, IRLiteral, IRReturn, IRSizeof, IRStmt, IRStmtExpr,
    IRTernary, IRUnaryOp, IRVar, IRVarDecl, IRWhile,
)


class _UserGenericStmtMixin:
    """Mixin providing statement emission for _UserGenericEmitter.

    All methods here assume the class also has: _expr(), resolve_c(),
    _resolve(), emit_stmts(), _var_types, and mangled attributes.
    """

    def _stmt(self, s) -> list[IRStmt]:
        from ....ast_nodes import (
            ReturnStmt, ExprStmt, IfStmt, VarDeclStmt,
            CForStmt, ForInStmt, WhileStmt, DoWhileStmt,
            BreakStmt, ContinueStmt, DeleteStmt,
        )

        if isinstance(s, ReturnStmt):
            val = self._expr(s.value) if s.value else None
            return [IRReturn(value=val)]
        if isinstance(s, ExprStmt):
            return [IRExprStmt(expr=self._expr(s.expr))]
        if isinstance(s, VarDeclStmt):
            return self._var_decl(s)
        if isinstance(s, IfStmt):
            return [self._if_stmt(s)]
        if isinstance(s, CForStmt):
            return [self._cfor_stmt(s)]
        if isinstance(s, ForInStmt):
            return self._forin_stmt(s)
        if isinstance(s, WhileStmt):
            return [self._while_stmt(s)]
        if isinstance(s, DoWhileStmt):
            return [self._dowhile_stmt(s)]
        if isinstance(s, BreakStmt):
            return [IRBreak()]
        if isinstance(s, ContinueStmt):
            return [IRContinue()]
        if isinstance(s, DeleteStmt):
            return [IRExprStmt(
                expr=IRCall(callee="free", args=[self._expr(s.expr)]))]
        return []

    def _var_decl(self, s) -> list[IRStmt]:
        c_type = self.resolve_c(s.type)
        # Track the resolved type for cross-type method call mangling
        if s.type:
            resolved = self._resolve(s.type)
            self._var_types[s.name] = resolved
        if s.initializer:
            init = self._var_init_expr(s)
            return [IRVarDecl(c_type=CType(text=c_type), name=s.name,
                              init=init)]
        return [IRVarDecl(c_type=CType(text=c_type), name=s.name)]

    def _var_init_expr(self, s) -> IRExpr:
        """Emit the initializer for a variable, handling typed literals."""
        from ....ast_nodes import ListLiteral, MapLiteral
        from ..types import mangle_generic_type

        if s.type and isinstance(s.initializer, (ListLiteral, MapLiteral)):
            resolved = self._resolve(s.type)
            if resolved.generic_args:
                target = mangle_generic_type(resolved.base,
                                             resolved.generic_args)
                if isinstance(s.initializer, ListLiteral):
                    if not s.initializer.elements:
                        return IRCall(callee=f"{target}_new", args=[])
                    stmts = [
                        IRVarDecl(c_type=CType(text=f"{target}*"),
                                  name="__tmp",
                                  init=IRCall(callee=f"{target}_new",
                                              args=[])),
                    ]
                    for x in s.initializer.elements:
                        stmts.append(IRExprStmt(
                            expr=IRCall(callee=f"{target}_push",
                                        args=[IRVar(name="__tmp"),
                                              self._expr(x)])))
                    return IRStmtExpr(stmts=stmts,
                                      result=IRVar(name="__tmp"))
                if isinstance(s.initializer, MapLiteral):
                    if not s.initializer.entries:
                        return IRCall(callee=f"{target}_new", args=[])
                    stmts = [
                        IRVarDecl(c_type=CType(text=f"{target}*"),
                                  name="__tmp",
                                  init=IRCall(callee=f"{target}_new",
                                              args=[])),
                    ]
                    for entry in s.initializer.entries:
                        stmts.append(IRExprStmt(
                            expr=IRCall(callee=f"{target}_put",
                                        args=[IRVar(name="__tmp"),
                                              self._expr(entry.key),
                                              self._expr(entry.value)])))
                    return IRStmtExpr(stmts=stmts,
                                      result=IRVar(name="__tmp"))
        return self._expr(s.initializer)

    def _if_stmt(self, s) -> IRIf:
        from ....ast_nodes import Block, ElseIf, ElseBlock
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
                # Wrap the inner if in a block so the emitter handles else-if
                else_block = IRBlock(stmts=[self._if_stmt(eb.if_stmt)])

        return IRIf(condition=cond, then_block=then_block,
                    else_block=else_block)

    def _cfor_stmt(self, s) -> IRFor:
        from ....ast_nodes import ForInitVar, ForInitExpr
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

    def _forin_stmt(self, s) -> list[IRStmt]:
        from ....ast_nodes import CallExpr, Identifier
        if (isinstance(s.iterable, CallExpr) and
                isinstance(s.iterable.callee, Identifier) and
                s.iterable.callee.name == "range"):
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
                          update=upd_node,
                          body=IRBlock(stmts=body_stmts))]
        return []

    def _while_stmt(self, s) -> IRWhile:
        body_stmts = self.emit_stmts(s.body.statements)
        return IRWhile(condition=self._expr(s.condition),
                       body=IRBlock(stmts=body_stmts))

    def _dowhile_stmt(self, s) -> IRDoWhile:
        body_stmts = self.emit_stmts(s.body.statements)
        return IRDoWhile(body=IRBlock(stmts=body_stmts),
                         condition=self._expr(s.condition))


# ------------------------------------------------------------------
# IR-to-text helpers (for sizeof operand and compatibility checks)
# ------------------------------------------------------------------

def _ir_expr_to_text(expr: IRExpr) -> str:
    """Convert an IRExpr node to a rough C text string.

    Used for sizeof operand rendering and the _is_type_incompatible
    check in user.py.
    """
    if expr is None:
        return ""
    if isinstance(expr, IRLiteral):
        return expr.text
    if isinstance(expr, IRVar):
        return expr.name
    if isinstance(expr, IRBinOp):
        return f"({_ir_expr_to_text(expr.left)} {expr.op} {_ir_expr_to_text(expr.right)})"
    if isinstance(expr, IRUnaryOp):
        inner = _ir_expr_to_text(expr.operand)
        if expr.prefix:
            return f"({expr.op}{inner})"
        return f"({inner}{expr.op})"
    if isinstance(expr, IRCall):
        args = ", ".join(_ir_expr_to_text(a) for a in expr.args)
        return f"{expr.callee}({args})"
    if isinstance(expr, IRFieldAccess):
        op = "->" if expr.arrow else "."
        return f"{_ir_expr_to_text(expr.obj)}{op}{expr.field}"
    if isinstance(expr, IRCast):
        return f"({expr.target_type.text}){_ir_expr_to_text(expr.expr)}"
    if isinstance(expr, IRTernary):
        return (f"({_ir_expr_to_text(expr.condition)} ? "
                f"{_ir_expr_to_text(expr.true_expr)} : "
                f"{_ir_expr_to_text(expr.false_expr)})")
    if isinstance(expr, IRSizeof):
        return f"sizeof({expr.operand})"
    if isinstance(expr, IRIndex):
        return f"{_ir_expr_to_text(expr.obj)}[{_ir_expr_to_text(expr.index)}]"
    if isinstance(expr, IRStmtExpr):
        parts = []
        for s in expr.stmts:
            parts.append(_ir_stmt_to_text(s))
        parts.append(f" {_ir_expr_to_text(expr.result)};")
        return "({" + "".join(parts) + " })"
    return "0"


def _ir_stmt_to_text(stmt: IRStmt) -> str:
    """Convert an IRStmt node to rough C text for compatibility checks."""
    if isinstance(stmt, IRVarDecl):
        if stmt.init:
            return f" {stmt.c_type.text} {stmt.name} = {_ir_expr_to_text(stmt.init)};"
        return f" {stmt.c_type.text} {stmt.name};"
    if isinstance(stmt, IRExprStmt):
        return f" {_ir_expr_to_text(stmt.expr)};"
    if isinstance(stmt, IRReturn):
        if stmt.value:
            return f" return {_ir_expr_to_text(stmt.value)};"
        return " return;"
    if isinstance(stmt, IRAssign):
        return f" {_ir_expr_to_text(stmt.target)} = {_ir_expr_to_text(stmt.value)};"
    if isinstance(stmt, IRIf):
        txt = f" if ({_ir_expr_to_text(stmt.condition)}) {{"
        if stmt.then_block:
            for s in stmt.then_block.stmts:
                txt += _ir_stmt_to_text(s)
            txt += " }"
        if stmt.else_block and stmt.else_block.stmts:
            txt += " else {"
            for s in stmt.else_block.stmts:
                txt += _ir_stmt_to_text(s)
            txt += " }"
        return txt
    if isinstance(stmt, IRFor):
        init_text = ""
        if stmt.init:
            if isinstance(stmt.init, IRVarDecl):
                if stmt.init.init:
                    init_text = f"{stmt.init.c_type.text} {stmt.init.name} = {_ir_expr_to_text(stmt.init.init)}"
                else:
                    init_text = f"{stmt.init.c_type.text} {stmt.init.name}"
            elif isinstance(stmt.init, IRExprStmt):
                init_text = _ir_expr_to_text(stmt.init.expr)
            elif isinstance(stmt.init, IRAssign):
                init_text = f"{_ir_expr_to_text(stmt.init.target)} = {_ir_expr_to_text(stmt.init.value)}"
        cond_text = _ir_expr_to_text(stmt.condition) if stmt.condition else ""
        upd_text = _ir_expr_to_text(stmt.update) if stmt.update else ""
        txt = f" for ({init_text}; {cond_text}; {upd_text}) {{"
        if stmt.body:
            for s in stmt.body.stmts:
                txt += _ir_stmt_to_text(s)
        txt += " }"
        return txt
    if isinstance(stmt, IRWhile):
        txt = f" while ({_ir_expr_to_text(stmt.condition)}) {{"
        if stmt.body:
            for s in stmt.body.stmts:
                txt += _ir_stmt_to_text(s)
        txt += " }"
        return txt
    if isinstance(stmt, IRDoWhile):
        txt = " do {"
        if stmt.body:
            for s in stmt.body.stmts:
                txt += _ir_stmt_to_text(s)
        txt += f" }} while ({_ir_expr_to_text(stmt.condition)});"
        return txt
    if isinstance(stmt, IRBreak):
        return " break;"
    if isinstance(stmt, IRContinue):
        return " continue;"
    return ""


def _ir_stmts_to_text(stmts: list[IRStmt]) -> str:
    """Convert a list of IRStmt nodes to rough C text for compatibility checks."""
    return "".join(_ir_stmt_to_text(s) for s in stmts)
