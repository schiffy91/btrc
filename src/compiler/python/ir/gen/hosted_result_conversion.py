"""Target-directed ownership conversion for hosted C string results."""

from ...ast_nodes import CallExpr, Identifier
from ...hosted_abi import (
    DEALLOC_FREE,
    RETURN_ALIAS,
    RETURN_FRESH,
    RETURN_INDEPENDENT,
    hosted_alias_argument_is_provably_null,
    hosted_function,
    hosted_return_deallocator,
    hosted_return_effect,
)
from ..nodes import IRCall
from .type_resolution import canonical_type

ADOPT = "adopt"
COPY = "copy"
REJECT = "reject"


def hosted_string_conversion_mode(
    gen,
    expression,
    target_type,
    source_type,
) -> str | None:
    """Classify raw-char-pointer to managed-string conversion."""
    target = canonical_type(target_type, gen.analyzed.typedef_table)
    source = canonical_type(source_type, gen.analyzed.typedef_table)
    if not _managed_string(target) or not _raw_c_string(source):
        return None
    if not isinstance(expression, CallExpr) or not isinstance(
        expression.callee,
        Identifier,
    ):
        return REJECT
    if id(expression) not in gen.analyzed.hosted_call_ids:
        return REJECT
    name = expression.callee.name
    spec = hosted_function(name)
    if spec is None:
        return REJECT
    alias_is_null = hosted_alias_argument_is_provably_null(
        name,
        expression.args,
    )
    effect = hosted_return_effect(
        name,
        alias_argument_is_null=alias_is_null,
    )
    if (
        effect == RETURN_FRESH
        and hosted_return_deallocator(
            name,
            alias_argument_is_null=alias_is_null,
        )
        == DEALLOC_FREE
    ):
        return ADOPT
    if effect in {RETURN_ALIAS, RETURN_INDEPENDENT}:
        return COPY
    return REJECT


def lower_hosted_string_conversion(gen, lowered, mode: str):
    if mode == COPY:
        gen.use_helper("__btrc_strdup")
        lowered = IRCall(
            callee="__btrc_strdup",
            args=[lowered],
            helper_ref="__btrc_strdup",
        )
    gen.use_helper("__btrc_str_track")
    return IRCall(
        callee="__btrc_str_track",
        args=[lowered],
        helper_ref="__btrc_str_track",
    )


def requested_hosted_string_conversion(gen, expression):
    """Return the target-directed conversion active while lowering a call."""
    requests = getattr(gen, "_hosted_result_conversion_requests", None)
    return requests.get(id(expression)) if requests is not None else None


def requires_target_value_conversion(gen, expression, target_type, source_type) -> bool:
    from .prepared_values import requires_string_conversion

    return requires_string_conversion(gen, target_type, source_type) or (
        hosted_string_conversion_mode(
            gen,
            expression,
            target_type,
            source_type,
        )
        in {ADOPT, COPY}
    )


def _managed_string(type_expr) -> bool:
    return bool(type_expr and type_expr.base == "string" and type_expr.pointer_depth == 0 and not type_expr.is_array)


def _raw_c_string(type_expr) -> bool:
    return bool(type_expr and type_expr.base == "char" and type_expr.pointer_depth == 1 and not type_expr.is_array)


__all__ = [
    "ADOPT",
    "COPY",
    "REJECT",
    "hosted_string_conversion_mode",
    "lower_hosted_string_conversion",
    "requested_hosted_string_conversion",
    "requires_target_value_conversion",
]
