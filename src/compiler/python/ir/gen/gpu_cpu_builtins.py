"""C equivalents for WGSL built-ins used by void-kernel CPU fallback."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...gpu_builtins import WGSL_CALL_BUILTINS, WGSL_FLOAT_UNARY_BUILTINS
from ..nodes import IRBinOp, IRCall, IRTernary

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_gpu_cpu_builtin(gen: IRGenerator, name: str, ast_args: list, ir_args: list):
    if not getattr(gen, "_gpu_cpu_index", None) or name not in WGSL_CALL_BUILTINS:
        return None
    argument_types = [gen.analyzed.node_types.get(id(argument)) for argument in ast_args]
    base = argument_types[0].base if argument_types and argument_types[0] is not None else "float"
    if name == "abs":
        return IRCall(callee="fabsf" if base == "float" else "abs", args=ir_args)
    if name in WGSL_FLOAT_UNARY_BUILTINS:
        return IRCall(callee=f"{name}f", args=ir_args)
    if name == "pow":
        return IRCall(callee="powf", args=ir_args)
    if name in ("min", "max"):
        if base == "float":
            return IRCall(callee=f"f{name}f", args=ir_args)
        return _integer_extreme(name, ir_args[0], ir_args[1])
    if name == "clamp":
        if base == "float":
            return IRCall(
                callee="fminf",
                args=[IRCall(callee="fmaxf", args=ir_args[:2]), ir_args[2]],
            )
        return _integer_extreme(
            "min",
            _integer_extreme("max", ir_args[0], ir_args[1]),
            ir_args[2],
        )
    return None


def _integer_extreme(name: str, left, right):
    operator = "<" if name == "min" else ">"
    return IRTernary(
        condition=IRBinOp(left=left, op=operator, right=right),
        true_expr=left,
        false_expr=right,
    )
