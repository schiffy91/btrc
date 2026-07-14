"""GPU-call vocabulary shared by validation and WGSL emission."""

from __future__ import annotations

WGSL_FLOAT_UNARY_BUILTINS = frozenset(
    {
        "ceil",
        "cos",
        "exp",
        "floor",
        "log",
        "round",
        "sin",
        "sqrt",
        "tan",
    }
)

WGSL_SAME_TYPE_BUILTINS = frozenset({"abs", "clamp", "max", "min"})

WGSL_BUILTIN_ARITY = {
    "abs": 1,
    "ceil": 1,
    "clamp": 3,
    "cos": 1,
    "exp": 1,
    "floor": 1,
    "log": 1,
    "max": 2,
    "min": 2,
    "pow": 2,
    "round": 1,
    "sin": 1,
    "sqrt": 1,
    "tan": 1,
}

WGSL_CALL_BUILTINS = frozenset(WGSL_BUILTIN_ARITY)
