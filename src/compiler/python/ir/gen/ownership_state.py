"""Ownership and exception-cleanup state for IR generation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .feature_scan import program_uses_trycatch
from .managed_local import ManagedLocal

if TYPE_CHECKING:
    from ...analyzer.core import AnalyzedProgram


class _OwnershipStateMixin:
    """Track managed locals and the control paths that must release them."""

    def _init_ownership_state(self, analyzed: AnalyzedProgram, *, freestanding: bool) -> None:
        # A callee cannot know whether its caller owns the active setjmp frame.
        # Exception-capable modules therefore register every managed local with
        # the dynamic cleanup stack, including lexical callees that contain no
        # try statement themselves. This contract is identical in freestanding
        # code because the runtime seam explicitly supports setjmp/longjmp.
        self.program_has_exceptions = program_uses_trycatch(analyzed.program)
        self.cross_function_cleanup_enabled = self.program_has_exceptions
        self._managed_vars_stack: list[list[ManagedLocal]] = []
        # Explicit None entries keep a borrowed inner declaration from finding
        # an owned outer declaration with the same name.
        self._local_ownership_scopes: list[dict[str, str | None]] = []
        self._loop_scope_depths: list[int] = []
        self._control_context: list[str] = []
        self._control_managed_depths: list[int] = []
        self._cleanup_scope_markers: list[str | None] = []
        self._active_cleanup_markers: set[str] = set()
        self._control_cleanup_depths: list[int] = []
        self.in_try_depth = 0
        self.in_trycatch_depth = 0
        self._func_var_decls: list = []

    # Control targets -------------------------------------------------

    def push_control_context(self, kind: str) -> None:
        self._control_context.append(kind)
        self._control_managed_depths.append(len(self._managed_vars_stack))
        self._control_cleanup_depths.append(len(self._cleanup_scope_markers))

    def pop_control_context(self) -> None:
        if self._control_context:
            self._control_context.pop()
            self._control_managed_depths.pop()
            self._control_cleanup_depths.pop()

    def exited_try_depth(self, targets: set[str]) -> int:
        """Return try frames crossed before the nearest control target."""
        depth = 0
        for kind in reversed(self._control_context):
            if kind in targets:
                return depth
            if kind == "try":
                depth += 1
        return 0

    def get_control_managed_vars(self, targets: set[str]) -> list[ManagedLocal]:
        """Return managed locals exited by the nearest control target."""
        for index in range(len(self._control_context) - 1, -1, -1):
            if self._control_context[index] not in targets:
                continue
            scope_depth = self._control_managed_depths[index]
            result: list[ManagedLocal] = []
            for scope in self._managed_vars_stack[scope_depth:]:
                result.extend(scope)
            return result
        return []

    # Dynamic exception-cleanup registrations ------------------------

    def push_cleanup_scope(self) -> str | None:
        """Track a lexical scope's exception-cleanup baseline."""
        marker = self.fresh_temp("__btrc_cleanup_scope") if self.exception_cleanup_active() else None
        self._cleanup_scope_markers.append(marker)
        return marker

    def pop_cleanup_scope(self) -> None:
        if self._cleanup_scope_markers:
            marker = self._cleanup_scope_markers.pop()
            if marker is not None:
                self._active_cleanup_markers.discard(marker)

    def mark_cleanup_registration(self) -> None:
        """Activate the baseline for a slot registered in this block."""
        if self._cleanup_scope_markers:
            marker = self._cleanup_scope_markers[-1]
            if marker is not None:
                self._active_cleanup_markers.add(marker)

    def cleanup_scope_is_active(self, marker: str | None) -> bool:
        return marker is not None and marker in self._active_cleanup_markers

    def exception_cleanup_active(self) -> bool:
        """Return whether slots here can unwind into a live try frame."""
        return self.in_try_depth > 0 or self.cross_function_cleanup_enabled

    def get_control_cleanup_marker(self, targets: set[str]) -> str | None:
        """Return the oldest cleanup marker exited by a control transfer."""
        for index in range(len(self._control_context) - 1, -1, -1):
            if self._control_context[index] not in targets:
                continue
            depth = self._control_cleanup_depths[index]
            return next(
                (marker for marker in self._cleanup_scope_markers[depth:] if self.cleanup_scope_is_active(marker)),
                None,
            )
        return None

    def get_return_cleanup_marker(self) -> str | None:
        """Return the oldest cleanup baseline in the current function."""
        return next(
            (marker for marker in self._cleanup_scope_markers if self.cleanup_scope_is_active(marker)),
            None,
        )

    # Managed lexical locals -----------------------------------------

    def push_managed_scope(self) -> None:
        self._managed_vars_stack.append([])

    def pop_managed_scope(self) -> list[ManagedLocal]:
        if self._managed_vars_stack:
            return self._managed_vars_stack.pop()
        return []

    def register_managed_var(self, var_name: str, class_type: str, *, cycle_seed: bool) -> None:
        if self._managed_vars_stack:
            self._managed_vars_stack[-1].append(ManagedLocal(var_name, class_type, cycle_seed))

    def register_thread_var(self, var_name: str) -> None:
        """Register one unique joinable owner for structured scope cleanup."""
        if self._managed_vars_stack:
            self._managed_vars_stack[-1].append(ManagedLocal(var_name, "", False, cleanup_kind="thread"))

    def local_cleanup_kind(self, var_name: str) -> str | None:
        for scope in reversed(self._managed_vars_stack):
            for local in reversed(scope):
                if local.name == var_name:
                    return local.cleanup_kind
        return None

    def push_local_ownership_scope(self) -> None:
        self._local_ownership_scopes.append({})

    def pop_local_ownership_scope(self) -> None:
        if self._local_ownership_scopes:
            self._local_ownership_scopes.pop()

    def declare_local_ownership(self, var_name: str, class_type: str | None = None) -> None:
        if self._local_ownership_scopes:
            self._local_ownership_scopes[-1][var_name] = class_type

    def managed_local_type(self, var_name: str) -> str | None:
        for scope in reversed(self._local_ownership_scopes):
            if var_name in scope:
                return scope[var_name]
        return None

    def local_ownership_declared(self, var_name: str) -> bool:
        """Whether a lexical binding shadows a same-named module global."""
        return any(var_name in scope for scope in reversed(self._local_ownership_scopes))

    def unregister_managed_var(self, var_name: str) -> None:
        """Stop automatic destruction after an explicit free/delete."""
        for scope in self._managed_vars_stack:
            scope[:] = [local for local in scope if local.name != var_name]
        for scope in reversed(self._local_ownership_scopes):
            if var_name in scope:
                scope[var_name] = None
                break

    def get_all_managed_vars(self) -> list[ManagedLocal]:
        result: list[ManagedLocal] = []
        for scope in self._managed_vars_stack:
            result.extend(scope)
        return result

    def push_loop_scope(self) -> None:
        self._loop_scope_depths.append(len(self._managed_vars_stack))

    def pop_loop_scope(self) -> None:
        if self._loop_scope_depths:
            self._loop_scope_depths.pop()

    def get_loop_managed_vars(self) -> list[ManagedLocal]:
        if not self._loop_scope_depths:
            return []
        result: list[ManagedLocal] = []
        for scope in self._managed_vars_stack[self._loop_scope_depths[-1] :]:
            result.extend(scope)
        return result
