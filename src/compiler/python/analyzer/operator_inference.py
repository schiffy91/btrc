"""Operator overload lookup and result-type substitution."""

from typing import ClassVar


class OperatorInferenceMixin:
    _BINARY_OVERLOADS: ClassVar[dict[str, str]] = {
        "+": "__add__",
        "-": "__sub__",
        "*": "__mul__",
        "/": "__div__",
        "%": "__mod__",
        "==": "__eq__",
        "!=": "__ne__",
        "<": "__lt__",
        ">": "__gt__",
        "<=": "__le__",
        ">=": "__ge__",
    }
    _UNARY_OVERLOADS: ClassVar[dict[str, str]] = {"-": "__neg__"}

    def _operator_method(self, receiver_type, operator, *, unary=False):
        """Return an overload and its class substitutions, if one exists."""
        if receiver_type is None:
            return None
        cls = self.declarations.class_table.get(receiver_type.base)
        names = self._UNARY_OVERLOADS if unary else self._BINARY_OVERLOADS
        method = cls.methods.get(names.get(operator, "")) if cls else None
        if method is None:
            return None
        substitutions = {}
        if cls.generic_params and len(receiver_type.generic_args) == len(cls.generic_params):
            substitutions.update(zip(cls.generic_params, receiver_type.generic_args))
        return method, substitutions

    def _operator_return_type(self, receiver_type, operator, *, unary=False):
        resolved = self._operator_method(receiver_type, operator, unary=unary)
        if resolved is None:
            return None
        method, substitutions = resolved
        if substitutions:
            return self._substitute_type(method.return_type, substitutions)
        return method.return_type

    def _validate_operator_access(self, receiver_type, operator, expression, *, unary=False):
        resolved = self._operator_method(receiver_type, operator, unary=unary)
        if resolved is None:
            return
        method, _ = resolved
        cls = self.declarations.class_table.get(receiver_type.base)
        owner = cls.method_owners.get(method.name, cls.name) if cls else ""
        if method.access == "private" and (self.current_class is None or self.current_class.name != owner):
            self._error(
                f"Cannot use private operator '{owner}.{method.name}' outside its class",
                expression.line,
                expression.col,
            )
