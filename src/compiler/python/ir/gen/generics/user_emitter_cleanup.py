"""Exception-cleanup registration for monomorphized generic bodies."""

from ...nodes import (
    IRExprStmt,
    IRLiteral,
    IRStmt,
    IRVar,
)


def register_exception_cleanup(
    emitter,
    name: str,
    type_name: str,
    statements: list[IRStmt],
) -> None:
    if not exception_cleanup_active(emitter):
        return
    mark_cleanup_registration(emitter)
    from ..cleanup_slots import register_cleanup_slot, require_cleanup_slot_declaration

    declaration = require_cleanup_slot_declaration(statements, name)
    from ..arc_cycles import managed_type_has_visitor
    from ..cycle_metadata import cycle_visitor_symbol
    from ..managed_values import STRING_RUNTIME_NAME, cleanup_destroy_symbol

    destroy = cleanup_destroy_symbol(type_name)
    if type_name == STRING_RUNTIME_NAME:
        emitter._gen.use_helper(destroy)
        statements.append(
            IRExprStmt(
                expr=register_cleanup_slot(
                    emitter._gen,
                    declaration,
                    IRVar(name=destroy),
                    direct=True,
                )
            )
        )
        return
    visitor = (
        IRVar(name=cycle_visitor_symbol(type_name))
        if managed_type_has_visitor(emitter._gen, type_name)
        else IRLiteral(text="NULL")
    )
    statements.append(
        IRExprStmt(
            expr=register_cleanup_slot(
                emitter._gen,
                declaration,
                IRVar(name=destroy),
                visitor=visitor,
            )
        )
    )


def mark_cleanup_registration(emitter) -> None:
    """Activate the generic body's innermost cleanup baseline."""
    if emitter._cleanup_scope_markers:
        marker = emitter._cleanup_scope_markers[-1]
        if marker is not None:
            emitter._active_cleanup_markers.add(marker)


def exception_cleanup_active(emitter) -> bool:
    """Whether this generic body can unwind into a live try frame."""
    return bool(emitter._gen is not None and (emitter._try_depth > 0 or emitter._gen.cross_function_cleanup_enabled))


__all__ = [
    "exception_cleanup_active",
    "mark_cleanup_registration",
    "register_exception_cleanup",
]
