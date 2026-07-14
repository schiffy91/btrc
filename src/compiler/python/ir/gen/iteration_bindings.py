"""Typed loop-binding prologues for structured ``for-in`` bodies."""

from __future__ import annotations

from dataclasses import dataclass

from ..nodes import CType, IRExpr, IRStmt, IRVarDecl


@dataclass(frozen=True)
class IterationBinding:
    """One value produced by ``iterGet``/``iterValueAt`` per iteration."""

    name: str
    c_type: str
    type_expr: object
    value: IRExpr
    owned: bool


def emit_iteration_bindings(gen, bindings) -> list[IRStmt]:
    """Declare bindings inside the body scope and register owned results."""
    result: list[IRStmt] = []
    for binding in bindings:
        gen.declare_local_ownership(binding.name)
        declaration = IRVarDecl(
            c_type=CType(text=binding.c_type),
            name=binding.name,
            init=binding.value,
        )
        gen._func_var_decls.append(declaration)
        result.append(declaration)

        type_expr = binding.type_expr
        from .managed_values import is_managed_type

        managed = binding.owned and is_managed_type(gen, type_expr)
        if managed:
            from .managed_values import is_string_type, runtime_name
            from .variables import _maybe_register_cleanup

            runtime_type = runtime_name(gen, type_expr)
            gen.register_managed_var(
                binding.name,
                runtime_type,
                cycle_seed=not is_string_type(gen, type_expr),
            )
            gen.declare_local_ownership(binding.name, runtime_type)
            _maybe_register_cleanup(gen, binding.name, runtime_type, result)
    return result


__all__ = ["IterationBinding", "emit_iteration_bindings"]
