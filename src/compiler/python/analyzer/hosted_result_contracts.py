"""Managed ownership boundaries for hosted pointer results."""

from ..ast_nodes import CallExpr, Identifier
from ..hosted_abi import (
    DEALLOC_FREE,
    RETURN_ALIAS,
    RETURN_FRESH,
    RETURN_INDEPENDENT,
    hosted_alias_argument_is_provably_null,
    hosted_function,
    hosted_return_deallocator,
    hosted_return_effect,
)


class HostedResultContractsMixin:
    def _direct_hosted_return_contract(
        self,
        expression,
    ) -> tuple[str, str | None] | None:
        if not isinstance(expression, CallExpr) or not isinstance(
            expression.callee,
            Identifier,
        ):
            return None
        if not self._hosted_call_uses_owned_symbol(expression):
            return None
        name = expression.callee.name
        spec = hosted_function(name)
        if spec is None:
            return None
        alias_is_null = hosted_alias_argument_is_provably_null(
            name,
            expression.args,
        )
        return (
            hosted_return_effect(
                name,
                alias_argument_is_null=alias_is_null,
            ),
            hosted_return_deallocator(
                name,
                alias_argument_is_null=alias_is_null,
            ),
        )

    def _validate_managed_string_source(
        self,
        expected,
        value,
        subject,
        line=0,
        col=0,
    ) -> None:
        target = self._canonical_type(expected)
        actual = self._canonical_type(self._infer_type(value))
        if not self._managed_string_target(target) or not self._raw_c_string(actual):
            return
        contract = self._direct_hosted_return_contract(value)
        if contract is not None and (
            contract[0] in {RETURN_ALIAS, RETURN_INDEPENDENT}
            or (contract[0] == RETURN_FRESH and contract[1] == DEALLOC_FREE)
        ):
            return
        self.context.error(
            f"{subject} cannot implicitly convert raw 'char*' storage to "
            "managed 'string' because its ownership is not proven; transfer "
            "fresh storage with __btrc_str_track() or make an explicit copy",
            getattr(value, "line", line),
            getattr(value, "col", col),
        )

    @staticmethod
    def _managed_string_target(type_expr) -> bool:
        return bool(
            type_expr and type_expr.base == "string" and type_expr.pointer_depth == 0 and not type_expr.is_array
        )

    @staticmethod
    def _raw_c_string(type_expr) -> bool:
        return bool(type_expr and type_expr.base == "char" and type_expr.pointer_depth == 1 and not type_expr.is_array)


__all__ = ["HostedResultContractsMixin"]
