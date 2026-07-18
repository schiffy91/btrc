"""Exception-unwind registration for locally owned resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import (
    IRExprStmt,
    IRLiteral,
    IRStmt,
    IRVar,
)

if TYPE_CHECKING:
    from .generator import IRGenerator


def _activate_cleanup_slot(gen: IRGenerator, var_name: str, stmts: list[IRStmt]):
    gen.mark_cleanup_registration()
    from .cleanup_slots import require_cleanup_slot_declaration

    return require_cleanup_slot_declaration(stmts, var_name)


def maybe_register_cleanup(
    gen: IRGenerator,
    var_name: str,
    cls_name: str,
    stmts: list[IRStmt],
) -> None:
    """Register a managed slot for a possible dynamic exception unwind."""
    if not gen.exception_cleanup_active():
        return

    from .arc_cycles import managed_visitor_symbol
    from .managed_values import STRING_RUNTIME_NAME, cleanup_destroy_symbol

    destroy_fn = cleanup_destroy_symbol(cls_name)
    if cls_name == STRING_RUNTIME_NAME:
        maybe_register_direct_cleanup(gen, var_name, destroy_fn, stmts)
        return
    declaration = _activate_cleanup_slot(gen, var_name, stmts)
    visitor = managed_visitor_symbol(gen, cls_name)
    visit_arg = IRVar(name=visitor) if visitor else IRLiteral(text="NULL")
    from .cleanup_slots import register_cleanup_slot

    stmts.append(
        IRExprStmt(
            expr=register_cleanup_slot(
                gen,
                declaration,
                IRVar(name=destroy_fn),
                visitor=visit_arg,
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

    declaration = _activate_cleanup_slot(gen, var_name, stmts)
    gen.use_helper(cleanup_fn)
    from .cleanup_slots import register_cleanup_slot

    stmts.append(
        IRExprStmt(
            expr=register_cleanup_slot(
                gen,
                declaration,
                IRVar(name=cleanup_fn),
                direct=True,
            )
        )
    )
