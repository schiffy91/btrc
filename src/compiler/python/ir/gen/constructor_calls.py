"""Explicit constructor-call lowering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import NewExpr
from ..nodes import IRCall
from .arguments import (
    arg_names_for,
    lower_arg_values,
    order_args_for_params,
    resolved_constructor_params,
)
from .arguments_arc import plan_call_operands
from .call_boundary import sequence_call_boundary
from .types import mangle_generic_type, type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_new_expr(gen: IRGenerator, node: NewExpr):
    """Lower an explicitly typed ``new Class<Args>(...)`` expression."""
    cls_info = gen.analyzed.class_table.get(node.type.base)
    params = []
    constructor = None
    if cls_info and cls_info.constructor:
        constructor = cls_info.constructor
        params = resolved_constructor_params(cls_info, node.type)
    from .call_effects import owned_transfer_param_indices

    operands, needs_boundary = plan_call_operands(
        gen,
        params,
        node.args,
        arg_names_for(node, len(node.args)),
        transferred_params=owned_transfer_param_indices(constructor),
    )
    if not needs_boundary:
        return _lower_new_plain(gen, node)

    def build_call(overrides):
        previous = {key: gen._owning_temp_overrides.get(key) for key in overrides}
        gen._owning_temp_overrides.update(overrides)
        try:
            return _lower_new_plain(gen, node)
        finally:
            for key, value in previous.items():
                if value is None:
                    gen._owning_temp_overrides.pop(key, None)
                else:
                    gen._owning_temp_overrides[key] = value

    result_type = gen.analyzed.node_types.get(id(node)) or node.type
    from .expressions import lower_expr

    return sequence_call_boundary(
        gen,
        operands,
        lower_expr=lambda value: lower_expr(gen, value),
        build_call=build_call,
        result_c_type=type_to_c(result_type),
        fresh_temp=gen.fresh_temp,
        cleanup_active=gen.exception_cleanup_active(),
        record_decl=gen._func_var_decls.append,
    )


def _lower_new_plain(gen: IRGenerator, node: NewExpr):
    """Lower a constructor after any managed operands are stabilized."""
    if node.type.base == "Mutex":
        from .call_builtins import lower_mutex_constructor

        args = lower_arg_values(gen, node.args)
        value_type = node.type.generic_args[0] if node.type.generic_args else None
        return lower_mutex_constructor(
            gen,
            node.args,
            args,
            value_type,
        )
    type_name = node.type.base
    if node.type.generic_args:
        type_name = mangle_generic_type(node.type.base, node.type.generic_args)
    args = lower_arg_values(gen, node.args)
    cls_info = gen.analyzed.class_table.get(node.type.base)
    if cls_info and cls_info.constructor:
        params = resolved_constructor_params(cls_info, node.type)
        args = order_args_for_params(
            gen,
            params,
            node.args,
            arg_names_for(node, len(node.args)),
            args,
        )
    return IRCall(callee=f"{type_name}_new", args=args)
