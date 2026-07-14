"""Explicit managed-release lowering for user generic methods."""

from __future__ import annotations

from ....ast_nodes import FieldAccessExpr, IndexExpr
from ...c_types import qualify_volatile_object
from ...nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRDeref,
    IRExprStmt,
    IRFieldAccess,
    IRIndex,
    IRLiteral,
    IRStmt,
    IRVar,
    IRVarDecl,
)
from ..managed_values import (
    flush_released_values,
    is_class_type,
    poll_released_values,
    release_edge_value,
    release_value,
    replace_edge_value,
    unlink_edge_value,
)


class _UserGenericReleaseMixin:
    def _release_stmt(self, statement) -> list[IRStmt]:
        resolved = self._resolve_expr_type(statement.expr)
        if not self._is_managed_type(resolved):
            return []
        expr = self._expr(statement.expr)

        edge_owner = None
        owner_decls = []
        owner_node = None
        owner_expr = None
        shape = ""
        if isinstance(statement.expr, FieldAccessExpr) and isinstance(expr, IRFieldAccess):
            owner_node = statement.expr.obj
            owner_expr = expr.obj
            shape = "field"
        elif (
            isinstance(statement.expr, IndexExpr)
            and isinstance(statement.expr.obj, FieldAccessExpr)
            and isinstance(expr, IRIndex)
            and isinstance(expr.obj, IRFieldAccess)
        ):
            owner_node = statement.expr.obj.obj
            owner_expr = expr.obj.obj
            shape = "index"
        owner_type = self._resolve_expr_type(owner_node) if owner_node is not None else None
        if owner_expr is not None and is_class_type(self._gen, owner_type):
            owner_decl = IRVarDecl(
                c_type=CType(text=self.iter_value_c(owner_type)),
                name=self._fresh_temp("__btrc_release_owner"),
                init=owner_expr,
            )
            self._func_var_decls.append(owner_decl)
            owner_decls.append(owner_decl)
            edge_owner = IRVar(name=owner_decl.name)
            if shape == "field":
                expr = IRFieldAccess(
                    obj=edge_owner,
                    field=expr.field,
                    arrow=expr.arrow,
                )
            else:
                expr = IRIndex(
                    obj=IRFieldAccess(
                        obj=edge_owner,
                        field=expr.obj.field,
                        arrow=expr.obj.arrow,
                    ),
                    index=expr.index,
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
        if edge_owner is not None and is_class_type(self._gen, resolved):
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
