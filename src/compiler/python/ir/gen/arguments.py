"""Call argument helpers: named argument ordering and default values."""

from __future__ import annotations

from ..nodes import IRExpr, IRLiteral
from .stringable import coerce_to_string_param
from .upcast import upcast_class_pointer


def _coerce_arg(gen, target_type, ast_node, value: IRExpr) -> IRExpr:
    """Apply both string coercion and Derived→Base upcasting to one argument."""
    value = coerce_to_string_param(gen, target_type, ast_node, value)
    source_type = gen.analyzed.node_types.get(id(ast_node))
    return upcast_class_pointer(gen, target_type, source_type, value)


def arg_names_for(node, count: int) -> list[str]:
    names = list(getattr(node, "arg_names", []) or [])
    while len(names) < count:
        names.append("")
    return names


def has_named_args(node) -> bool:
    return any(arg_names_for(node, len(getattr(node, "args", []) or [])))


def lower_arg_values(gen, args: list) -> list[IRExpr]:
    from .expressions import lower_expr
    return [lower_expr(gen, arg) for arg in args]


def order_args_for_params(gen, params: list, ast_args: list,
                          arg_names: list[str],
                          ir_args: list[IRExpr] | None = None) -> list[IRExpr]:
    """Return IR args in parameter order, filling omitted defaults.

    Positional-only calls keep their original order and append trailing
    defaults. Named calls can skip optional middle parameters because the result
    is expanded to the full declared parameter list.
    """
    from .expressions import lower_expr

    if ir_args is None:
        ir_args = lower_arg_values(gen, ast_args)
    if not params:
        return ir_args

    names = list(arg_names or [])
    while len(names) < len(ast_args):
        names.append("")

    if not any(names):
        result = list(ir_args)
        ast_result = list(ast_args)
        for index in range(len(result), len(params)):
            default = params[index].default
            result.append(lower_expr(gen, default) if default is not None
                          else IRLiteral(text="0"))
            ast_result.append(default)
        return [
            _coerce_arg(gen, params[index].type, ast_result[index], result[index])
            for index in range(len(result))
        ]

    param_indices = {param.name: index for index, param in enumerate(params)}
    result: list[IRExpr | None] = [None] * len(params)
    ast_result: list[object | None] = [None] * len(params)
    positional_index = 0
    for index, arg in enumerate(ir_args):
        name = names[index]
        if name:
            param_index = param_indices.get(name)
            if param_index is not None:
                result[param_index] = arg
                ast_result[param_index] = ast_args[index]
            continue
        if positional_index < len(params):
            result[positional_index] = arg
            ast_result[positional_index] = ast_args[index]
            positional_index += 1

    for index, param in enumerate(params):
        if result[index] is None:
            result[index] = (lower_expr(gen, param.default)
                             if param.default is not None
                             else IRLiteral(text="0"))
            ast_result[index] = param.default
    return [
        _coerce_arg(gen, params[index].type, ast_result[index], arg)
        for index, arg in enumerate(result)
        if arg is not None
    ]


def param_index_for_written_arg(params: list, arg_position: int,
                                arg_names: list[str]) -> int:
    names = list(arg_names or [])
    while len(names) <= arg_position:
        names.append("")
    name = names[arg_position]
    if not name:
        return arg_position
    for index, param in enumerate(params):
        if param.name == name:
            return index
    return arg_position
