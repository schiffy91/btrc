"""Explicit managed-release lowering for user generic methods."""

from __future__ import annotations

from ...c_types import qualify_volatile_object
from ...nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRDeref,
    IRExprStmt,
    IRLiteral,
    IRStmt,
    IRVar,
    IRVarDecl,
)
from ..managed_values import (
    flush_released_values,
    is_arc_type,
    poll_released_values,
    release_edge_value,
    release_value,
    replace_edge_value,
    unlink_edge_value,
)


class _UserGenericReleaseMixin:
    def _release_stmt(self, statement) -> list[IRStmt]:
        return self._release_expression(statement.expr)

    def _release_expression(self, expression) -> list[IRStmt]:
        """Clear and release one specialized physical managed slot."""
        resolved = self._resolve_expr_type(expression)
        if not self._is_managed_type(resolved):
            return []
        expr = self._expr(expression)
        from ..persistent_slots import stabilize_persistent_slot

        expr, edge_owner, owner_decls = stabilize_persistent_slot(
            self._gen,
            expression,
            expr,
            resolve_type=self._resolve_expr_type,
            render_type=self.iter_value_c,
            fresh_temp=self._fresh_temp,
            record_decl=self._func_var_decls.append,
            prefix="__btrc_release_owner",
        )

        slot_name = self._fresh_temp("__btrc_release_slot")
        slot_decl = IRVarDecl(
            c_type=CType(text=f"{qualify_volatile_object(self.iter_value_c(resolved), True)}*"),
            name=slot_name,
            init=IRAddressOf(expr=expr),
        )
        self._func_var_decls.append(slot_decl)
        slot = IRDeref(expr=IRVar(name=slot_name))
        result = [*owner_decls, slot_decl]
        if edge_owner is not None and is_arc_type(self._gen, resolved):
            result.append(
                IRExprStmt(
                    expr=replace_edge_value(
                        self._gen,
                        slot,
                        IRLiteral(text="NULL"),
                        resolved,
                        edge_owner,
                        adopt=False,
                    )
                )
            )
        else:
            value_name = self._fresh_temp("__btrc_release_value")
            value_decl = IRVarDecl(
                c_type=CType(text=self.iter_value_c(resolved)),
                name=value_name,
                init=slot,
            )
            self._func_var_decls.append(value_decl)
            release = release_edge_value if edge_owner is not None else release_value
            result.extend(
                [
                    value_decl,
                    *(
                        [
                            IRExprStmt(
                                expr=unlink_edge_value(
                                    self._gen,
                                    IRVar(name=value_name),
                                    resolved,
                                    edge_owner,
                                )
                            )
                        ]
                        if edge_owner is not None
                        else []
                    ),
                    IRAssign(target=slot, value=IRLiteral(text="NULL")),
                    IRExprStmt(
                        expr=release(
                            self._gen,
                            IRVar(name=value_name),
                            resolved,
                        )
                    ),
                ]
            )
        boundary = poll_released_values if self._batch_explicit_releases else flush_released_values
        flush = boundary(self._gen, resolved)
        if flush is not None:
            result.append(IRExprStmt(expr=flush))
        return result


__all__ = ["_UserGenericReleaseMixin"]
