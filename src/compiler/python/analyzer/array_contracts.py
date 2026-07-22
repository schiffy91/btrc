"""Array storage provenance and strict-C assignment contracts."""

from ..ast_nodes import (
    BraceInitializer,
    CallExpr,
    FieldAccessExpr,
    Identifier,
    IntLiteral,
    ListLiteral,
)
from ..type_composition import add_outer_pointer


class ArrayContractsMixin:
    def _validate_fixed_array_initializer(
        self,
        expected,
        initializer,
        subject,
        line,
        col,
    ) -> None:
        """Reject initializer lists that exceed a statically known bound."""
        if expected is None or not expected.is_array:
            return
        bound = expected.array_size
        if not isinstance(bound, IntLiteral):
            return
        if not isinstance(initializer, (BraceInitializer, ListLiteral)):
            return
        count = len(initializer.elements)
        if count > bound.value:
            self.context.error(
                f"{subject} has {count} elements but fixed array bound is {bound.value}",
                line,
                col,
            )

    def _validate_fixed_array_assignment(self, target, expression) -> bool:
        """Reject array-object rebinding while preserving pointer-valued slots."""
        target = self._array_target_value_type(expression.target, target)
        canonical = self._canonical_type(target)
        if self._is_gpu_output_assignment(expression):
            if self._array_target_has_capacity(expression.target, target):
                return False
            self.context.error(
                "Array-returning @gpu assignment target has no provable writable capacity",
                expression.line,
                expression.col,
            )
            return True
        if canonical is None or not canonical.is_array:
            return False
        if self._is_pointer_backed_array_target(expression.target, canonical):
            return False
        subject = "Fixed array" if canonical.array_size is not None else "Array object"
        self.context.error(
            f"{subject} '{self._format_type(canonical)}' is not assignable",
            expression.line,
            expression.col,
        )
        return True

    def _inferred_array_binding_type(self, inferred, initializer):
        """Represent `var alias = arrayValue` as a pointer-valued binding."""
        if isinstance(initializer, BraceInitializer):
            self.context.error(
                "Cannot infer array storage for 'var' from a brace initializer; use an explicit array declaration",
                initializer.line,
                initializer.col,
            )
        inferred = self._array_value_type(inferred)
        canonical = self._canonical_type(inferred)
        if canonical is None or not canonical.is_array or isinstance(initializer, (BraceInitializer, ListLiteral)):
            return inferred
        if self._is_gpu_array_initializer(initializer):
            return canonical
        return add_outer_pointer(canonical, clear_array=True)

    def _array_value_type(self, type_expr):
        """Preserve raw array declarators versus pointer-valued array aliases."""
        canonical = self._canonical_type(type_expr)
        if type_expr is None or canonical is None or type_expr.is_array or not canonical.is_array:
            return type_expr
        return add_outer_pointer(canonical, clear_array=True)

    def _array_parameter_value_type(self, type_expr):
        value_type = self._array_value_type(type_expr)
        canonical = self._canonical_type(value_type)
        if canonical is None or not canonical.is_array:
            return value_type
        return add_outer_pointer(canonical, clear_array=True)

    def _array_parameter_initializer_type(self, type_expr, initializer):
        if isinstance(initializer, (BraceInitializer, ListLiteral)):
            return self._array_value_type(type_expr)
        return self._array_parameter_value_type(type_expr)

    def _validate_array_parameter_default(self, type_expr, initializer, subject, line, col) -> None:
        canonical = self._canonical_type(type_expr)
        if (
            canonical is not None
            and canonical.is_array
            and isinstance(
                initializer,
                (BraceInitializer, ListLiteral),
            )
        ):
            self.context.error(
                f"{subject} cannot use temporary aggregate backing for an array parameter",
                line,
                col,
            )

    def _array_field_value_type(self, field, resolved_type=None):
        """Apply field storage representation after generic resolution."""
        value_type = self._array_value_type(field.type if resolved_type is None else resolved_type)
        canonical = self._canonical_type(value_type)
        if canonical is not None and not canonical.is_array:
            return value_type
        if (
            canonical is None
            or not canonical.is_array
            or canonical.array_size is not None
            or (
                getattr(field, "access", None) == "class"
                and isinstance(
                    getattr(field, "initializer", None),
                    (BraceInitializer, ListLiteral),
                )
            )
        ):
            return value_type
        return add_outer_pointer(canonical, clear_array=True)

    def _validate_pointer_backed_array_field_initializer(self, field, initializer, subject, line, col) -> None:
        canonical = self._canonical_type(field.type)
        represented = self._canonical_type(self._array_field_value_type(field))
        if (
            canonical is not None
            and canonical.is_array
            and represented is not None
            and not represented.is_array
            and isinstance(initializer, (BraceInitializer, ListLiteral))
        ):
            self.context.error(
                f"{subject} cannot use aggregate backing for a pointer-valued array field",
                line,
                col,
            )

    def _validate_array_object_initializer(self, expected, initializer, subject, line, col) -> None:
        canonical = self._canonical_type(expected)
        represented = self._canonical_type(self._array_value_type(expected))
        aggregate = isinstance(initializer, (BraceInitializer, ListLiteral))
        if canonical is not None and canonical.is_array and represented is not None and not represented.is_array:
            if self._is_gpu_array_initializer(initializer):
                self.context.error(
                    f"{subject} cannot materialize an array-returning @gpu result through a pointer-valued array alias",
                    line,
                    col,
                )
            elif aggregate:
                self.context.error(
                    f"{subject} cannot use an array initializer for a pointer-valued array alias",
                    line,
                    col,
                )
            return
        if (
            canonical is not None
            and canonical.is_array
            and not aggregate
            and not self._is_gpu_array_initializer(initializer)
        ):
            self.context.error(f"{subject} requires an array initializer", line, col)

    def _array_target_value_type(self, target, inferred):
        if isinstance(target, Identifier):
            symbol = self.scope.lookup(target.name)
            if symbol is not None:
                if symbol.kind in {"param", "lambda_param"}:
                    return self._array_parameter_value_type(symbol.type)
                return self._array_value_type(symbol.type)
        member, _ = self._array_target_member(target)
        if member is not None:
            return self._array_field_value_type(member, inferred)
        return self._array_value_type(inferred)

    def _is_pointer_backed_array_target(self, target, inferred) -> bool:
        canonical = self._canonical_type(inferred)
        if canonical is None or not canonical.is_array:
            return False
        if isinstance(target, Identifier):
            symbol = self.scope.lookup(target.name)
            return bool(symbol and symbol.kind == "param")
        member, storage = self._array_target_member(target)
        if member is None:
            return False
        if storage == "property":
            return member.access != "class" and canonical.array_size is None
        if canonical.array_size is not None:
            return False
        if storage in {"instance-field", "struct-field"}:
            return True
        return storage == "static-field" and not isinstance(
            member.initializer,
            (BraceInitializer, ListLiteral),
        )

    def _array_target_has_capacity(self, target, inferred) -> bool:
        inferred = self._array_target_value_type(target, inferred)
        canonical = self._canonical_type(inferred)
        if canonical is None:
            return False
        if canonical.base in {"Array", "Vector"} and canonical.generic_args:
            return True
        if not canonical.is_array:
            return False
        if isinstance(target, FieldAccessExpr):
            member, storage = self._array_target_member(target)
            if canonical.array_size is not None and storage in {
                "instance-field",
                "struct-field",
            }:
                return True
            return bool(
                member
                and storage == "static-field"
                and member.type.is_array
                and isinstance(member.initializer, (BraceInitializer, ListLiteral))
            )
        if not isinstance(target, Identifier):
            return False
        symbol = self.scope.lookup(target.name)
        if symbol and symbol.kind == "param":
            return False
        if canonical.is_extern and canonical.array_size is None:
            return False
        return not self._is_pointer_backed_array_target(target, canonical)

    def _array_target_member(self, target):
        if not isinstance(target, FieldAccessExpr) or target.optional:
            return None, None
        if isinstance(target.obj, Identifier) and self.scope.lookup(target.obj.name) is None:
            class_info = self.declarations.class_table.get(target.obj.name)
            if class_info is not None:
                member = class_info.static_fields.get(target.field)
                if member is not None:
                    return member, "static-field"
                prop = class_info.properties.get(target.field)
                if prop is not None and prop.access == "class":
                    return prop, "property"

        receiver = self._canonical_type(self._infer_type(target.obj))
        if receiver is None:
            return None, None
        class_info = self.declarations.class_table.get(receiver.base)
        if class_info is not None:
            prop = class_info.properties.get(target.field)
            if prop is not None:
                return prop, "property"
            member = class_info.fields.get(target.field)
            if member is not None:
                return member, "instance-field"
        struct_name = receiver.base.removeprefix("struct ")
        structure = self.declarations.struct_table.get(struct_name)
        if structure is not None:
            member = next(
                (field for field in structure.fields if field.name == target.field),
                None,
            )
            if member is not None:
                return member, "struct-field"
        return None, None

    def _is_gpu_output_assignment(self, expression) -> bool:
        """Recognize the GPU dispatch lowering that writes into a host buffer."""
        if expression.op != "=" or not isinstance(expression.value, CallExpr):
            return False
        callee = expression.value.callee
        if not isinstance(callee, Identifier):
            return False
        symbol = self.scope.lookup(callee.name)
        if symbol is not None and symbol.kind != "function":
            return False
        declaration = self.declarations.function_table.get(callee.name)
        return bool(declaration and declaration.is_gpu and declaration.return_type and declaration.return_type.is_array)


__all__ = ["ArrayContractsMixin"]
