"""Ownership-boundary composition for monomorphized method lowering."""

from ..call_boundary import CallBoundaryLowerer
from ..lowering_context import LoweringContext
from ..ownership import OwnershipLowerer
from ..ownership_order import OwnershipOperandOrder


class _GenericExpressionLowerer:
    """Expose the generic visitor as one object-owned capability."""

    def __init__(self, emitter) -> None:
        self.emitter = emitter

    def lower_expression(self, expression):
        return self.emitter._expr(expression)


def build_boundary_ownership(emitter, lowerer):
    """Bind shared ownership sequencing to generic-emitter local state."""
    context = LoweringContext(
        analyzed=lowerer.analyzed,
        module=lowerer.module,
        helpers=lowerer.helpers,
        function_declarations=emitter._func_var_decls,
        owning_overrides=emitter._arc_overrides,
        type_overrides=emitter._arc_type_overrides,
        local_ownership_scopes=emitter._local_ownership_scopes,
        callable_types=emitter._callable_types,
        callable_return_abis=emitter._callable_return_abis,
        current_property_backing=emitter._current_property_backing,
        gpu_cpu_index=lowerer.context.gpu_cpu_index,
        unevaluated_depth=emitter._unevaluated_depth,
        temporaries=lowerer.context.temporaries,
    )
    emitter.context = context
    return OwnershipLowerer(
        context,
        lowerer.managed_types,
        OwnershipOperandOrder(context, lowerer.managed_types),
        lowerer.lifetime,
        CallBoundaryLowerer(context, lowerer.lifetime),
        _GenericExpressionLowerer(emitter),
        emitter._type_renderer,
    )


def sync_boundary_context(emitter) -> None:
    """Rebind state collections replaced at a generic function boundary."""
    context = emitter._boundary_ownership.context
    context.function_declarations = emitter._func_var_decls
    context.owning_overrides = emitter._arc_overrides
    context.type_overrides = emitter._arc_type_overrides
    context.local_ownership_scopes = emitter._local_ownership_scopes
    context.callable_types = emitter._callable_types
    context.callable_return_abis = emitter._callable_return_abis
    context.current_property_backing = emitter._current_property_backing
    context.unevaluated_depth = emitter._unevaluated_depth


__all__ = ["build_boundary_ownership", "sync_boundary_context"]
