"""Source-expression ownership classification used by semantic contracts."""

from ..ast_nodes import (
    AssignExpr,
    BinaryExpr,
    BraceInitializer,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    FStringExpr,
    FStringLiteral,
    Identifier,
    IndexExpr,
    ListLiteral,
    MapLiteral,
    NewExpr,
    NullLiteral,
    SelfExpr,
    SuperExpr,
    TernaryExpr,
    UnaryExpr,
)


class ExpressionOwnershipContractsMixin:
    def _expression_produces_owned_result(self, expression) -> bool:
        result = self._canonical_type(self._infer_type(expression))
        managed = self._managed_result_type(result)
        if isinstance(expression, (NewExpr, BraceInitializer, ListLiteral, MapLiteral)):
            return managed
        if isinstance(expression, CastExpr):
            return managed and self._expression_produces_owned_result(expression.expr)
        if isinstance(expression, FStringLiteral):
            return any(isinstance(part, FStringExpr) for part in expression.parts)
        if isinstance(expression, AssignExpr):
            target = expression.target
            owned_receiver = isinstance(
                target, (FieldAccessExpr, IndexExpr)
            ) and self._expression_produces_owned_result(target.obj)
            owned_value = (
                expression.op == "="
                and self._is_virtual_update_target(target)
                and (
                    managed
                    or self._expression_produces_owned_result(expression.value)
                    or self._requires_string_conversion(
                        result,
                        self._infer_type(expression.value),
                    )
                )
            )
            return managed and (owned_receiver or owned_value)
        if isinstance(expression, (FieldAccessExpr, IndexExpr)):
            if not managed:
                return False
            if self._expression_produces_owned_result(expression.obj):
                return True
            if isinstance(expression, FieldAccessExpr):
                from ..class_storage import custom_property_getter

                return custom_property_getter(
                    self.declarations.class_table,
                    self._canonical_type(self._infer_type(expression.obj)),
                    expression.field,
                ) and not isinstance(expression.obj, (SelfExpr, SuperExpr))
            if not isinstance(expression, IndexExpr):
                return False
            receiver = self._canonical_type(self._infer_type(expression.obj))
            protocol = self.index_protocols.resolve(
                receiver,
                active_type_params=self._active_storage_type_parameters(),
            )
            return bool(protocol and protocol.getter is not None)
        if isinstance(expression, TernaryExpr):
            return self._conditional_produces_owned_result(
                result,
                (expression.true_expr, expression.false_expr),
            )
        if isinstance(expression, BinaryExpr) and expression.op == "??":
            return self._conditional_produces_owned_result(
                result,
                (expression.left, expression.right),
            )
        if isinstance(expression, BinaryExpr):
            if self._string_concat_produces_owned_result(expression, result):
                return True
            return self._overload_produces_owned_result(
                expression.left,
                expression.op,
                result,
            )
        if isinstance(expression, UnaryExpr):
            return self._overload_produces_owned_result(
                expression.operand,
                "__neg__" if expression.op == "-" else "",
                result,
                magic_is_resolved=True,
            )
        if not isinstance(expression, CallExpr) or not managed:
            return False
        if result.base == "string":
            return self._string_call_produces_owned_result(expression)
        return self._known_language_call(expression)

    def _argument_produces_owned_result(self, expression) -> bool:
        """Compatibility name for call/update validators."""
        return self._expression_produces_owned_result(expression)

    def _managed_result_type(self, type_expr) -> bool:
        active_type_param = bool(type_expr and type_expr.base in self._active_storage_type_parameters())
        return bool(
            type_expr
            and not type_expr.is_array
            and type_expr.pointer_depth <= 1
            and (
                type_expr.base in {"string", "Mutex"}
                or (not active_type_param and type_expr.base in self.declarations.class_table)
            )
        )

    def _conditional_produces_owned_result(self, result, branches) -> bool:
        if not self._managed_result_type(result):
            return False
        if not any(self._expression_produces_owned_result(item) for item in branches):
            return False
        return all(self._ownership_branch_is_promotable(item) for item in branches)

    def _ownership_branch_is_promotable(self, expression) -> bool:
        if isinstance(expression, NullLiteral):
            return True
        if self._expression_produces_owned_result(expression):
            return True
        return self._managed_result_type(self._canonical_type(self._infer_type(expression)))

    def _string_concat_produces_owned_result(self, expression, result) -> bool:
        if expression.op != "+" or result is None or result.base != "string":
            return False
        left = self._canonical_type(self._infer_type(expression.left))
        right = self._canonical_type(self._infer_type(expression.right))
        return bool(left and right and left.base == "string" and right.base == "string")

    def _overload_produces_owned_result(
        self,
        operand,
        operator,
        result,
        *,
        magic_is_resolved=False,
    ) -> bool:
        if not self._managed_result_type(result) or result.base == "string":
            return False
        magic = (
            operator
            if magic_is_resolved
            else {
                "+": "__add__",
                "-": "__sub__",
                "*": "__mul__",
                "/": "__div__",
                "%": "__mod__",
            }.get(operator, "")
        )
        operand_type = self._canonical_type(self._infer_type(operand))
        class_info = self.declarations.class_table.get(operand_type.base) if operand_type else None
        return bool(magic and class_info and magic in class_info.methods)

    def _known_language_call(self, expression) -> bool:
        callee = expression.callee
        if isinstance(callee, Identifier):
            symbol = self.scope.lookup(callee.name)
            if symbol is not None and symbol.kind != "function":
                return False
            return (
                callee.name == "Mutex"
                or callee.name in self.declarations.class_table
                or callee.name in self.declarations.function_table
            )
        if not isinstance(callee, FieldAccessExpr):
            return False
        if isinstance(callee.obj, Identifier):
            owner = (
                None
                if self.scope.lookup(callee.obj.name) is not None
                else self.declarations.class_table.get(callee.obj.name)
            )
            if owner is not None and callee.field in owner.methods:
                return True
        receiver = self._canonical_type(self._infer_type(callee.obj))
        if receiver is None:
            return False
        if receiver.base == "Thread" and callee.field == "join":
            return True
        if receiver.base == "Mutex" and callee.field == "get":
            return True
        owner = self.declarations.class_table.get(receiver.base)
        if owner is not None and callee.field in owner.methods:
            return True
        interface = self.declarations.interface_table.get(receiver.base)
        return bool(interface is not None and callee.field in interface.methods)

    def _string_call_produces_owned_result(self, expression) -> bool:
        if self._known_language_call(expression):
            return True
        callee = expression.callee
        if isinstance(callee, Identifier):
            return callee.name in {
                "__btrc_str_track",
                "__btrc_string_adopt",
                "__btrc_string_alloc",
            }
        if not isinstance(callee, FieldAccessExpr):
            return False
        receiver = self._canonical_type(self._infer_type(callee.obj))
        if receiver is not None and receiver.base == "string":
            from ..string_methods import STRING_METHODS

            method = STRING_METHODS.get(callee.field)
            return bool(method and method.tracked)
        if callee.field != "toString" or receiver is None:
            return False
        return receiver.base != "bool" and receiver.base not in self.declarations.enum_table


__all__ = ["ExpressionOwnershipContractsMixin"]
