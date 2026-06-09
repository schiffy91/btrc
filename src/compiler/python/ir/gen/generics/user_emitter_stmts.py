"""Statement emission and IR-to-text helpers for user-defined generics."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRBreak,
    IRCall,
    IRContinue,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRIf,
    IRLiteral,
    IRReturn,
    IRStmt,
    IRUnaryOp,
    IRVarDecl,
)
from .user_emitter_control import _UserGenericControlMixin


class _UserGenericStmtMixin(_UserGenericControlMixin):
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
            ReleaseStmt,
            ReturnStmt,
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
            return self._delete_stmt(s)
        return []

    def _resolve_expr_type(self, e):
        """Resolve the (type-substituted) TypeExpr of an AST expression.

        Covers the receivers we can name inside a monomorphized method: local
        variables, `self.<field>` (via the class's field types), and indexing
        into generic backing arrays like `self.data[i]`, `self.keys[i]`, and
        `self.values[i]`. Returns None when the type is unknown."""
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
            if isinstance(obj, FieldAccessExpr) and isinstance(obj.obj, SelfExpr):
                return self._indexed_self_field_type(obj.field)
        return None

    def _indexed_self_field_type(self, field_name: str):
        from ....ast_nodes import TypeExpr
        cls_info = getattr(self, "_cls_info", None)
        if not cls_info or field_name not in cls_info.fields:
            return None
        field_type = cls_info.fields[field_name].type
        if not field_type:
            return None
        resolved = self._resolve(field_type)
        if resolved.pointer_depth <= 0:
            return resolved
        return TypeExpr(
            base=resolved.base,
            generic_args=resolved.generic_args,
            pointer_depth=resolved.pointer_depth - 1,
            is_array=resolved.is_array,
            array_size=resolved.array_size,
            is_const=resolved.is_const,
            is_nullable=resolved.is_nullable,
            line=resolved.line,
            col=resolved.col,
        )

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

    def _delete_stmt(self, s) -> list[IRStmt]:
        expr = self._expr(s.expr)
        destroy_fn = self._class_destroy_fn(self._resolve_expr_type(s.expr))
        callee = destroy_fn if destroy_fn else "free"
        return [
            IRExprStmt(expr=IRCall(callee=callee, args=[expr])),
            IRAssign(target=expr, value=IRLiteral(text="NULL")),
        ]

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
