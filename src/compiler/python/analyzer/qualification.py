"""Qualification-aware reference conversion contracts."""

from ..ast_nodes import (
    AssignExpr,
    BinaryExpr,
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    Identifier,
    IndexExpr,
    TernaryExpr,
    UnaryExpr,
)
from ..qualifier_provenance import volatile_qualifier_depths


class QualificationMixin:
    def _validate_mutex_volatile_initializer(self, expected, expression) -> None:
        self._validate_volatile_reference_conversion(
            expected,
            expression.args[0],
            "Mutex initializer",
            expression.line,
            expression.col,
        )

    def _validate_volatile_reference_conversion(
        self,
        target,
        value,
        subject,
        line=0,
        col=0,
    ) -> bool:
        """Reject implicit conversions that lose a nested volatile object.

        Top-level qualifiers disappear during ordinary lvalue conversion and
        are harmless.  A qualifier below a pointer/array layer is observable
        through the resulting alias and must also exist in the target shape.
        """

        if target is None or value is None:
            return True
        required = {depth for depth in self._expression_volatile_depths(value) if depth > 0}
        available = volatile_qualifier_depths(target, self.declarations.typedef_table)
        missing = sorted(required - set(available))
        if not missing:
            return True
        self.context.error(
            f"{subject} would discard volatile storage qualification at "
            f"pointer depth {missing[0]}; use a typedef that preserves the "
            "qualified pointee instead of unsupported layered pointer qualifiers",
            getattr(value, "line", line),
            getattr(value, "col", col),
        )
        return False

    def _expression_volatile_depths(self, expression) -> frozenset[int]:
        if expression is None:
            return frozenset()
        if isinstance(expression, Identifier):
            symbol = self.scope.lookup(expression.name)
            declared = symbol.type if symbol is not None else None
            return volatile_qualifier_depths(
                declared or self._infer_type(expression),
                self.declarations.typedef_table,
            )
        if isinstance(expression, FieldAccessExpr):
            return volatile_qualifier_depths(
                self._declared_projection_type(expression),
                self.declarations.typedef_table,
            )
        if isinstance(expression, IndexExpr):
            if not self._raw_index_removes_storage_layer(expression):
                return volatile_qualifier_depths(
                    self._infer_index_type(expression),
                    self.declarations.typedef_table,
                )
            return self._remove_volatile_storage_layer(self._expression_volatile_depths(expression.obj))
        if isinstance(expression, UnaryExpr):
            overloaded = self._operator_return_type(
                self._infer_type(expression.operand),
                expression.op,
                unary=True,
            )
            if overloaded is not None:
                return volatile_qualifier_depths(
                    overloaded,
                    self.declarations.typedef_table,
                )
            depths = self._expression_volatile_depths(expression.operand)
            if expression.op == "&":
                return frozenset(depth + 1 for depth in depths)
            if expression.op == "*":
                return self._remove_volatile_storage_layer(depths)
            if expression.op == "!":
                return frozenset()
            return depths
        if isinstance(expression, CastExpr):
            return volatile_qualifier_depths(
                expression.target_type,
                self.declarations.typedef_table,
            )
        if isinstance(expression, TernaryExpr):
            return self._expression_volatile_depths(expression.true_expr) | self._expression_volatile_depths(
                expression.false_expr
            )
        if isinstance(expression, AssignExpr):
            return frozenset(depth for depth in self._expression_volatile_depths(expression.target) if depth > 0)
        if isinstance(expression, BinaryExpr):
            overloaded = self._operator_return_type(
                self._infer_type(expression.left),
                expression.op,
            )
            if overloaded is not None:
                return volatile_qualifier_depths(
                    overloaded,
                    self.declarations.typedef_table,
                )
            if expression.op == "??":
                return self._expression_volatile_depths(expression.left) | self._expression_volatile_depths(
                    expression.right
                )
            if expression.op in {"+", "-"}:
                return volatile_qualifier_depths(
                    self._infer_type(expression),
                    self.declarations.typedef_table,
                )
            return frozenset()
        if isinstance(expression, CallExpr):
            declared = self._declared_call_result_type(expression)
            return volatile_qualifier_depths(
                declared or self._infer_type(expression),
                self.declarations.typedef_table,
            )
        return volatile_qualifier_depths(
            self._infer_type(expression),
            self.declarations.typedef_table,
        )

    def _raw_index_removes_storage_layer(self, expression) -> bool:
        object_type = self._canonical_type(self._infer_type(expression.obj))
        if object_type is None:
            return False
        if object_type.is_array:
            return True
        if object_type.pointer_depth <= 0:
            return False
        return bool(
            object_type.base in self._active_storage_type_parameters()
            or object_type.base not in self.declarations.class_table
            or object_type.pointer_depth > 1
        )

    def _declared_projection_type(self, expression):
        # Field inference preserves a concrete member's alias spelling and
        # substitutes class/method type parameters through the receiver.
        return self._infer_field_access_type(expression)

    def _declared_call_result_type(self, expression):
        callee = expression.callee
        if isinstance(callee, Identifier):
            symbol = self.scope.lookup(callee.name)
            if symbol is not None and symbol.kind != "function":
                signature = self._function_pointer_signature(symbol.type)
                return signature[0] if signature else None
            declaration = self.declarations.function_table.get(callee.name)
            return declaration.return_type if declaration is not None else self._infer_type(expression)
        if not isinstance(callee, FieldAccessExpr):
            return self._infer_type(expression)
        signature = self._function_pointer_signature(self._infer_type(callee))
        if signature is not None:
            return signature[0]
        receiver = self._infer_type(callee.obj)
        info = self.declarations.class_table.get(receiver.base) if receiver else None
        method = info.methods.get(callee.field) if info else None
        if method is None:
            return self._infer_type(expression)
        substitutions = {}
        if info.generic_params and receiver.generic_args:
            substitutions.update(zip(info.generic_params, receiver.generic_args))
        if method.generic_params:
            inferred = self._infer_method_type_args(
                expression,
                method,
                substitutions,
            )
            if inferred:
                substitutions.update(inferred)
        return self._substitute_type(method.return_type, substitutions) if substitutions else method.return_type

    @staticmethod
    def _remove_volatile_storage_layer(depths) -> frozenset[int]:
        return frozenset(depth - 1 for depth in depths if depth > 0)

    def _reference_shapes_compatible(self, target, source) -> bool:
        return bool(
            self._semantic_pointer_depth(target) == self._semantic_pointer_depth(source)
            and target.is_array == source.is_array
            and self._const_conversion_allowed(target, source)
            and self._generic_args_equal(target, source)
        )

    def _const_conversion_allowed(self, target, source) -> bool:
        """Whether an implicit conversion preserves pointee constness.

        ``is_const`` qualifies the base type, so it is an object qualifier for
        scalars and a pointee qualifier once one indirection is present. C's
        safe one-level qualification addition is allowed; removing const or
        changing a deeper pointee qualification requires an explicit cast.
        """
        target_depth = self._qualifier_indirection_depth(target)
        source_depth = self._qualifier_indirection_depth(source)
        if target_depth == 0 or source_depth == 0:
            return True
        if source.is_const and not target.is_const:
            return False
        if target_depth > 1 or source_depth > 1:
            return target.is_const == source.is_const
        return True

    def _qualifier_indirection_depth(self, type_expr) -> int:
        depth = self._semantic_pointer_depth(type_expr) + int(type_expr.is_array)
        if type_expr.base == "string" and depth == 0:
            return 1
        return depth


__all__ = ["QualificationMixin"]
