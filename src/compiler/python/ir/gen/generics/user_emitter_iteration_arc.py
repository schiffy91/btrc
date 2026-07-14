"""Owned synthetic iterable lifetimes in generic specializations."""

from __future__ import annotations

from ...nodes import CType, IRAssign, IRExprStmt, IRLiteral, IRStmt, IRVar, IRVarDecl
from ..managed_local import ManagedLocal


def begin_owned_iterable(
    emitter,
    expression,
    type_expr,
    name: str,
    prefix: list[IRStmt],
) -> ManagedLocal | None:
    """Own a fresh or borrowed iterable until every loop exit is lowered."""
    if not emitter._is_managed_type(type_expr):
        return None
    from ..managed_values import is_string_type, retain_value, runtime_name
    from .user_emitter_scopes import register_managed_local

    if not emitter._owns_expr(expression):
        prefix.append(
            IRExprStmt(
                expr=retain_value(
                    emitter._gen,
                    IRVar(name=name),
                    type_expr,
                )
            )
        )

    owner = ManagedLocal(
        name=name,
        type_name=runtime_name(emitter._gen, type_expr),
        cycle_seed=not is_string_type(emitter._gen, type_expr),
    )
    register_managed_local(emitter, name, type_expr, owner.cycle_seed, prefix)
    return owner


def finish_owned_iterable(emitter, owner) -> list[IRStmt]:
    """Release a synthetic iterable on exhaustion/break without double ARC."""
    if owner is None:
        return []
    for scope in emitter._managed_vars_stack:
        scope[:] = [local for local in scope if local.name != owner.name]
    for scope in reversed(emitter._local_ownership_scopes):
        if owner.name in scope:
            del scope[owner.name]
            break

    from ..arc import _emit_scope_release

    result = _emit_scope_release([owner], emitter._gen)
    result.append(
        IRAssign(
            target=IRVar(name=owner.name),
            value=IRLiteral(text="NULL"),
        )
    )
    return result


def emit_iteration_bindings(emitter, bindings) -> list[IRStmt]:
    """Declare protocol results as per-iteration local owners."""
    from .user_emitter_scopes import declare_local, register_managed_local

    result = []
    for binding in bindings:
        declare_local(emitter, binding.name)
        emitter._var_types[binding.name] = binding.type_expr
        declaration = IRVarDecl(
            c_type=CType(text=binding.c_type),
            name=binding.name,
            init=binding.value,
        )
        emitter._func_var_decls.append(declaration)
        result.append(declaration)
        if binding.owned and emitter._is_managed_type(binding.type_expr):
            register_managed_local(
                emitter,
                binding.name,
                binding.type_expr,
                True,
                result,
            )
    return result


__all__ = [
    "begin_owned_iterable",
    "emit_iteration_bindings",
    "finish_owned_iterable",
]
