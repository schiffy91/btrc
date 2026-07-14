"""Assignment ownership dispatch and typed update lowering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import AssignExpr, FieldAccessExpr, IndexExpr
from ..nodes import IRExpr

if TYPE_CHECKING:
    from .generator import IRGenerator


def lower_assignment_expr(gen: IRGenerator, node: AssignExpr) -> IRExpr:
    """Lower one assignment after enforcing aggregate/operand ownership."""
    from .aggregate_ownership import reject_shallow_store

    reject_shallow_store(gen, node)
    target_type = gen.analyzed.node_types.get(id(node.target))
    if target_type is not None and target_type.base in gen.analyzed.class_table:
        from .managed_local import mark_borrowed_cycle_seeds

        mark_borrowed_cycle_seeds(gen._managed_vars_stack)
    target_nodes = _target_operands(gen, node.target)
    if target_nodes:
        from .managed_values import is_managed_type
        from .ownership_boundary import sequence_owned_operands

        result_type = gen.analyzed.node_types.get(id(node))
        sequenced = sequence_owned_operands(
            gen,
            target_nodes,
            build=lambda: _lower_plain_assignment(gen, node),
            result_type=result_type,
            promote_result=bool(is_managed_type(gen, result_type)),
        )
        if sequenced is not None:
            return sequenced
    return _lower_plain_assignment(gen, node)


def _lower_plain_assignment(gen: IRGenerator, node: AssignExpr) -> IRExpr:
    """Lower one assignment after any owning target is stabilized."""
    from .local_arc import lower_managed_local_assignment

    managed_local = lower_managed_local_assignment(gen, node)
    if managed_local is not None:
        return managed_local

    from .property_arc import lower_managed_property_assignment

    managed_property = lower_managed_property_assignment(gen, node)
    if managed_property is not None:
        return managed_property

    from .field_arc import lower_managed_field_assignment

    managed_field = lower_managed_field_assignment(gen, node)
    if managed_field is not None:
        return managed_field

    gpu_assignment = _lower_gpu_assignment(gen, node)
    if gpu_assignment is not None:
        return gpu_assignment

    from .updates import generator_update_context, lower_assignment

    return lower_assignment(generator_update_context(gen), node)


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


def _target_operands(gen, target):
    """Return target dependencies in source evaluation order."""
    if isinstance(target, FieldAccessExpr):
        return _receiver_operands(gen, target.obj)
    if isinstance(target, IndexExpr):
        return [*_receiver_operands(gen, target.obj), target.index]
    # A later owned index still forces a boundary. Keep the receiver leaf in
    # the operand list so it is evaluated before that index; the boundary is a
    # no-op when every collected operand is borrowed.
    return [target]


def _receiver_operands(gen, receiver):
    from .ownership import owns_result

    if owns_result(gen, receiver):
        return [receiver]
    # A property is a value-producing getter even though its syntax is a field
    # projection. Stabilize the getter result itself when it feeds a later
    # projection; raw fields recurse so nested struct targets remain lvalues.
    if isinstance(receiver, FieldAccessExpr) and _is_property_projection(gen, receiver):
        return [receiver]
    return _target_operands(gen, receiver)


def _is_property_projection(gen, expression: FieldAccessExpr) -> bool:
    receiver_type = gen.analyzed.node_types.get(id(expression.obj))
    if receiver_type is None:
        return False
    class_info = gen.analyzed.class_table.get(receiver_type.base)
    return bool(class_info is not None and expression.field in class_info.properties)


__all__ = ["lower_assignment_expr"]
