"""Statement emission and IR-to-text helpers for user-defined generics."""

from __future__ import annotations

from ...nodes import (
    CType,
    IRBlock,
    IRBreak,
    IRContinue,
    IRExpr,
    IRExprStmt,
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
        from ..manual_destruction import lower_taken_delete
        from ..persistent_slots import stabilize_persistent_slot

        mark_borrowed_cycle_seeds(self._managed_vars_stack)
        target = self._expr(s.expr)
        resolved = self._resolve_expr_type(s.expr)
        target, edge_owner, owner_decls = stabilize_persistent_slot(
            self._gen,
            s.expr,
            target,
            resolve_type=self._resolve_expr_type,
            render_type=self.iter_value_c,
            fresh_temp=self._fresh_temp,
            record_decl=self._func_var_decls.append,
            prefix="__btrc_delete_owner",
        )
        return [
            *owner_decls,
            *lower_taken_delete(
                self._gen,
                target,
                resolved,
                edge_owner=edge_owner,
            ),
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
            from ..prepared_values import prepare_generic_value

            prepared = prepare_generic_value(
                self,
                s.initializer,
                resolved,
                lowered=init,
            )
            init = prepared.value
            from ..upcast import upcast_class_pointer

            init = upcast_class_pointer(
                self._gen,
                resolved,
                prepared.effective_type,
                init,
            )
            declaration = IRVarDecl(c_type=CType(text=c_type), name=s.name, init=init)
        else:
            prepared = None
            declaration = IRVarDecl(c_type=CType(text=c_type), name=s.name)
        self._func_var_decls.append(declaration)
        result = [declaration]
        ownership_type = resolved
        if (
            not self._is_managed_type(ownership_type)
            and prepared is not None
            and prepared.owned
            and self._is_managed_type(prepared.effective_type)
        ):
            ownership_type = prepared.effective_type
        if ownership_type is not None and s.initializer is not None and self._is_managed_type(ownership_type):
            owns_initializer = prepared.owned
            if not owns_initializer:
                from ..managed_values import retain_value

                result.append(IRExprStmt(expr=retain_value(self._gen, IRVar(name=s.name), ownership_type)))
            register_managed_local(self, s.name, ownership_type, owns_initializer, result)
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
