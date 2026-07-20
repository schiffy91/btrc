"""Lexical ARC scopes for monomorphized generic method bodies."""

from __future__ import annotations

from ...nodes import IRBinOp, IRCall, IRExprStmt, IRLiteral, IRStmt, IRVar
from ..arc import _emit_scope_release
from ..cleanup_scopes import cleanup_scope_exit
from ..managed_local import ManagedLocal
from ..try_stack import pop_try_frames
from .user_emitter_bindings import (
    declare_source_binding,
    reset_source_bindings,
    source_binding_c_name,
)
from .user_emitter_cleanup import (
    exception_cleanup_active,
    mark_cleanup_registration,
    register_exception_cleanup,
)
from .user_emitter_scope_frames import (
    complete_generic_scope,
    enter_generic_scope,
    leave_generic_scope,
)


def reset_scope_state(emitter) -> None:
    """Reset ownership state at one generated function boundary."""
    emitter._managed_vars_stack = []
    emitter._local_ownership_scopes = []
    emitter._cleanup_scope_markers = []
    emitter._active_cleanup_markers = set()
    emitter._control_managed_depths = []
    emitter._control_cleanup_depths = []
    reset_source_bindings(emitter)
    from .user_callable_provenance import reset_generic_callable_state

    reset_generic_callable_state(emitter)


def emit_scoped_stmts(emitter, statements, *, iteration_bindings=()) -> list[IRStmt]:
    """Emit one lexical block and release its owned locals on normal exit."""
    from .user_callable_provenance import seed_borrowed_callable_parameters

    seed_borrowed_callable_parameters(emitter)
    frame = enter_generic_scope(emitter)
    result = []
    try:
        if iteration_bindings:
            from .user_emitter_iteration_arc import (
                emit_iteration_bindings,
            )

            result.extend(emit_iteration_bindings(emitter, iteration_bindings))
        for statement in statements:
            result.extend(emitter._stmt(statement))
        return complete_generic_scope(emitter, frame, result)
    finally:
        leave_generic_scope(emitter, frame)


def declare_local(emitter, name: str) -> str:
    """Record a lexical declaration, including borrowed shadowing slots."""
    c_name = declare_source_binding(emitter, name)
    if emitter._local_ownership_scopes:
        emitter._local_ownership_scopes[-1][name] = None
    return c_name


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
    c_name = source_binding_c_name(emitter, name)
    emitter._managed_vars_stack[-1].append(
        ManagedLocal(
            name,
            type_name,
            cycle_seed,
            c_name=c_name,
        )
    )
    emitter._local_ownership_scopes[-1][name] = type_name
    register_exception_cleanup(
        emitter,
        c_name,
        type_name,
        statements,
    )


def managed_local_type(emitter, name: str) -> str | None:
    for scope in reversed(emitter._local_ownership_scopes):
        if name in scope:
            return scope[name]
    return None


def emit_return_release(emitter, returned_name: str | None) -> list[IRStmt]:
    """Release every live local owner except the reference being transferred."""
    managed = _all_managed(emitter)
    returned_c_name = source_binding_c_name(emitter, returned_name) if returned_name is not None else None
    managed = [local for local in managed if (local.c_name or local.name) != returned_c_name]
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


def _all_managed(emitter) -> list[ManagedLocal]:
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
