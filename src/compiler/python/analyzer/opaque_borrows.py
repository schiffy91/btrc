"""Ephemeral managed-to-raw borrow boundaries."""

from ..ast_nodes import (
    BinaryExpr,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    Identifier,
    IndexExpr,
    StringLiteral,
    TernaryExpr,
    UnaryExpr,
)
from ..hosted_abi import (
    hosted_parameter_is_read_only_borrow,
    hosted_return_alias_parameter,
)

_MANAGED_RUNTIME_BASES = frozenset({"string", "Mutex", "Thread", "Vector", "List", "Map", "Set", "Array"})
_NON_CARRYING_BINARY_OPS = frozenset({"==", "!=", "<", "<=", ">", ">=", "&&", "||"})


class OpaqueBorrowContractsMixin:
    def _opaque_projection_carrier_type(self, type_expr) -> bool:
        canonical = self._canonical_type(type_expr)
        return bool(canonical and (canonical.pointer_depth > 0 or canonical.base in {"intptr_t", "uintptr_t"}))

    def _hosted_return_alias_argument(self, expression):
        if not isinstance(expression, CallExpr) or not isinstance(
            expression.callee,
            Identifier,
        ):
            return None
        if not self._hosted_call_uses_owned_symbol(expression):
            return None
        name = expression.callee.name
        parameter = hosted_return_alias_parameter(name)
        if parameter is None or parameter >= len(expression.args):
            return None
        return expression.args[parameter]

    def _opaque_managed_type(self, type_expr):
        canonical = self._canonical_type(type_expr)
        if canonical is None or canonical.is_array:
            return None
        active = self._active_storage_type_parameters()
        active_parameter_value = canonical.base in active and (
            canonical.pointer_depth == 0 or (canonical.is_nullable and canonical.pointer_depth == 1)
        )
        if self._managed_result_type(canonical) or canonical.base in _MANAGED_RUNTIME_BASES or active_parameter_value:
            return canonical
        return None

    def _opaque_raw_carrier_type(self, type_expr) -> bool:
        canonical = self._canonical_type(type_expr)
        if canonical is None or self._opaque_managed_type(canonical):
            return False
        if canonical.pointer_depth > 0:
            return True
        return bool(
            canonical.base != "bool" and (self._is_numeric_value(canonical) or self._is_opaque_c_scalar(canonical))
        )

    def _opaque_managed_origin_type(self, expression):
        if expression is None:
            return None
        if isinstance(expression, StringLiteral):
            return None
        direct = self._opaque_managed_type(self._infer_type(expression))
        if direct is not None:
            return direct
        if isinstance(expression, CastExpr):
            return self._opaque_managed_origin_type(expression.expr)
        if isinstance(expression, UnaryExpr):
            if expression.op == "*":
                if self._opaque_projection_carrier_type(
                    self._infer_type(expression)
                ) and self._expression_carries_opaque_borrow(expression.operand):
                    return self._opaque_managed_origin_type(expression.operand)
                return None
            return self._opaque_managed_origin_type(expression.operand)
        if isinstance(expression, BinaryExpr):
            if expression.op in _NON_CARRYING_BINARY_OPS:
                return None
            return self._opaque_managed_origin_type(expression.left) or self._opaque_managed_origin_type(
                expression.right
            )
        if isinstance(expression, TernaryExpr):
            return self._opaque_managed_origin_type(expression.true_expr) or self._opaque_managed_origin_type(
                expression.false_expr
            )
        if isinstance(expression, (IndexExpr, FieldAccessExpr)):
            if self._opaque_projection_carrier_type(
                self._infer_type(expression)
            ) and self._expression_carries_opaque_borrow(expression.obj):
                return self._opaque_managed_origin_type(expression.obj)
            return None
        alias_argument = self._hosted_return_alias_argument(expression)
        if alias_argument is not None:
            return self._opaque_managed_origin_type(alias_argument)
        return None

    def _expression_carries_opaque_borrow(self, expression) -> bool:
        if expression is None:
            return False
        if isinstance(expression, CastExpr):
            if not self._opaque_raw_carrier_type(expression.target_type):
                return False
            if isinstance(expression.expr, StringLiteral):
                return False
            return bool(
                self._opaque_managed_origin_type(expression.expr)
                or self._expression_carries_opaque_borrow(expression.expr)
            )
        if isinstance(expression, UnaryExpr):
            if expression.op == "!":
                return False
            if expression.op == "*":
                return bool(
                    self._opaque_projection_carrier_type(self._infer_type(expression))
                    and self._expression_carries_opaque_borrow(expression.operand)
                )
            return self._expression_carries_opaque_borrow(expression.operand)
        if isinstance(expression, BinaryExpr):
            if expression.op in _NON_CARRYING_BINARY_OPS:
                return False
            if expression.op == "-" and all(
                self._is_pointer_value(self._infer_type(operand)) for operand in (expression.left, expression.right)
            ):
                return False
            return self._expression_carries_opaque_borrow(expression.left) or self._expression_carries_opaque_borrow(
                expression.right
            )
        if isinstance(expression, TernaryExpr):
            return self._expression_carries_opaque_borrow(
                expression.true_expr
            ) or self._expression_carries_opaque_borrow(expression.false_expr)
        if isinstance(expression, (IndexExpr, FieldAccessExpr)):
            return bool(
                self._opaque_projection_carrier_type(self._infer_type(expression))
                and self._expression_carries_opaque_borrow(expression.obj)
            )
        alias_argument = self._hosted_return_alias_argument(expression)
        if alias_argument is not None:
            return self._expression_is_opaque_borrow(alias_argument)
        return False

    def _expression_is_opaque_borrow(self, expression) -> bool:
        if isinstance(expression, StringLiteral):
            return False
        return bool(
            self._opaque_managed_type(self._infer_type(expression))
            or self._expression_carries_opaque_borrow(expression)
        )

    def _validate_opaque_borrow_storage(
        self,
        expected,
        value,
        subject="This operation",
        line=0,
        col=0,
    ) -> None:
        if not self._opaque_raw_carrier_type(expected):
            return
        if not self._expression_is_opaque_borrow(value):
            return
        self._error(
            f"{subject} cannot persist a managed value as a raw representation; "
            "use it only in a non-persisting expression or a proven borrow-only FFI call",
            getattr(value, "line", line),
            getattr(value, "col", col),
        )

    def _validate_opaque_call_argument(
        self,
        declaration,
        parameter_index,
        expected,
        argument,
        label,
        *,
        bodyless_ffi=False,
    ) -> None:
        if not self._opaque_raw_carrier_type(expected):
            return
        if not self._expression_is_opaque_borrow(argument):
            return
        if (bodyless_ffi and hosted_parameter_is_read_only_borrow(label, parameter_index)) or (
            declaration is not None
            and self._raw_parameter_is_borrow_only(
                declaration,
                parameter_index,
            )
        ):
            return
        self._error(
            f"Argument to '{label}()' cannot forward a managed value as a raw "
            "representation because the parameter is not proven borrow-only",
            getattr(argument, "line", 0),
            getattr(argument, "col", 0),
        )


__all__ = ["OpaqueBorrowContractsMixin"]
