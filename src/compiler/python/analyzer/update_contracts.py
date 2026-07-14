"""Semantic contracts for assignment and increment/decrement updates."""

from ..ast_nodes import (
    FieldAccessExpr,
    FloatLiteral,
    Identifier,
    IntLiteral,
    NullLiteral,
)


class UpdateContractsMixin:
    def _validate_literal_divisor(self, operator, operand):
        if operator not in {"/", "%", "/=", "%="}:
            return
        zero = (isinstance(operand, IntLiteral) and operand.value == 0) or (
            isinstance(operand, FloatLiteral) and operand.value == 0.0
        )
        if zero:
            self._error("Division by zero", operand.line, operand.col)

    def _validate_assignment(self, expression):
        if not self._is_lvalue(expression.target):
            self._error("Assignment target is not assignable", expression.line, expression.col)
            return
        if not self._validate_mutable_target(expression.target, expression.line, expression.col):
            return
        if isinstance(expression.target, FieldAccessExpr) and expression.target.optional:
            self._error("Optional-chain expression is not assignable", expression.line, expression.col)
            return
        self._validate_property_update(
            expression.target, require_getter=expression.op != "=", line=expression.line, col=expression.col
        )
        self._validate_indexed_update(
            expression.target,
            require_getter=expression.op != "=",
            value=expression.value,
            line=expression.line,
            col=expression.col,
        )

        target = self._infer_type(expression.target)
        canonical_target = self._canonical_type(target)
        if self._reject_borrowed_managed_rebind(
            expression,
            canonical_target,
        ):
            return
        virtual_target = self._is_virtual_update_target(expression.target)
        if (
            expression.op != "="
            and canonical_target is not None
            and (canonical_target.base in self.class_table or canonical_target.base == "string")
        ):
            supported_physical = isinstance(expression.target, (Identifier, FieldAccessExpr)) and not virtual_target
            if not supported_physical:
                self._error(
                    "Managed compound updates require a direct local/global or physical field; "
                    "use an explicit local value and simple store for virtual or indirect targets",
                    expression.line,
                    expression.col,
                )
                return
        if self._validate_fixed_array_assignment(target, expression):
            return
        self._contextualize_generic_constructor(target, expression.value)
        source = self._infer_type(expression.value)
        if target is None:
            return
        if self._validate_callable_value(target, expression.value, expression.line, expression.col):
            return
        if source is None:
            return
        if isinstance(expression.value, NullLiteral) and self._is_active_type_parameter(target):
            return
        if expression.op == "=":
            if self._validate_thread_handle_copy(
                target,
                expression.value,
                expression.line,
                expression.col,
            ):
                return
            canonical_target = self._canonical_type(target)
            if canonical_target and canonical_target.base == "Thread":
                self._error(
                    "Thread owner variables are single-assignment; declare a new owner for a fresh Thread result",
                    expression.line,
                    expression.col,
                )
                return
            if not self._types_compatible(target, source):
                self._error(
                    f"Cannot assign '{self._format_type(source)}' to '{self._format_type(target)}'",
                    expression.line,
                    expression.col,
                )
            return

        operator = expression.op[:-1]
        if target.base == source.base and self._is_active_type_parameter(target):
            return
        if self._operator_method(target, operator) is not None:
            self._validate_operator_access(target, operator, expression)
            return
        if (
            operator == "+"
            and target.base == "string"
            and (source.base == "string" or (source.base == "char" and (source.pointer_depth > 0 or source.is_array)))
        ):
            return
        if not self._validate_portable_numeric_mix(
            expression,
            target,
            source,
            f"Compound assignment '{expression.op}'",
        ):
            return
        if operator in ("&", "|", "^", "<<", ">>"):
            valid = self._is_integral_value(target) and self._is_integral_value(source)
        else:
            valid = self._is_numeric_value(target) and self._is_numeric_value(source)
        if not valid:
            self._error(
                f"Operator '{expression.op}' is not defined for "
                f"'{self._format_type(target)}' and "
                f"'{self._format_type(source)}'",
                expression.line,
                expression.col,
            )

    def _validate_unary_expr(self, expression):
        if expression.op == "&":
            self._validate_address_operand(expression)
            return
        operand_type = self._infer_type(expression.operand)
        if operand_type is None:
            return
        if self._operator_method(operand_type, expression.op, unary=True) is not None:
            self._validate_operator_access(
                operand_type,
                expression.op,
                expression,
                unary=True,
            )
            return
        if expression.op == "*":
            valid = operand_type.pointer_depth > 0 or operand_type.is_array
        elif expression.op in ("++", "--"):
            valid = self._is_lvalue(expression.operand) and (
                self._is_numeric_value(operand_type) or operand_type.pointer_depth > 0
            )
            if valid:
                if not self._validate_mutable_target(expression.operand, expression.line, expression.col):
                    return
                self._validate_property_update(
                    expression.operand, require_getter=True, line=expression.line, col=expression.col
                )
                self._validate_indexed_update(
                    expression.operand,
                    require_getter=True,
                    value=None,
                    line=expression.line,
                    col=expression.col,
                )
        elif expression.op in ("+", "-"):
            valid = self._is_numeric_value(operand_type)
        elif expression.op == "~":
            valid = self._is_integral_value(operand_type)
        elif expression.op == "!":
            valid = (
                operand_type.base == "bool" or self._is_numeric_value(operand_type) or operand_type.pointer_depth > 0
            )
        else:
            return
        if not valid:
            self._error(
                f"Unary operator '{expression.op}' is not defined for '{self._format_type(operand_type)}'",
                expression.line,
                expression.col,
            )

    def _validate_property_update(self, target, *, require_getter, line, col):
        if not isinstance(target, FieldAccessExpr):
            return
        receiver_type = self._infer_type(target.obj)
        class_info = self.class_table.get(receiver_type.base) if receiver_type else None
        prop = class_info.properties.get(target.field) if class_info else None
        if prop is None:
            return
        if not prop.has_setter:
            self._error(f"Property '{target.field}' has no setter", line, col)
        if require_getter and not prop.has_getter:
            self._error(f"Property '{target.field}' has no getter", line, col)

    def _validate_mutable_target(self, target, line, col) -> bool:
        target_type = self._canonical_type(self._infer_type(target))
        if target_type is not None and target_type.is_const and not self._is_pointer_value(target_type):
            self._error("Cannot modify const-qualified storage", line, col)
            return False
        if self._target_has_const_receiver(target):
            self._error("Cannot modify through a const-qualified receiver", line, col)
            return False
        if self._aggregate_has_const_member(target_type):
            self._error(
                "Cannot assign an aggregate containing const-qualified storage",
                line,
                col,
            )
            return False
        return True

    def _aggregate_has_const_member(self, type_expr, seen=None) -> bool:
        if type_expr is None or self._is_pointer_value(type_expr):
            return False
        name = type_expr.base.removeprefix("struct ")
        declaration = self.struct_table.get(name)
        if declaration is None:
            return False
        seen = set() if seen is None else seen
        if name in seen:
            return False
        seen.add(name)
        for field in declaration.fields:
            field_type = self._canonical_type(field.type)
            if field_type is None:
                continue
            if field_type.is_const and not self._is_pointer_value(field_type):
                return True
            if self._aggregate_has_const_member(field_type, seen):
                return True
        return False


__all__ = ["UpdateContractsMixin"]
