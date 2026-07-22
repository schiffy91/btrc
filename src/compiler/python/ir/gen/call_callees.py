"""Helpers for callable expression callees."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ...ast_nodes import Identifier, TypeExpr
from ..nodes import CType, IRBinOp, IRCall, IRCommaExpr, IRExpr, IRStmtExpr, IRVar, IRVarDecl
from .type_resolution import function_pointer_signature
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def callable_callee_type(
    gen: IRGenerator,
    callee_node: object,
) -> TypeExpr | None:
    """Return the analyzed type of an expression-capable callee."""
    callee_type = gen.analyzed.node_types.get(id(callee_node))
    if callee_type is None and isinstance(callee_node, Identifier):
        callee_type = gen._callable_types.get(callee_node.name)
        if callee_type is None:
            callee_type = gen.analyzed.global_var_types.get(callee_node.name)
    return callee_type


def callable_callee_signature(
    gen: IRGenerator,
    callee_node: object,
) -> list[TypeExpr] | None:
    """Resolve a callable expression's canonical function-pointer shape."""
    return function_pointer_signature(
        callable_callee_type(gen, callee_node),
        gen.analyzed.typedef_table,
    )


def callable_value_identifier_signature(
    gen: IRGenerator,
    callee_node: object,
) -> list[TypeExpr] | None:
    """Resolve only lexical/global callable values, never function symbols."""
    if not isinstance(callee_node, Identifier):
        return None
    if callee_node.name in gen._fn_ptr_envs:
        return None
    if not (gen.local_ownership_declared(callee_node.name) or callee_node.name in gen.analyzed.global_var_types):
        return None
    return callable_callee_signature(gen, callee_node)


def materialize_callable_callee(
    gen: IRGenerator,
    callee_node: object,
    callee: IRExpr,
    signature: list[TypeExpr],
    args: list[IRExpr],
    *,
    callee_materialized: bool = False,
    fresh_temp: Callable[[str], str] | None = None,
    record_decl: Callable[[IRVarDecl], None] | None = None,
) -> IRExpr:
    """Evaluate a complex function-pointer callee before applying arguments."""
    if callee_materialized or not args or id(callee_node) in gen._owning_temp_overrides:
        return IRCall(callee=callee, args=args)
    temp = (fresh_temp or gen.fresh_temp)("__btrc_callable")
    temp_var = IRVar(name=temp)
    callable_type = TypeExpr(base="__fn_ptr", generic_args=signature)
    declaration = IRVarDecl(c_type=CType(text=type_to_c(callable_type)), name=temp)
    (record_decl or gen._func_var_decls.append)(declaration)
    return IRStmtExpr(
        stmts=[declaration],
        result=IRCommaExpr(
            expressions=[
                IRBinOp(left=temp_var, op="=", right=callee),
                IRCall(callee=temp_var, args=args),
            ],
        ),
    )


def lower_callee_expression(
    gen: IRGenerator,
    callee_node: object,
    args: list[IRExpr],
) -> IRExpr:
    """Lower and invoke a non-function-symbol callee with stable selection."""
    from .expressions import lower_expr

    callee = lower_expr(gen, callee_node)
    signature = callable_callee_signature(gen, callee_node)
    if signature is None:
        return IRCall(callee=callee, args=args)
    return materialize_callable_callee(gen, callee_node, callee, signature, args)


__all__ = [
    "callable_callee_signature",
    "callable_callee_type",
    "callable_value_identifier_signature",
    "lower_callee_expression",
    "materialize_callable_callee",
]
