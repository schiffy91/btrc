"""Statement emission and IR-to-text helpers for user-defined generics."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRBreak,
    IRCall,
    IRContinue,
    IRExpr,
    IRExprStmt,
    IRLiteral,
    IRStmt,
    IRVar,
    IRVarDecl,
)
from .user_emitter_control import _UserGenericControlMixin
from .user_emitter_releases import _UserGenericReleaseMixin
from .user_emitter_scopes import (
    declare_local,
    emit_control_cleanup_discard,
    emit_control_release,
    emit_try_pop,
    register_managed_local,
)
from .user_emitter_types import _UserGenericTypeMixin


class _UserGenericStmtMixin(
    _UserGenericTypeMixin,
    _UserGenericControlMixin,
    _UserGenericReleaseMixin,
):
    """Mixin providing statement emission for _UserGenericEmitter.

    All methods here assume the class also has: _expr(), resolve_c(),
    _resolve(), emit_stmts(), _var_types, and mangled attributes.
    """

    def _stmt(self, s) -> list[IRStmt]:
        from ....ast_nodes import (
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
        from ..errors import unsupported_node

        if isinstance(s, ReturnStmt):
            from .user_emitter_returns import lower_generic_return

            return lower_generic_return(self, s)
        if isinstance(s, Block):
            return [IRBlock(stmts=self.emit_stmts(s.statements))]
        if isinstance(s, ExprStmt):
            from .user_emitter_local_arc import (
                lower_generic_expression_statement,
            )

            return lower_generic_expression_statement(self, s.expr)
        if isinstance(s, VarDeclStmt):
            return self._var_decl(s)
        if isinstance(s, IfStmt):
            return [self._if_stmt(s)]
        if isinstance(s, CForStmt):
            return [self._cfor_stmt(s)]
        if isinstance(s, ForInStmt):
            return self._forin_stmt(s)
        if isinstance(s, ParallelForStmt):
            return self._forin_stmt(s)
        if isinstance(s, WhileStmt):
            return [self._while_stmt(s)]
        if isinstance(s, DoWhileStmt):
            return [self._dowhile_stmt(s)]
        if isinstance(s, SwitchStmt):
            return [self._switch_stmt(s)]
        if isinstance(s, BreakStmt):
            depth = self._exited_try_depth({"loop", "switch"})
            return (
                emit_control_release(self, {"loop", "switch"})
                + emit_control_cleanup_discard(self, {"loop", "switch"})
                + emit_try_pop(self, depth)
                + [IRBreak()]
            )
        if isinstance(s, ContinueStmt):
            depth = self._exited_try_depth({"loop"})
            return (
                emit_control_release(self, {"loop"})
                + emit_control_cleanup_discard(self, {"loop"})
                + emit_try_pop(self, depth)
                + [IRContinue()]
            )
        if isinstance(s, KeepStmt):
            return self._keep_stmt(s)
        if isinstance(s, ReleaseStmt):
            return self._release_stmt(s)
        if isinstance(s, DeleteStmt):
            return self._delete_stmt(s)
        if isinstance(s, TryCatchStmt):
            return self._try_catch_stmt(s)
        if isinstance(s, ThrowStmt):
            return self._throw_stmt(s)
        raise unsupported_node("generic method statement", s)

    def _keep_stmt(self, s) -> list[IRStmt]:
        resolved = self._resolve_expr_type(s.expr)
        if not self._is_managed_type(resolved):
            return []
        expr = self._expr(s.expr)
        from ..managed_values import retain_edge_value, retain_value

        retained = (
            retain_edge_value(self._gen, expr, resolved, IRVar(name="self"))
            if self._collection_edge_keeps
            else retain_value(self._gen, expr, resolved)
        )
        return [IRExprStmt(expr=retained)]

    def _delete_stmt(self, s) -> list[IRStmt]:
        from ..managed_local import mark_borrowed_cycle_seeds

        mark_borrowed_cycle_seeds(self._managed_vars_stack)
        expr = self._expr(s.expr)
        resolved = self._resolve_expr_type(s.expr)
        destroy_fn = self._class_destroy_fn(resolved)
        if destroy_fn:
            from ..arc_ops import arc_type_descriptor

            self._gen.use_helper("__btrc_arc_destroy")
            destroy = IRCall(
                callee="__btrc_arc_destroy",
                helper_ref="__btrc_arc_destroy",
                args=[expr, arc_type_descriptor(self._gen, resolved)],
            )
        elif self._is_string_type(resolved):
            from ..managed_values import release_value

            destroy = release_value(self._gen, expr, resolved)
        else:
            destroy = IRCall(callee="free", args=[expr])
        return [
            IRExprStmt(expr=destroy),
            IRAssign(target=expr, value=IRLiteral(text="NULL")),
        ]

    def _var_decl(self, s) -> list[IRStmt]:
        c_type = self.resolve_c(s.type)
        declare_local(self, s.name)
        # Track the resolved type for cross-type method call mangling
        resolved = None
        if s.type:
            resolved = self._resolve(s.type)
            self._var_types[s.name] = resolved
        if s.initializer:
            init = self._var_init_expr(s)
            declaration = IRVarDecl(c_type=CType(text=c_type), name=s.name, init=init)
        else:
            declaration = IRVarDecl(c_type=CType(text=c_type), name=s.name)
        self._func_var_decls.append(declaration)
        result = [declaration]
        if resolved is not None and s.initializer is not None and self._is_managed_type(resolved):
            owns_initializer = self._owns_expr(s.initializer)
            if not owns_initializer:
                from ..managed_values import retain_value

                result.append(IRExprStmt(expr=retain_value(self._gen, IRVar(name=s.name), resolved)))
            register_managed_local(self, s.name, resolved, owns_initializer, result)
        return result

    def _var_init_expr(self, s) -> IRExpr:
        """Emit a variable initializer, routing a typed collection literal to
        its declared collection type (e.g. Vector<int> xs = [1, 2, 3])."""
        from ....ast_nodes import BraceInitializer, ListLiteral, MapLiteral

        if s.type and isinstance(s.initializer, (BraceInitializer, ListLiteral, MapLiteral)):
            target = self._mangle_type(self._resolve(s.type))
            if target:
                return self._collection_literal(
                    target,
                    s.initializer,
                    self._resolve(s.type),
                )
        return self._expr(s.initializer)
