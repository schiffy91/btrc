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
    from .managed_values import is_arc_type

    if is_arc_type(gen, target_type):
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
        from .assignment_result_ownership import virtual_assignment_rhs_owns_result
        from .ownership_boundary import sequence_owned_operands

        result_type = None if _is_gpu_output_assignment(gen, node) else gen.analyzed.node_types.get(id(node))
        prepared_targets = _prepared_index_targets(gen, node)
        rhs_supplies_result = bool(
            node.op == "="
            and virtual_assignment_target(gen, node.target)
            and virtual_assignment_rhs_owns_result(
                gen,
                node.target,
                node.value,
                type_of=type_of,
                owns=lambda value: owns_result(gen, value),
            )
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
            prepared_values=prepared_targets,
        )
        if sequenced is not None:
            lowered = sequenced
    if lowered is None:
        lowered = _lower_plain_assignment(gen, node)
    from .callable_provenance import rebind_local_callable

    rebind_local_callable(gen, node)
    return lowered


def _prepared_index_targets(gen, node):
    """Prepare an indexed setter key against its declared target type."""
    from ...ast_nodes import IndexExpr

    if not isinstance(node.target, IndexExpr):
        return {}
    from ...index_protocol import indexed_protocol

    receiver_type = gen.analyzed.node_types.get(id(node.target.obj))
    protocol = indexed_protocol(receiver_type, gen.analyzed.class_table)
    if protocol is None or protocol.setter is None:
        return {}
    expected = protocol.setter.params[0].type
    substitutions = protocol.substitutions(receiver_type)
    if substitutions:
        from .type_resolution import substitute_concrete_type

        expected = substitute_concrete_type(
            expected,
            substitutions,
            gen.analyzed.typedef_table,
        )
    from .prepared_values import prepare_normal_value, requires_string_conversion

    source = gen.analyzed.node_types.get(id(node.target.index))
    if not requires_string_conversion(gen, expected, source):
        return {}
    return {
        id(node.target.index): prepare_normal_value(
            gen,
            node.target.index,
            expected,
        )
    }


def _lower_plain_assignment(gen: IRGenerator, node: AssignExpr) -> IRExpr:
    """Lower one assignment after any owning target is stabilized."""
    # Array-returning GPU dispatch writes through an existing array/collection
    # target; it does not rebind a managed collection owner.  Recognize that
    # storage operation before the ordinary ARC assignment handlers lower its
    # RHS as an unsupported value-producing GPU call.
    gpu_assignment = _lower_gpu_assignment(gen, node)
    if gpu_assignment is not None:
        return gpu_assignment

    from .local_arc import lower_managed_local_assignment

    managed_local = lower_managed_local_assignment(gen, node)
    if managed_local is not None:
        return managed_local

    from .field_arc import lower_managed_field_assignment

    managed_field = lower_managed_field_assignment(gen, node)
    if managed_field is not None:
        return managed_field

    from .updates import generator_update_context, lower_assignment

    return lower_assignment(generator_update_context(gen), node)


def _lower_gpu_assignment(gen: IRGenerator, node: AssignExpr):
    if not _is_gpu_output_assignment(gen, node):
        return None
    from .expressions import lower_expr
    from .gpu_dispatch import lower_gpu_output_assignment

    target = lower_expr(gen, node.target)
    return lower_gpu_output_assignment(
        gen,
        node.value,
        node.target,
        target,
    )


def _is_gpu_output_assignment(gen: IRGenerator, node: AssignExpr) -> bool:
    if not isinstance(node, AssignExpr) or node.op != "=":
        return False
    from ...ast_nodes import CallExpr
    from .gpu_dispatch import output_gpu_call_name

    return (
        isinstance(node.value, CallExpr)
        and output_gpu_call_name(
            gen,
            node.value,
        )
        is not None
    )


__all__ = ["lower_assignment_expr"]
