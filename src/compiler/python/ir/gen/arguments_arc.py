"""Call-scoped ownership planning for the primary IR generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier
from ..nodes import IRCommaExpr, IRExprStmt
from .call_boundary import CallOperand, sequence_call_boundary
from .ownership import owns_result
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_call_with_arc(gen: IRGenerator, node: CallExpr):
    """Lower a call with single-evaluation, call-scoped ARC guards."""
    from .aggregate_ownership import reject_rich_enum_owned_args
    from .call_effects import (
        callable_for_call,
        owned_transfer_param_indices,
    )
    from .calls import _lower_call

    reject_rich_enum_owned_args(gen, node)
    if isinstance(node.callee, FieldAccessExpr) and node.callee.optional:
        return _lower_call(gen, node)

    declaration = callable_for_call(gen, node)
    params = declaration.params if declaration is not None else []
    receiver = _instance_receiver(gen, node)
    operands, needs_boundary = plan_call_operands(
        gen,
        params,
        node.args,
        _arg_names(node),
        receiver=receiver,
        transferred_params=owned_transfer_param_indices(declaration),
    )
    if not needs_boundary:
        return _lower_call(gen, node)

    result_type = gen.analyzed.node_types.get(id(node))

    def build_call(overrides):
        previous = {key: gen._owning_temp_overrides.get(key) for key in overrides}
        gen._owning_temp_overrides.update(overrides)
        try:
            return _lower_call(gen, node)
        finally:
            for key, value in previous.items():
                if value is None:
                    gen._owning_temp_overrides.pop(key, None)
                else:
                    gen._owning_temp_overrides[key] = value

    return sequence_call_boundary(
        gen,
        operands,
        lower_expr=_lowerer(gen),
        build_call=build_call,
        result_c_type=type_to_c(result_type) if result_type is not None else None,
        fresh_temp=gen.fresh_temp,
        cleanup_active=gen.exception_cleanup_active(),
        record_decl=gen._func_var_decls.append,
        promote_result=False,
    )


def plan_call_operands(
    gen,
    params,
    ast_args,
    arg_names,
    *,
    receiver=None,
    transferred_params=frozenset(),
):
    """Describe one call's source-order operands and ARC obligations."""
    from .arguments import bind_arg_nodes_to_params

    receiver_type = gen.analyzed.node_types.get(id(receiver)) if receiver is not None else None
    from .managed_values import is_managed_type

    receiver_owned = bool(is_managed_type(gen, receiver_type) and owns_result(gen, receiver))
    specs = [
        _argument_spec(
            gen,
            params,
            param_index,
            argument,
            transferred_params,
        )
        for param_index, argument, _is_default in bind_arg_nodes_to_params(
            params,
            ast_args,
            arg_names,
        )
    ]
    needs_boundary = receiver_owned or any(keep or owned for _argument, _type_expr, keep, owned, _transferred in specs)
    if not needs_boundary:
        return [], False

    operands = []
    if receiver is not None:
        if receiver_type is None:
            _missing_operand_type()
        operands.append(
            CallOperand(
                node=receiver,
                type_expr=receiver_type,
                c_type=type_to_c(receiver_type),
                owned=receiver_owned,
            )
        )
    for argument, type_expr, keep, owned, transferred in specs:
        if type_expr is None:
            _missing_operand_type()
        operands.append(
            CallOperand(
                node=argument,
                type_expr=type_expr,
                c_type=type_to_c(type_expr),
                keep=keep,
                owned=owned,
                transferred=transferred,
            )
        )
    return operands, True


def _arg_names(node):
    from .arguments import arg_names_for

    return arg_names_for(node, len(node.args))


def _argument_spec(
    gen,
    params,
    param_index,
    argument,
    transferred_params,
):
    param = params[param_index] if param_index is not None and 0 <= param_index < len(params) else None
    type_expr = gen.analyzed.node_types.get(id(argument))
    if type_expr is None and param is not None:
        type_expr = param.type
    from .managed_values import is_managed_type

    managed = is_managed_type(gen, type_expr)
    owned = bool(managed and owns_result(gen, argument))
    return (
        argument,
        type_expr,
        bool(managed and param is not None and param.keep),
        owned,
        bool(owned and param_index in transferred_params),
    )


def _instance_receiver(gen, node):
    if not isinstance(node.callee, FieldAccessExpr):
        return None
    receiver = node.callee.obj
    if isinstance(receiver, Identifier) and (
        receiver.name in gen.analyzed.class_table or receiver.name in gen.analyzed.rich_enum_table
    ):
        return None
    return receiver


def _lowerer(gen):
    from .expressions import lower_expr

    return lambda node: lower_expr(gen, node)


def _missing_operand_type():
    from .errors import CodegenError

    raise CodegenError("managed call sequencing requires a concrete analyzed operand type")


def _release_stmt(gen, target, argument_type):
    """Statement form used for discarded owned expression results."""
    from .arc_ops import poll_release_batch
    from .managed_values import is_class_type, release_value

    expressions = [release_value(gen, target, argument_type)]
    flush = poll_release_batch(
        gen,
        types=[argument_type] if is_class_type(gen, argument_type) else [],
    )
    if flush is not None:
        expressions.append(flush)
    return IRExprStmt(expr=IRCommaExpr(expressions=expressions))


__all__ = ["_release_stmt", "lower_call_with_arc", "plan_call_operands"]
