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
from .types import CTypeRenderer, mangle_generic_type

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def lower_new_expr(
    gen: IRLowerer,
    node: NewExpr,
    type_renderer: CTypeRenderer,
    default_arguments,
):
    """Lower an explicitly typed ``new Class<Args>(...)`` expression."""
    instance_type = default_arguments.resolve_type(node.type) if default_arguments is not None else node.type
    cls_info = gen.analyzed.class_table.get(instance_type.base)
    params = []
    constructor = None
    if cls_info and cls_info.constructor:
        constructor = cls_info.constructor
        params = resolved_constructor_params(gen, cls_info, instance_type)
    elif instance_type.base == "Mutex" and instance_type.generic_args:
        from ...ast_nodes import Param

        params = [Param(type=instance_type.generic_args[0], name="value")]
    from ...ownership_effects import owned_transfer_param_indices

    operands, needs_boundary = gen.calls.operands.plan(
        params,
        node.args,
        arg_names_for(node, len(node.args)),
        transferred_params=owned_transfer_param_indices(constructor),
        call=node,
    )
    if not needs_boundary:
        return _lower_new_plain(
            gen,
            node,
            type_renderer,
            default_arguments,
        )

    def build_call(overrides):
        previous = {key: gen.context.owning_overrides.get(key) for key in overrides}
        gen.context.owning_overrides.update(overrides)
        try:
            return _lower_new_plain(
                gen,
                node,
                type_renderer,
                default_arguments,
            )
        finally:
            for key, value in previous.items():
                if value is None:
                    gen.context.owning_overrides.pop(key, None)
                else:
                    gen.context.owning_overrides[key] = value

    result_type = gen.analyzed.node_types.get(id(node)) or instance_type
    from .expressions import lower_expr

    return gen.ownership.boundaries.sequence(
        operands,
        lower_expr=lambda value: lower_expr(
            gen,
            value,
            type_renderer,
            default_arguments,
        ),
        build_call=build_call,
        result_c_type=type_renderer.render(result_type),
        result_type=result_type,
        result_owned=True,
    )


def _lower_new_plain(
    gen: IRLowerer,
    node: NewExpr,
    type_renderer: CTypeRenderer,
    default_arguments,
):
    """Lower a constructor after any managed operands are stabilized."""
    instance_type = default_arguments.resolve_type(node.type) if default_arguments is not None else node.type
    if instance_type.base == "Mutex":
        from .call_builtins import lower_mutex_constructor

        args = lower_arg_values(
            gen,
            node.args,
            type_renderer,
            default_arguments,
        )
        value_type = instance_type.generic_args[0] if instance_type.generic_args else None
        return lower_mutex_constructor(
            gen,
            node.args,
            args,
            type_renderer,
            value_type,
        )
    type_name = instance_type.base
    if instance_type.generic_args:
        type_name = mangle_generic_type(
            instance_type.base,
            instance_type.generic_args,
        )
    args = lower_arg_values(
        gen,
        node.args,
        type_renderer,
        default_arguments,
    )
    cls_info = gen.analyzed.class_table.get(instance_type.base)
    if cls_info and cls_info.constructor:
        params = resolved_constructor_params(gen, cls_info, instance_type)
        args = order_args_for_params(
            gen,
            params,
            node.args,
            arg_names_for(node, len(node.args)),
            type_renderer,
            default_arguments,
            args,
        )
    return IRCall(callee=f"{type_name}_new", args=args)
