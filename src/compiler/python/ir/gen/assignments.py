"""Assignment ownership dispatch and typed update lowering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import AssignExpr
from ..nodes import IRExpr

if TYPE_CHECKING:
    from .lowerer import IRLowerer
    from .types import CTypeRenderer


def lower_assignment_expr(
    gen: IRLowerer,
    node: AssignExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    """Lower one assignment after enforcing aggregate/operand ownership."""
    from .aggregate_ownership import reject_shallow_store
    from .callable_boundaries import reject_erasing_callable_assignment

    reject_shallow_store(gen, node)
    reject_erasing_callable_assignment(gen, node)
    target_type = gen.analyzed.node_types.get(id(node.target))

    if gen.managed_values.is_arc(target_type):
        gen.mark_borrowed_cycle_seeds()
    from .assignment_ownership import (
        assignment_target_operands,
        kept_target_operands,
        property_projection,
    )

    def type_of(expression):
        return gen.analyzed.node_types.get(id(expression))

    target_nodes = assignment_target_operands(
        node.target,
        stabilize_receiver=lambda receiver: bool(
            gen.ownership.owns_result(receiver)
            or gen.managed_values.is_managed(type_of(receiver))
            or property_projection(
                receiver,
                type_of=type_of,
                class_table=gen.analyzed.class_table,
            )
        ),
    )
    lowered = None
    if target_nodes:
        result_type = None if _is_gpu_output_assignment(gen, node) else gen.analyzed.node_types.get(id(node))
        prepared_targets = _prepared_index_targets(
            gen,
            node,
            type_renderer,
            default_arguments,
        )
        rhs_supplies_result = bool(
            node.op == "="
            and gen.ownership.effects.virtual_assignment_owns(
                node.target,
                node.value,
            )
        )
        sequenced = gen.ownership.sequence_operands(
            target_nodes,
            build=lambda: _lower_plain_assignment(
                gen,
                node,
                type_renderer,
                default_arguments,
            ),
            result_type=result_type,
            keep_nodes=kept_target_operands(
                node.target,
                target_nodes,
                type_of=type_of,
                is_managed=lambda type_expr: gen.managed_values.is_managed(type_expr),
                owns=lambda expression: gen.ownership.owns_result(expression),
            ),
            promote_result=bool(gen.managed_values.is_managed(result_type) and not rhs_supplies_result),
            prepared_values=prepared_targets,
        )
        if sequenced is not None:
            lowered = sequenced
    if lowered is None:
        lowered = _lower_plain_assignment(
            gen,
            node,
            type_renderer,
            default_arguments,
        )
    from .callable_provenance import rebind_local_callable

    rebind_local_callable(gen, node)
    return lowered


def _prepared_index_targets(
    gen,
    node,
    type_renderer: CTypeRenderer,
    default_arguments=None,
):
    """Prepare an indexed setter key against its declared target type."""
    from ...ast_nodes import IndexExpr

    if not isinstance(node.target, IndexExpr):
        return {}
    receiver_type = gen.analyzed.node_types.get(id(node.target.obj))
    protocol = gen.index_protocols.resolve(receiver_type)
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
            gen.type_identity,
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
            type_renderer,
            default_arguments=default_arguments,
        )
    }


def _lower_plain_assignment(
    gen: IRLowerer,
    node: AssignExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
) -> IRExpr:
    """Lower one assignment after any owning target is stabilized."""
    # Array-returning GPU dispatch writes through an existing array/collection
    # target; it does not rebind a managed collection owner.  Recognize that
    # storage operation before the ordinary ARC assignment handlers lower its
    # RHS as an unsupported value-producing GPU call.
    gpu_assignment = _lower_gpu_assignment(
        gen,
        node,
        type_renderer,
        default_arguments,
    )
    if gpu_assignment is not None:
        return gpu_assignment

    from .local_arc import lower_managed_local_assignment

    managed_local = lower_managed_local_assignment(gen, node, type_renderer)
    if managed_local is not None:
        return managed_local

    from .field_arc import lower_managed_field_assignment

    managed_field = lower_managed_field_assignment(gen, node, type_renderer)
    if managed_field is not None:
        return managed_field

    from .updates import generator_update_context, lower_assignment

    return lower_assignment(
        generator_update_context(
            gen,
            type_renderer,
            default_arguments,
        ),
        node,
    )


def _lower_gpu_assignment(
    gen: IRLowerer,
    node: AssignExpr,
    type_renderer: CTypeRenderer,
    default_arguments=None,
):
    if not _is_gpu_output_assignment(gen, node):
        return None
    from .expressions import lower_expr
    from .gpu_dispatch import lower_gpu_output_assignment

    target = lower_expr(
        gen,
        node.target,
        type_renderer,
        default_arguments,
    )
    return lower_gpu_output_assignment(
        gen,
        node.value,
        node.target,
        target,
        type_renderer,
        default_arguments,
    )


def _is_gpu_output_assignment(gen: IRLowerer, node: AssignExpr) -> bool:
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
