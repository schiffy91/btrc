"""Call, cast, and scalar-type contracts for WGSL-compatible GPU code."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..ast_nodes import CallExpr, CastExpr, Identifier, TypeExpr
from ..gpu_builtins import (
    WGSL_BUILTIN_ARITY,
    WGSL_CALL_BUILTINS,
    WGSL_FLOAT_UNARY_BUILTINS,
    WGSL_SAME_TYPE_BUILTINS,
)

if TYPE_CHECKING:
    from .gpu_exprs import GpuValidationContext


def validate_gpu_call(context: GpuValidationContext, call: CallExpr) -> None:
    from .gpu_exprs import validate_gpu_expr

    for argument in call.args:
        validate_gpu_expr(context, argument)
    if any(call.arg_names):
        context.error("WGSL built-ins do not accept named arguments", call)
    if not isinstance(call.callee, Identifier):
        context.error("indirect and method calls have no WGSL definition", call.callee)
        return
    name = call.callee.name
    if name == "gpu_id":
        if call.args:
            context.error("gpu_id() takes no arguments", call)
        return
    if context.knows(name) or name in context.analyzer.function_table:
        context.error(
            f"call to '{name}' has no WGSL definition because it resolves to a source symbol",
            call,
        )
        return
    if name not in WGSL_CALL_BUILTINS:
        context.error(
            f"call to '{name}' has no WGSL definition; only gpu_id() and WGSL built-ins are allowed",
            call,
        )
        return
    expected = WGSL_BUILTIN_ARITY[name]
    if len(call.args) != expected:
        context.error(f"{name}() expects {expected} argument(s), got {len(call.args)}", call)
        return
    argument_types = [context.type_of(argument) for argument in call.args]
    bases = [type_expr.base for type_expr in argument_types if type_expr is not None]
    if name in WGSL_FLOAT_UNARY_BUILTINS or name == "pow":
        if any(not is_gpu_scalar(type_expr, {"float"}) for type_expr in argument_types if type_expr is not None):
            context.error(f"{name}() requires float arguments in GPU functions", call)
        result_base = "float"
    elif name in WGSL_SAME_TYPE_BUILTINS:
        if any(not is_gpu_scalar(type_expr, {"int", "float"}) for type_expr in argument_types if type_expr is not None):
            context.error(f"{name}() requires int or float arguments in GPU functions", call)
        if bases and any(base != bases[0] for base in bases[1:]):
            context.error(f"{name}() arguments must have the same GPU scalar type", call)
        result_base = bases[0] if bases else "float"
    else:
        result_base = "float"
    context.analyzer.node_types[id(call)] = TypeExpr(base=result_base)


def validate_gpu_cast(context: GpuValidationContext, cast: CastExpr) -> None:
    target = cast.target_type
    if not is_gpu_scalar(target, {"int", "float", "bool"}):
        context.error(
            f"cast target '{context.analyzer._format_type(target)}' has no WGSL scalar representation",
            cast,
        )


def require_exact_gpu_type(
    context: GpuValidationContext,
    expression,
    allowed: set[str],
    role: str,
) -> None:
    type_expr = context.type_of(expression)
    if type_expr is not None and not is_gpu_scalar(type_expr, allowed):
        expected = " or ".join(sorted(allowed))
        context.error(f"{role} must be {expected}, got '{type_expr.base}'", expression)


def is_gpu_scalar(type_expr, allowed: set[str]) -> bool:
    return bool(
        type_expr.base in allowed
        and not type_expr.is_array
        and type_expr.pointer_depth == 0
        and not type_expr.generic_args
        and not type_expr.is_nullable
    )
