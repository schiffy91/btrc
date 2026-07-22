"""Branch-safe call rules for borrowed raw projections."""

from __future__ import annotations

from ..projection_storage_roots import projection_storage_root
from ..raw_projection_carriers import (
    first_branch_local_storage_choice,
    is_raw_projection_carrier_type,
    raw_projection_carrier,
)

_CONDITIONAL_STORAGE_ERROR = "Conditional raw projection call arguments require branch-local backing storage"


def validate_conditional_raw_projection_call(analyzer, call) -> None:
    """Reject carriers whose owner cannot be stabilized without eager branches."""
    for argument in call.args:
        carrier = raw_projection_carrier(
            argument,
            type_of=analyzer._infer_type,
            is_raw_carrier=lambda value: _is_raw_carrier(analyzer, value),
            is_direct_storage=lambda value: _is_managed(
                analyzer,
                analyzer._infer_type(value),
            ),
            return_alias_argument=analyzer._hosted_return_alias_argument,
        )
        choice = first_branch_local_storage_choice(
            carrier,
            storage_for=lambda leaf: projection_storage_root(
                leaf.expression,
                type_of=analyzer._infer_type,
                is_managed=lambda value: _is_managed(analyzer, value),
                overridden=lambda _value: False,
                struct_table=analyzer.struct_table,
                direct=leaf.direct_storage,
            ),
        )
        if choice is not None:
            analyzer._error(
                _CONDITIONAL_STORAGE_ERROR,
                getattr(choice, "line", call.line),
                getattr(choice, "col", call.col),
            )


def _is_managed(analyzer, type_expr) -> bool:
    return analyzer._managed_result_type(analyzer._canonical_type(type_expr))


def _is_raw_carrier(analyzer, type_expr) -> bool:
    canonical = analyzer._canonical_type(type_expr)
    return is_raw_projection_carrier_type(
        canonical,
        is_managed=lambda value: _is_managed(analyzer, value),
    )


__all__ = ["validate_conditional_raw_projection_call"]
