"""Target-directed ownership conversion for hosted C string results."""

from contextlib import contextmanager

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


class HostedResultLowerer:
    """Own target-directed hosted-result requests for one lowering run."""

    def __init__(self, context) -> None:
        self.context = context
        self._requests = context.hosted_result_conversion_requests

    def conversion_mode(
        self,
        expression,
        target_type,
        source_type,
    ) -> str | None:
        return _conversion_mode(
            self.context.analyzed,
            expression,
            target_type,
            source_type,
        )

    def requires_target_conversion(
        self,
        expression,
        target_type,
        source_type,
    ) -> bool:
        from ...string_conversion import requires_class_to_string

        analyzed = self.context.analyzed
        target = canonical_type(target_type, analyzed.typedef_table)
        source = canonical_type(source_type, analyzed.typedef_table)
        class_conversion = requires_class_to_string(
            analyzed.class_table,
            target,
            source,
            canonicalize=lambda value: canonical_type(
                value,
                analyzed.typedef_table,
            ),
        )
        return class_conversion or self.conversion_mode(
            expression,
            target_type,
            source_type,
        ) in {ADOPT, COPY}

    @contextmanager
    def request(self, expression, mode: str, target_type):
        key = id(expression)
        missing = object()
        previous = self._requests.get(key, missing)
        self._requests[key] = (mode, target_type)
        try:
            yield
        finally:
            if previous is missing:
                self._requests.pop(key, None)
            else:
                self._requests[key] = previous

    def requested_conversion(self, expression):
        return self._requests.get(id(expression))

    def lower_conversion(self, lowered, mode: str):
        if mode == COPY:
            self.context.helpers.use("__btrc_strdup")
            lowered = IRCall(
                callee="__btrc_strdup",
                args=[lowered],
                helper_ref="__btrc_strdup",
            )
        self.context.helpers.use("__btrc_str_track")
        return IRCall(
            callee="__btrc_str_track",
            args=[lowered],
            helper_ref="__btrc_str_track",
        )


def hosted_string_conversion_mode(
    gen,
    expression,
    target_type,
    source_type,
) -> str | None:
    """Classify raw-char-pointer to managed-string conversion."""
    return _conversion_mode(
        gen.analyzed,
        expression,
        target_type,
        source_type,
    )


def _conversion_mode(
    analyzed,
    expression,
    target_type,
    source_type,
) -> str | None:
    target = canonical_type(target_type, analyzed.typedef_table)
    source = canonical_type(source_type, analyzed.typedef_table)
    if not _managed_string(target) or not _raw_c_string(source):
        return None
    if not isinstance(expression, CallExpr) or not isinstance(
        expression.callee,
        Identifier,
    ):
        return REJECT
    if id(expression) not in analyzed.hosted_call_ids:
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
        gen.helpers.use("__btrc_strdup")
        lowered = IRCall(
            callee="__btrc_strdup",
            args=[lowered],
            helper_ref="__btrc_strdup",
        )
    gen.helpers.use("__btrc_str_track")
    return IRCall(
        callee="__btrc_str_track",
        args=[lowered],
        helper_ref="__btrc_str_track",
    )


def requested_hosted_string_conversion(gen, expression):
    """Return the target-directed conversion active while lowering a call."""
    context = getattr(gen, "context", None)
    requests = (
        context.hosted_result_conversion_requests
        if context is not None
        else getattr(gen, "_hosted_result_conversion_requests", None)
    )
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
    "HostedResultLowerer",
    "hosted_string_conversion_mode",
    "lower_hosted_string_conversion",
    "requested_hosted_string_conversion",
    "requires_target_value_conversion",
]
