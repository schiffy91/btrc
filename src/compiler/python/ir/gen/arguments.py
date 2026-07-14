"""Call argument helpers: named argument ordering and default values."""

from __future__ import annotations

from dataclasses import replace

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


def bind_arg_nodes_to_params(
    params: list,
    ast_args: list,
    arg_names: list[str],
) -> list[tuple[int | None, object, bool]]:
    """Bind explicit arguments, then omitted defaults, without lowering.

    Explicit nodes stay in source evaluation order. Omitted defaults follow in
    parameter order. The boolean marks synthesized default arguments.
    """
    if not params:
        return [(None, argument, False) for argument in ast_args]

    names = list(arg_names or [])
    names.extend([""] * (len(ast_args) - len(names)))
    param_indices = {param.name: index for index, param in enumerate(params)}
    positional_index = 0
    bound: set[int] = set()
    result: list[tuple[int | None, object, bool]] = []
    for index, argument in enumerate(ast_args):
        name = names[index]
        if name:
            param_index = param_indices.get(name)
        else:
            param_index = positional_index
            positional_index += 1
        if param_index is not None and param_index < len(params):
            bound.add(param_index)
        result.append((param_index, argument, False))

    for index, param in enumerate(params):
        if index not in bound and param.default is not None:
            result.append((index, param.default, True))
    return result


def lower_arg_values(gen, args: list) -> list[IRExpr]:
    from .expressions import lower_expr

    return [lower_expr(gen, arg) for arg in args]


def resolved_constructor_params(cls_info, instance_type):
    """Resolve class type parameters in one constructor signature."""
    params = cls_info.constructor.params
    if not (instance_type.generic_args and cls_info.generic_params):
        return params

    from .generics.core import _resolve_type

    type_map = dict(zip(cls_info.generic_params, instance_type.generic_args))
    return [replace(param, type=_resolve_type(param.type, type_map)) for param in params]


def order_args_for_params(
    gen, params: list, ast_args: list, arg_names: list[str], ir_args: list[IRExpr] | None = None
) -> list[IRExpr]:
    """Return IR args in parameter order, filling omitted defaults.

    Positional-only calls keep their original order and append trailing
    defaults. Named calls can skip optional middle parameters because the result
    is expanded to the full declared parameter list.
    """
    _, result = order_args_and_nodes_for_params(
        gen,
        params,
        ast_args,
        arg_names,
        ir_args,
    )
    return result


def order_args_and_nodes_for_params(
    gen,
    params: list,
    ast_args: list,
    arg_names: list[str],
    ir_args: list[IRExpr] | None = None,
    *,
    reject_missing: bool = False,
) -> tuple[list, list[IRExpr]]:
    """Order both AST and lowered values, retaining defaults as metadata."""

    from .expressions import lower_expr

    if ir_args is None:
        ir_args = lower_arg_values(gen, ast_args)
    if not params:
        return list(ast_args), ir_args

    names = list(arg_names or [])
    while len(names) < len(ast_args):
        names.append("")

    if not any(names):
        result = list(ir_args)
        ast_result = list(ast_args)
        for index in range(len(result), len(params)):
            default = params[index].default
            if default is None and reject_missing:
                _raise_missing(params[index].name)
            result.append(lower_expr(gen, default) if default is not None else IRLiteral(text="0"))
            ast_result.append(default)
        return ast_result, [
            _coerce_arg(gen, params[index].type, ast_result[index], result[index]) for index in range(len(result))
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
            if param.default is None and reject_missing:
                _raise_missing(param.name)
            result[index] = lower_expr(gen, param.default) if param.default is not None else IRLiteral(text="0")
            ast_result[index] = param.default
    return ast_result, [
        _coerce_arg(gen, params[index].type, ast_result[index], arg)
        for index, arg in enumerate(result)
        if arg is not None
    ]


def _raise_missing(parameter_name: str) -> None:
    from .errors import CodegenError

    raise CodegenError(f"missing required argument for parameter '{parameter_name}'")


def param_index_for_written_arg(params: list, arg_position: int, arg_names: list[str]) -> int:
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
