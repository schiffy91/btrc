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
    from .user_emitter_scopes import register_managed_local

    if not emitter._owns_expr(expression):
        prefix.append(
            IRExprStmt(
                expr=emitter._boundary_lifetime.retain_value(
                    IRVar(name=name),
                    type_expr,
                )
            )
        )

    owner = ManagedLocal(
        name=name,
        type_name=emitter._gen.managed_values.runtime_name(type_expr),
        cycle_seed=not emitter._gen.managed_values.is_string(type_expr),
        c_name=name,
    )
    register_managed_local(emitter, name, type_expr, owner.cycle_seed, prefix)
    return owner


def finish_owned_iterable(emitter, owner) -> list[IRStmt]:
    """Release a synthetic iterable on exhaustion/break without double ARC."""
    if owner is None:
        return []
    owner_c_name = owner.c_name or owner.name
    for scope in emitter._managed_vars_stack:
        scope[:] = [local for local in scope if (local.c_name or local.name) != owner_c_name]
    for scope in reversed(emitter._local_ownership_scopes):
        if owner.name in scope:
            del scope[owner.name]
            break

    result = emitter._boundary_lifetime.release_scope([owner])
    result.append(
        IRAssign(
            target=IRVar(name=owner_c_name),
            value=IRLiteral(text="NULL"),
        )
    )
    return result


def emit_iteration_bindings(emitter, bindings) -> list[IRStmt]:
    """Declare protocol results as per-iteration local owners."""
    from .user_emitter_scopes import declare_local, register_managed_local

    result = []
    for binding in bindings:
        binding_c_name = declare_local(emitter, binding.name)
        emitter._var_types[binding.name] = binding.type_expr
        from .user_callable_provenance import bind_generic_local_callable

        bind_generic_local_callable(
            emitter,
            binding.name,
            binding.type_expr,
            None,
        )
        declaration = IRVarDecl(
            c_type=CType(text=binding.c_type),
            name=binding_c_name,
            init=binding.value,
        )
        emitter._func_var_decls.append(declaration)
        result.append(declaration)
        # Synthetic iteration bindings are part of the source contract even
        # when the body ignores them.  Represent that intentional discard as
        # IR so strict C builds do not diagnose an unused local.
        result.append(IRExprStmt(expr=IRVar(name=binding_c_name)))
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
