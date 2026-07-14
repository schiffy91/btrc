"""Lexical ARC scopes for monomorphized generic method bodies."""

from __future__ import annotations

from ...nodes import IRBinOp, IRCall, IRExprStmt, IRLiteral, IRStmt, IRVar
from ..arc import _emit_scope_release
from ..cleanup_scopes import cleanup_scope_entry, cleanup_scope_exit
from ..managed_local import ManagedLocal
from ..try_stack import pop_try_frames
from .user_emitter_cleanup import (
    exception_cleanup_active,
    mark_cleanup_registration,
    register_exception_cleanup,
)


def reset_scope_state(emitter) -> None:
    """Reset ownership state at one generated function boundary."""
    emitter._managed_vars_stack = []
    emitter._local_ownership_scopes = []
    emitter._cleanup_scope_markers = []
    emitter._active_cleanup_markers = set()
    emitter._control_managed_depths = []
    emitter._control_cleanup_depths = []


def emit_scoped_stmts(emitter, statements, *, iteration_bindings=()) -> list[IRStmt]:
    """Emit one lexical block and release its owned locals on normal exit."""
    outer_types = emitter._var_types.copy()
    marker = emitter._fresh_temp("__btrc_cleanup_scope") if exception_cleanup_active(emitter) else None
    emitter._managed_vars_stack.append([])
    emitter._local_ownership_scopes.append({})
    emitter._cleanup_scope_markers.append(marker)
    result = []
    try:
        if iteration_bindings:
            from .user_emitter_iteration_arc import (
                emit_iteration_bindings,
            )

            result.extend(emit_iteration_bindings(emitter, iteration_bindings))
        for statement in statements:
            result.extend(emitter._stmt(statement))
        from ...completion import (
            sequence_may_fall_through,
            sequence_references_variable,
        )

        falls_through = sequence_may_fall_through(result)
        if falls_through:
            result.extend(_emit_scope_release(emitter._managed_vars_stack[-1], emitter._gen))
        marker_referenced = falls_through or sequence_references_variable(result, marker or "")
        if marker in emitter._active_cleanup_markers and marker_referenced:
            result[:0] = cleanup_scope_entry(emitter._gen, marker)
            if falls_through:
                result.extend(cleanup_scope_exit(emitter._gen, marker))
        return result
    finally:
        emitter._active_cleanup_markers.discard(marker)
        emitter._cleanup_scope_markers.pop()
        emitter._local_ownership_scopes.pop()
        emitter._managed_vars_stack.pop()
        emitter._var_types = outer_types


def declare_local(emitter, name: str) -> None:
    """Record a lexical declaration, including borrowed shadowing slots."""
    if emitter._local_ownership_scopes:
        emitter._local_ownership_scopes[-1][name] = None


def register_managed_local(
    emitter,
    name: str,
    resolved_type,
    cycle_seed: bool,
    statements: list[IRStmt],
) -> None:
    """Make a caller-owned initializer the reference owned by this block."""
    if not emitter._is_managed_type(resolved_type) or not emitter._managed_vars_stack:
        return
    from ..managed_values import runtime_name

    type_name = runtime_name(emitter._gen, resolved_type)
    emitter._managed_vars_stack[-1].append(ManagedLocal(name, type_name, cycle_seed))
    emitter._local_ownership_scopes[-1][name] = type_name
    register_exception_cleanup(emitter, name, type_name, statements)


def managed_local_type(emitter, name: str) -> str | None:
    for scope in reversed(emitter._local_ownership_scopes):
        if name in scope:
            return scope[name]
    return None


def emit_return_release(emitter, returned_name: str | None) -> list[IRStmt]:
    """Release every live local owner except the reference being transferred."""
    managed = _all_managed(emitter)
    if returned_name is not None:
        for index in range(len(managed) - 1, -1, -1):
            if managed[index].name == returned_name:
                del managed[index]
                break
    return _emit_scope_release(managed, emitter._gen)


def emit_return_cleanup_discard(emitter) -> list[IRStmt]:
    """Forget every cleanup slot owned by the current generic function."""
    marker = next(
        (value for value in emitter._cleanup_scope_markers if value in emitter._active_cleanup_markers),
        None,
    )
    return cleanup_scope_exit(emitter._gen, marker) if marker else []


def push_control_context(emitter, kind: str) -> None:
    emitter._control_context.append(kind)
    emitter._control_managed_depths.append(len(emitter._managed_vars_stack))
    emitter._control_cleanup_depths.append(len(emitter._cleanup_scope_markers))


def pop_control_context(emitter) -> None:
    emitter._control_context.pop()
    emitter._control_managed_depths.pop()
    emitter._control_cleanup_depths.pop()


def emit_control_release(emitter, targets: set[str]) -> list[IRStmt]:
    """Release exactly the scopes exited by break or continue."""
    depth = _control_depth(emitter, targets, emitter._control_managed_depths)
    if depth is None:
        return []
    managed = []
    for scope in emitter._managed_vars_stack[depth:]:
        managed.extend(scope)
    return _emit_scope_release(managed, emitter._gen, force=True)


def emit_control_cleanup_discard(emitter, targets: set[str]) -> list[IRStmt]:
    """Discard registrations belonging to scopes exited by control flow."""
    depth = _control_depth(emitter, targets, emitter._control_cleanup_depths)
    if depth is None:
        return []
    marker = next(
        (value for value in emitter._cleanup_scope_markers[depth:] if value in emitter._active_cleanup_markers),
        None,
    )
    if marker is None:
        return []
    return cleanup_scope_exit(emitter._gen, marker)


def emit_try_pop(emitter, depth: int) -> list[IRStmt]:
    """Discard exception cleanups and pop active frames bypassed by an exit."""
    if depth <= 0:
        return []
    result = []
    if emitter._gen and emitter._gen._used_helpers & {
        "__btrc_register_cleanup",
        "__btrc_register_direct_cleanup",
    }:
        emitter._gen.use_helper("__btrc_discard_cleanups")
        level = IRVar(name="__btrc_try_top")
        if depth > 1:
            level = IRBinOp(
                left=level,
                op="-",
                right=IRLiteral(text=str(depth - 1)),
            )
        result.append(
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_discard_cleanups",
                    args=[level],
                    helper_ref="__btrc_discard_cleanups",
                )
            )
        )
    result.extend(pop_try_frames(depth))
    return result


def _all_managed(emitter) -> list[tuple[str, str]]:
    result = []
    for scope in emitter._managed_vars_stack:
        result.extend(scope)
    return result


def _control_depth(emitter, targets, depths):
    for index in range(len(emitter._control_context) - 1, -1, -1):
        if emitter._control_context[index] in targets:
            return depths[index]
    return None


__all__ = [
    "declare_local",
    "emit_control_cleanup_discard",
    "emit_control_release",
    "emit_return_cleanup_discard",
    "emit_return_release",
    "emit_scoped_stmts",
    "emit_try_pop",
    "exception_cleanup_active",
    "managed_local_type",
    "mark_cleanup_registration",
    "pop_control_context",
    "push_control_context",
    "register_managed_local",
    "reset_scope_state",
]
