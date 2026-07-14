"""Assignment ownership dispatch and typed update lowering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import AssignExpr
from ..nodes import IRExpr

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_assignment_expr(gen: IRGenerator, node: AssignExpr) -> IRExpr:
    """Lower one assignment after enforcing aggregate/operand ownership."""
    from .aggregate_ownership import reject_shallow_store
    from .callable_boundaries import reject_erasing_callable_assignment

    reject_shallow_store(gen, node)
    reject_erasing_callable_assignment(gen, node)
    target_type = gen.analyzed.node_types.get(id(node.target))
    if target_type is not None and target_type.base in gen.analyzed.class_table:
        from .managed_local import mark_borrowed_cycle_seeds

        mark_borrowed_cycle_seeds(gen._managed_vars_stack)
    from .assignment_ownership import (
        assignment_target_operands,
        kept_target_operands,
        property_projection,
    )
    from .managed_values import is_managed_type
    from .ownership import owns_result

    def type_of(expression):
        return gen.analyzed.node_types.get(id(expression))

    target_nodes = assignment_target_operands(
        node.target,
        stabilize_receiver=lambda receiver: bool(
            owns_result(gen, receiver)
            or is_managed_type(gen, type_of(receiver))
            or property_projection(
                receiver,
                type_of=type_of,
                class_table=gen.analyzed.class_table,
            )
        ),
    )
    lowered = None
    if target_nodes:
        from .assignment_ownership import virtual_assignment_target
        from .ownership_boundary import sequence_owned_operands

        result_type = gen.analyzed.node_types.get(id(node))
        rhs_supplies_result = bool(
            node.op == "=" and virtual_assignment_target(gen, node.target) and owns_result(gen, node.value)
        )
        sequenced = sequence_owned_operands(
            gen,
            target_nodes,
            build=lambda: _lower_plain_assignment(gen, node),
            result_type=result_type,
            keep_nodes=kept_target_operands(
                node.target,
                target_nodes,
                type_of=type_of,
                is_managed=lambda type_expr: is_managed_type(gen, type_expr),
                owns=lambda expression: owns_result(gen, expression),
            ),
            promote_result=bool(is_managed_type(gen, result_type) and not rhs_supplies_result),
        )
        if sequenced is not None:
            lowered = sequenced
    if lowered is None:
        lowered = _lower_plain_assignment(gen, node)
    from .callable_provenance import rebind_local_callable

    rebind_local_callable(gen, node)
    return lowered


def _lower_plain_assignment(gen: IRGenerator, node: AssignExpr) -> IRExpr:
    """Lower one assignment after any owning target is stabilized."""
    from .local_arc import lower_managed_local_assignment

    managed_local = lower_managed_local_assignment(gen, node)
    if managed_local is not None:
        return managed_local

    mutex_field = _lower_mutex_field_assignment(gen, node)
    if mutex_field is not None:
        return mutex_field

    from .field_arc import lower_managed_field_assignment

    managed_field = lower_managed_field_assignment(gen, node)
    if managed_field is not None:
        return managed_field

    gpu_assignment = _lower_gpu_assignment(gen, node)
    if gpu_assignment is not None:
        return gpu_assignment

    from .updates import generator_update_context, lower_assignment

    return lower_assignment(generator_update_context(gen), node)


def _lower_mutex_field_assignment(gen: IRGenerator, node: AssignExpr):
    """Route direct class Mutex fields through owner-aware replacement."""
    from ...ast_nodes import FieldAccessExpr, SelfExpr

    if not isinstance(node.target, FieldAccessExpr):
        return None
    receiver_type = gen.analyzed.node_types.get(id(node.target.obj))
    if receiver_type is None or receiver_type.base not in gen.analyzed.class_table:
        return None
    class_info = gen.analyzed.class_table[receiver_type.base]
    field_name = node.target.field
    field = class_info.fields.get(field_name)
    backing_property = bool(
        field is None and isinstance(node.target.obj, SelfExpr) and gen.current_property_backing == field_name
    )
    prop = class_info.properties.get(field_name) if backing_property else None
    if field is None and prop is None:
        return None
    field_type = gen.analyzed.node_types.get(id(node.target)) or (field.type if field is not None else prop.type)
    from .mutex_fields import lower_mutex_field_store, mutex_value_type

    if mutex_value_type(gen, field_type) is None:
        return None
    from .expressions import lower_expr
    from .types import type_to_c
    from .updates import _lower_assignment_value

    return lower_mutex_field_store(
        gen,
        node,
        receiver_type=receiver_type,
        field_type=field_type,
        field_name=f"_prop_{field_name}" if backing_property else field_name,
        lower_expr=lambda expression: lower_expr(gen, expression),
        lower_value=lambda target_type, value: _lower_assignment_value(
            gen,
            target_type,
            value,
        ),
        c_type=type_to_c,
        fresh_temp=gen.fresh_temp,
        record_decl=gen._func_var_decls.append,
    )


def _lower_gpu_assignment(gen: IRGenerator, node: AssignExpr):
    if node.op != "=":
        return None
    from ...ast_nodes import CallExpr
    from .gpu_dispatch import lower_gpu_output_assignment, output_gpu_call_name

    if not isinstance(node.value, CallExpr):
        return None
    if output_gpu_call_name(gen, node.value) is None:
        return None
    from .expressions import lower_expr

    target = lower_expr(gen, node.target)
    return lower_gpu_output_assignment(
        gen,
        node.value,
        node.target,
        target,
    )


__all__ = ["lower_assignment_expr"]
