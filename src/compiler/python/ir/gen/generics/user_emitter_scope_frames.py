"""Reusable lexical ownership frames for generic method lowering."""

from __future__ import annotations

from dataclasses import dataclass

from ...nodes import IRStmt
from ..cleanup_scopes import cleanup_scope_entry, cleanup_scope_exit
from .user_emitter_bindings import (
    pop_source_binding_scope,
    push_source_binding_scope,
)


@dataclass(frozen=True)
class GenericScopeFrame:
    """Compiler state owned by one source-level lexical block."""

    outer_types: dict
    enclosing_callables: object
    cleanup_marker: str | None


def enter_generic_scope(emitter) -> GenericScopeFrame:
    """Open one source, callable, ownership, and cleanup scope."""
    from .user_callable_provenance import begin_callable_scope

    marker = emitter._fresh_temp("__btrc_cleanup_scope") if emitter.exception_cleanup_active() else None
    frame = GenericScopeFrame(
        outer_types=emitter._var_types.copy(),
        enclosing_callables=begin_callable_scope(emitter),
        cleanup_marker=marker,
    )
    emitter._managed_vars_stack.append([])
    emitter._local_ownership_scopes.append({})
    push_source_binding_scope(emitter)
    emitter._cleanup_scope_markers.append(marker)
    return frame


def complete_generic_scope(
    emitter,
    frame: GenericScopeFrame,
    statements: list[IRStmt],
) -> list[IRStmt]:
    """Append normal cleanup and materialize an active cleanup baseline."""
    from ...completion import StatementSequence

    sequence = StatementSequence(statements)
    falls_through = sequence.may_fall_through()
    if falls_through:
        statements.extend(emitter._boundary_lifetime.release_scope(emitter._managed_vars_stack[-1]))
    marker = frame.cleanup_marker
    marker_referenced = falls_through or sequence.references_variable(marker or "")
    if marker in emitter._active_cleanup_markers and marker_referenced:
        statements[:0] = cleanup_scope_entry(emitter._gen, marker)
        if falls_through:
            statements.extend(cleanup_scope_exit(emitter._gen, marker))
    return statements


def leave_generic_scope(emitter, frame: GenericScopeFrame) -> None:
    """Restore compiler state after a lexical scope has been lowered."""
    from .user_callable_provenance import finish_callable_scope

    emitter._active_cleanup_markers.discard(frame.cleanup_marker)
    emitter._cleanup_scope_markers.pop()
    pop_source_binding_scope(emitter)
    emitter._local_ownership_scopes.pop()
    emitter._managed_vars_stack.pop()
    emitter._var_types = frame.outer_types
    finish_callable_scope(emitter, frame.enclosing_callables)


__all__ = [
    "GenericScopeFrame",
    "complete_generic_scope",
    "enter_generic_scope",
    "leave_generic_scope",
]
