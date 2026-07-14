"""Call-scoped ownership planning for the primary IR generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import CallExpr, FieldAccessExpr, Identifier, LambdaExpr
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
        callee=_evaluated_callee(node),
        transferred_params=owned_transfer_param_indices(declaration),
        force_order=_language_ordered_call(gen, node, declaration),
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
    callee=None,
    transferred_params=frozenset(),
    force_order: bool = True,
):
    """Describe one call's source-order operands and lifetime guards."""
    from .arguments import bind_arg_nodes_to_params
    from .evaluation_order import has_observable_effect, operand_c_type, operands_require_order
    from .managed_values import is_managed_type

    specs = []
    for value in (callee, receiver):
        if value is None:
            continue
        type_expr = gen.analyzed.node_types.get(id(value))
        managed = is_managed_type(gen, type_expr)
        specs.append((value, type_expr, False, bool(managed and owns_result(gen, value)), False))
    specs.extend(
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
    )
    effects = [has_observable_effect(gen, argument) for argument, _type_expr, _keep, _owned, _transferred in specs]
    ownership_required = any(keep or owned for _argument, _type_expr, keep, owned, _transferred in specs)
    ordered = force_order and operands_require_order(
        gen,
        [argument for argument, _type_expr, _keep, _owned, _transferred in specs],
    )
    needs_boundary = ownership_required or ordered
    if not needs_boundary:
        return [], False

    operands = []
    final_index = len(specs) - 1
    for index, (argument, type_expr, keep, owned, transferred) in enumerate(specs):
        if type_expr is None:
            if index == final_index and index > 0 and not (keep or owned):
                continue
            _missing_operand_type(argument)
        pin = bool(index < final_index and any(effects[index + 1 :]) and is_managed_type(gen, type_expr) and not owned)
        operands.append(
            CallOperand(
                node=argument,
                type_expr=type_expr,
                c_type=operand_c_type(
                    gen,
                    argument,
                    type_expr,
                    render=type_to_c,
                ),
                keep=keep,
                pin=pin,
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


def _evaluated_callee(node):
    """Return a side-effecting callable value that precedes call arguments."""
    callee = node.callee
    if isinstance(callee, (Identifier, FieldAccessExpr, LambdaExpr)):
        return None
    return callee


def _language_ordered_call(gen, node, declaration) -> bool:
    if declaration is not None:
        return True
    if isinstance(node.callee, Identifier) and node.callee.name in {"print", "Mutex"}:
        return True
    callee_type = gen.analyzed.node_types.get(id(node.callee))
    return bool(callee_type is not None and callee_type.base == "__fn_ptr")


def _lowerer(gen):
    from .expressions import lower_expr

    return lambda node: lower_expr(gen, node)


def _missing_operand_type(argument):
    from .evaluation_order import reject_opaque_ordering

    reject_opaque_ordering(
        argument,
        "call arguments",
        typed_declaration=True,
    )


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
