"""Statement emission and IR-to-text helpers for user-defined generics."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRBreak,
    IRCall,
    IRCast,
    IRContinue,
    IRDoWhile,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRIf,
    IRIndex,
    IRLiteral,
    IRReturn,
    IRSizeof,
    IRStmt,
    IRStmtExpr,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)


class _UserGenericStmtMixin:
    """Mixin providing statement emission for _UserGenericEmitter.

    All methods here assume the class also has: _expr(), resolve_c(),
    _resolve(), emit_stmts(), _var_types, and mangled attributes.
    """

    def _stmt(self, s) -> list[IRStmt]:
        from ....ast_nodes import (
            BreakStmt,
            CForStmt,
            ContinueStmt,
            DeleteStmt,
            DoWhileStmt,
            ExprStmt,
            ForInStmt,
            IfStmt,
            KeepStmt,
            ReturnStmt,
            ReleaseStmt,
            VarDeclStmt,
            WhileStmt,
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
        if isinstance(s, KeepStmt):
            return self._keep_stmt(s)
        if isinstance(s, ReleaseStmt):
            return self._release_stmt(s)
        if isinstance(s, DeleteStmt):
            return [IRExprStmt(
                expr=IRCall(callee="free", args=[self._expr(s.expr)]))]
        return []

    def _resolve_expr_type(self, e):
        """Resolve the (type-substituted) TypeExpr of an AST expression.

        Covers the receivers we can name inside a monomorphized method: local
        variables, `self.<field>` (via the class's field types), and indexing
        into the collection's own `self.data` backing store. Returns None when
        the type is unknown (the caller falls back to a bare call)."""
        from ....ast_nodes import FieldAccessExpr, Identifier, IndexExpr, SelfExpr
        if isinstance(e, Identifier):
            return self._var_types.get(e.name)
        if isinstance(e, FieldAccessExpr) and isinstance(e.obj, SelfExpr):
            cls_info = getattr(self, "_cls_info", None)
            if cls_info and e.field in cls_info.fields and cls_info.fields[e.field].type:
                return self._resolve(cls_info.fields[e.field].type)
            return None
        if isinstance(e, IndexExpr):
            obj = e.obj
            if (isinstance(obj, FieldAccessExpr) and
                    isinstance(obj.obj, SelfExpr) and
                    obj.field == "data" and "T" in self.type_map):
                return self.type_map["T"]
        return None

    def _mangle_type(self, t):
        """Mangled C name for a resolved class/collection type, or None."""
        from ..types import mangle_generic_type
        if not t:
            return None
        if getattr(t, "generic_args", None):
            return mangle_generic_type(t.base, t.generic_args)
        if self._gen and t.base in self._gen.analyzed.class_table:
            if not self._gen.analyzed.class_table[t.base].generic_params:
                return t.base
        return None

    def _class_destroy_fn(self, resolved):
        if not self._gen or not resolved:
            return None
        cls = self._gen.analyzed.class_table.get(resolved.base)
        if not cls:
            return None
        if getattr(resolved, "generic_args", None):
            from ..types import mangle_generic_type
            target = mangle_generic_type(resolved.base, resolved.generic_args)
            dtor = "free" if "free" in cls.methods else "destroy"
            return f"{target}_{dtor}"
        if cls.generic_params:
            return None
        return f"{resolved.base}_destroy"

    def _keep_stmt(self, s) -> list[IRStmt]:
        resolved = self._resolve_expr_type(s.expr)
        if not self._class_destroy_fn(resolved):
            return []
        expr = self._expr(s.expr)
        return [IRExprStmt(expr=IRUnaryOp(
            op="++", operand=IRFieldAccess(obj=expr, field="__rc", arrow=True),
            prefix=False))]

    def _release_stmt(self, s) -> list[IRStmt]:
        resolved = self._resolve_expr_type(s.expr)
        destroy_fn = self._class_destroy_fn(resolved)
        if not destroy_fn:
            return []
        expr = self._expr(s.expr)
        return [IRIf(
            condition=expr,
            then_block=IRBlock(stmts=[IRIf(
                condition=IRBinOp(
                    left=IRUnaryOp(
                        op="--",
                        operand=IRFieldAccess(obj=expr, field="__rc", arrow=True),
                        prefix=True),
                    op="<=",
                    right=IRLiteral(text="0")),
                then_block=IRBlock(stmts=[IRExprStmt(
                    expr=IRCall(callee=destroy_fn, args=[expr]))]),
            )]),
        )]

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
        """Emit a variable initializer, routing a typed collection literal to
        its declared collection type (e.g. Vector<int> xs = [1, 2, 3])."""
        from ....ast_nodes import ListLiteral, MapLiteral
        if s.type and isinstance(s.initializer, (ListLiteral, MapLiteral)):
            target = self._mangle_type(self._resolve(s.type))
            if target:
                return self._collection_literal(target, s.initializer)
        return self._expr(s.initializer)

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
                # Wrap the inner if in a block so the emitter handles else-if
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

        # Iterate a collection via the Iterable protocol (iterLen/iterGet),
        # mirroring the non-generic lowering — e.g. `for x in items` where
        # items is a Vector<T>/Map<K,V> field or local inside the method.
        iter_type = self._resolve_expr_type(s.iterable)
        if iter_type and getattr(iter_type, "generic_args", None) and self._gen:
            cls = self._gen.analyzed.class_table.get(iter_type.base)
            if cls and "iterLen" in cls.methods and "iterGet" in cls.methods:
                from ..types import mangle_generic_type
                mangled = mangle_generic_type(iter_type.base,
                                              iter_type.generic_args)
                it = self._fresh_temp("__iter")
                n = self._fresh_temp("__n")
                idx = self._fresh_temp("__i")
                iter_c = self._ttc(iter_type)
                if not iter_c.endswith("*"):
                    iter_c += "*"
                body_stmts = self.emit_stmts(s.body.statements)
                # element binding: T x = TYPE_iterGet(it, i);
                body_stmts.insert(0, IRVarDecl(
                    c_type=CType(text=self._ttc(iter_type.generic_args[0])),
                    name=s.var_name,
                    init=IRCall(callee=f"{mangled}_iterGet",
                                args=[IRVar(name=it), IRVar(name=idx)])))
                # optional value binding for two-variable map iteration
                var2 = getattr(s, "var_name2", None)
                if (var2 and "iterValueAt" in cls.methods and
                        len(iter_type.generic_args) > 1):
                    body_stmts.insert(1, IRVarDecl(
                        c_type=CType(text=self._ttc(iter_type.generic_args[1])),
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
        # For text rendering, just show the result expression
        # (stmts are hoisted by the emitter at emission time)
        return _ir_expr_to_text(expr.result)
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
