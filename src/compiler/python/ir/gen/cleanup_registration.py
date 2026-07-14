"""Exception-unwind registration for locally owned resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import (
    CType,
    IRAddressOf,
    IRCall,
    IRCast,
    IRExprStmt,
    IRLiteral,
    IRStmt,
    IRVar,
    IRVarDecl,
)

if TYPE_CHECKING:
    from .generator import IRGenerator


def _mark_cleanup_slot(gen: IRGenerator, var_name: str, stmts: list[IRStmt]) -> None:
    gen.mark_cleanup_registration()
    # The unwind registry holds this slot's address.  Keep nulling writes
    # observable so optimized builds cannot leave a stale resource pointer.
    for statement in reversed(stmts):
        if isinstance(statement, IRVarDecl) and statement.name == var_name:
            statement.is_volatile = True
            break


def maybe_register_cleanup(
    gen: IRGenerator,
    var_name: str,
    cls_name: str,
    stmts: list[IRStmt],
) -> None:
    """Register a managed slot for a possible dynamic exception unwind."""
    if not gen.exception_cleanup_active():
        return

    from .arc_cycles import managed_type_has_visitor
    from .cycle_metadata import cycle_visitor_symbol
    from .managed_values import STRING_RUNTIME_NAME, cleanup_destroy_symbol

    destroy_fn = cleanup_destroy_symbol(cls_name)
    if cls_name == STRING_RUNTIME_NAME:
        maybe_register_direct_cleanup(gen, var_name, destroy_fn, stmts)
        return
    _mark_cleanup_slot(gen, var_name, stmts)
    gen.use_helper("__btrc_register_cleanup")
    if managed_type_has_visitor(gen, cls_name):
        visit_arg = IRVar(name=cycle_visitor_symbol(cls_name))
    else:
        visit_arg = IRLiteral(text="NULL")
    stmts.append(
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_register_cleanup",
                args=[
                    IRCast(
                        target_type=CType(text="void**"),
                        expr=IRAddressOf(expr=IRVar(name=var_name)),
                    ),
                    IRVar(name=destroy_fn),
                    visit_arg,
                ],
                helper_ref="__btrc_register_cleanup",
            )
        )
    )


def maybe_register_direct_cleanup(
    gen: IRGenerator,
    var_name: str,
    cleanup_fn: str,
    stmts: list[IRStmt],
) -> None:
    """Register a non-ARC resource callback for dynamic exception unwind."""
    if not gen.exception_cleanup_active():
        return

    _mark_cleanup_slot(gen, var_name, stmts)
    gen.use_helper(cleanup_fn)
    gen.use_helper("__btrc_register_direct_cleanup")
    stmts.append(
        IRExprStmt(
            expr=IRCall(
                callee="__btrc_register_direct_cleanup",
                args=[
                    IRCast(
                        target_type=CType(text="void**"),
                        expr=IRAddressOf(expr=IRVar(name=var_name)),
                    ),
                    IRVar(name=cleanup_fn),
                ],
                helper_ref="__btrc_register_direct_cleanup",
            )
        )
    )
