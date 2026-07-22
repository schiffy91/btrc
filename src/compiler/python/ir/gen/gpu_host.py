"""Host-expression adapters for shared GPU dispatch lowering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..nodes import IRExpr

if TYPE_CHECKING:
    from .generator import IRGenerator
    from .gpu_outputs import GpuOutputTarget


@dataclass(frozen=True)
class GpuHostLowering:
    """Frontend-specific facts needed by the shared dispatch planner."""

    lower_argument: Callable[[object, dict[int, IRExpr]], IRExpr]
    resolve_type: Callable[[object], Any]
    render_type: Callable[[object], str]
    array_length: Callable[[object, IRExpr], IRExpr]
    output_target: Callable[[object, IRExpr], GpuOutputTarget]
    owns_result: Callable[[object], bool]
    is_managed: Callable[[object], bool]
    override_value: Callable[[object], IRExpr | None]
    record_declaration: Callable[[object], None]
    cleanup_active: Callable[[], bool]
    activate_cleanup: Callable[[], None]


def ordinary_gpu_host(gen: IRGenerator) -> GpuHostLowering:
    """Build the ordinary, analyzer-backed host-expression adapter."""

    from .gpu_arguments import bare_array_argument_length
    from .gpu_outputs import assignment_target
    from .managed_values import is_managed_type
    from .ownership import owns_result
    from .types import type_to_c

    def lower_argument(expression, overrides):
        from .expressions import lower_expr
        from .projection_storage import evaluate_with_operand_overrides

        return evaluate_with_operand_overrides(
            overrides,
            values=gen._owning_temp_overrides,
            operation=lambda: lower_expr(gen, expression),
        )

    return GpuHostLowering(
        lower_argument=lower_argument,
        resolve_type=lambda expression: gen.analyzed.node_types.get(id(expression)),
        render_type=type_to_c,
        array_length=lambda expression, lowered: bare_array_argument_length(
            gen,
            expression,
            lowered,
        ),
        output_target=lambda expression, lowered: assignment_target(
            gen,
            expression,
            lowered,
        ),
        owns_result=lambda expression: bool(
            id(expression) not in gen._owning_temp_overrides and owns_result(gen, expression)
        ),
        is_managed=lambda type_expr: is_managed_type(gen, type_expr),
        override_value=lambda expression: gen._owning_temp_overrides.get(id(expression)),
        record_declaration=gen._func_var_decls.append,
        cleanup_active=gen.exception_cleanup_active,
        activate_cleanup=gen.mark_cleanup_registration,
    )


__all__ = ["GpuHostLowering", "ordinary_gpu_host"]
