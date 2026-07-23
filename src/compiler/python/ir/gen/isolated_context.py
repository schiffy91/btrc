"""State isolation for lowering nested bodies that become separate C functions."""

from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def isolated_function_context(gen, return_c_type, return_type):
    """Prevent a lambda/thread wrapper from inheriting outer control state."""
    saved = (
        gen._managed_vars_stack,
        gen.context.local_ownership_scopes,
        gen._local_c_name_scopes,
        gen._loop_scope_depths,
        gen._control_context,
        gen._control_managed_depths,
        gen._cleanup_scope_markers,
        gen._active_cleanup_markers,
        gen._control_cleanup_depths,
        gen.in_try_depth,
        gen.in_trycatch_depth,
        gen.context.function_declarations,
        gen.current_return_c_type,
        gen.current_return_type,
        gen.current_return_owned,
        gen.context.callable_environments,
        gen.context.callable_return_abis,
        gen._callable_scope_declarations,
        gen._callable_exception_captures,
        gen._callable_loop_captures,
        gen._last_lambda_id,
        gen.context.owning_overrides,
        gen.context.type_overrides,
        gen._normalizing_void_main,
        gen._c_array_scopes,
    )
    gen._managed_vars_stack = []
    gen.context.local_ownership_scopes = []
    gen._local_c_name_scopes = []
    gen._loop_scope_depths = []
    gen._control_context = []
    gen._control_managed_depths = []
    gen._cleanup_scope_markers = []
    gen._active_cleanup_markers = set()
    gen._control_cleanup_depths = []
    gen.in_try_depth = 0
    gen.in_trycatch_depth = 0
    gen.context.function_declarations = []
    gen.current_return_c_type = return_c_type
    gen.current_return_type = return_type
    gen.current_return_owned = True
    gen.context.callable_environments = {}
    gen.context.callable_return_abis = {}
    gen._callable_scope_declarations = []
    gen._callable_exception_captures = []
    gen._callable_loop_captures = []
    gen._last_lambda_id = 0
    gen.context.owning_overrides = {}
    gen.context.type_overrides = {}
    gen._normalizing_void_main = False
    gen._c_array_scopes = []
    try:
        yield
    finally:
        (
            gen._managed_vars_stack,
            gen.context.local_ownership_scopes,
            gen._local_c_name_scopes,
            gen._loop_scope_depths,
            gen._control_context,
            gen._control_managed_depths,
            gen._cleanup_scope_markers,
            gen._active_cleanup_markers,
            gen._control_cleanup_depths,
            gen.in_try_depth,
            gen.in_trycatch_depth,
            gen.context.function_declarations,
            gen.current_return_c_type,
            gen.current_return_type,
            gen.current_return_owned,
            gen.context.callable_environments,
            gen.context.callable_return_abis,
            gen._callable_scope_declarations,
            gen._callable_exception_captures,
            gen._callable_loop_captures,
            gen._last_lambda_id,
            gen.context.owning_overrides,
            gen.context.type_overrides,
            gen._normalizing_void_main,
            gen._c_array_scopes,
        ) = saved
