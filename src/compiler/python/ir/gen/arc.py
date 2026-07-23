"""Explicit managed-release statement lowering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..c_types import qualify_volatile_object
from ..nodes import (
    CType,
    IRAddressOf,
    IRAssign,
    IRCall,
    IRDeref,
    IRExprStmt,
    IRLiteral,
    IRStmt,
    IRVar,
    IRVarDecl,
)
from .expressions import lower_expr

if TYPE_CHECKING:
    from ...ast_nodes import ReleaseStmt
    from .lowerer import IRLowerer
    from .ownership_lifetime import ManagedLifetimeLowerer
    from .types import CTypeRenderer


class ManagedReleaseLowerer:
    """Lower explicit source releases through one managed-lifetime owner."""

    def __init__(
        self,
        lifetime: ManagedLifetimeLowerer,
        type_renderer: CTypeRenderer,
    ) -> None:
        self.lifetime = lifetime
        self.type_renderer = type_renderer

    def lower_statement(
        self,
        lowerer: IRLowerer,
        node: ReleaseStmt,
    ) -> list[IRStmt]:
        return self.lower_expression(lowerer, node.expr)

    def lower_expression(
        self,
        lowerer: IRLowerer,
        expression,
    ) -> list[IRStmt]:
        """Clear and release one analyzed physical managed slot."""
        expr = lower_expr(lowerer, expression, self.type_renderer)
        expr_type = lowerer.analyzed.node_types.get(id(expression))

        if not self.lifetime.values.is_managed(expr_type):
            return [IRExprStmt(expr=IRCall(callee="free", args=[expr]))]
        from .persistent_slots import stabilize_persistent_slot

        expr, edge_owner, owner_decls = stabilize_persistent_slot(
            lowerer,
            expression,
            expr,
            render_type=self.type_renderer.render,
            prefix="__btrc_release_owner",
        )

        value_c = self.type_renderer.render(expr_type)
        slot_name = self.lifetime.context.fresh_temp("__btrc_release_slot")
        slot_decl = IRVarDecl(
            c_type=CType(text=f"{qualify_volatile_object(value_c, True)}*"),
            name=slot_name,
            init=IRAddressOf(expr=expr),
        )
        slot = IRDeref(expr=IRVar(name=slot_name))
        self.lifetime.context.record_declaration(slot_decl)
        statements = [*owner_decls, slot_decl]
        if edge_owner is not None and self.lifetime.values.is_arc(expr_type):
            statements.append(
                IRExprStmt(
                    expr=self.lifetime.replace_edge_value(
                        slot,
                        IRLiteral(text="NULL"),
                        expr_type,
                        edge_owner,
                        adopt=False,
                    )
                )
            )
        else:
            value_name = self.lifetime.context.fresh_temp("__btrc_release_value")
            value_decl = IRVarDecl(
                c_type=CType(text=value_c),
                name=value_name,
                init=slot,
            )
            self.lifetime.context.record_declaration(value_decl)
            value = IRVar(name=value_name)
            statements.append(value_decl)
            if edge_owner is not None:
                statements.append(
                    IRExprStmt(
                        expr=self.lifetime.unlink_edge_value(
                            value,
                            expr_type,
                            edge_owner,
                        )
                    )
                )
            statements.extend(
                [
                    IRAssign(
                        target=slot,
                        value=IRLiteral(text="NULL"),
                    ),
                    IRExprStmt(
                        expr=(
                            self.lifetime.release_edge_value(
                                value,
                                expr_type,
                            )
                            if edge_owner is not None
                            else self.lifetime.release_value(
                                value,
                                expr_type,
                            )
                        )
                    ),
                ]
            )
        flush = self.lifetime.flush_released_values(expr_type)
        if flush is not None:
            statements.append(IRExprStmt(expr=flush))
        return statements


__all__ = ["ManagedReleaseLowerer"]
