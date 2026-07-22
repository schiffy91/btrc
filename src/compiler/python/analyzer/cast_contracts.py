"""Strict-C contracts for explicit casts."""

from ..type_identity import is_semantic_scalar_void

_PRIMITIVE_TYPE_NAMES = frozenset(
    (
        "void",
        "bool",
        "byte",
        "char",
        "short",
        "int",
        "long",
        "float",
        "double",
        "string",
        "uint",
        "unsigned",
        "signed",
    )
)

_BUILTIN_CAST_BASES = frozenset(("Vector", "List", "Map", "Set", "Array", "Thread", "Mutex", "Tuple"))

_RUNTIME_AGGREGATE_BASES = frozenset(("Vector", "List", "Map", "Set", "Array", "Tuple"))


class CastContractsMixin:
    def _validate_cast_expr(self, expression) -> None:
        if not self._validate_cast_target_name(expression):
            return
        target = self._canonical_type(expression.target_type)
        source = self._canonical_type(self._infer_type(expression.expr))
        if target is None or source is None:
            return
        if source.base == "Thread":
            self._reject_thread_value_escape(expression.expr, "cast")
            return
        if self._nonportable_pointer_integer_cast(
            source,
            target,
            expression.expr,
        ):
            self._error(
                "Pointer/integer casts require intptr_t or uintptr_t",
                expression.line,
                expression.col,
            )
            return

        if self._is_void_value(source):
            if not self._is_void_value(target):
                self._error(
                    f"Cannot cast void expression to '{self._format_type(target)}'",
                    expression.line,
                    expression.col,
                )
            return
        if not self._is_scalar_cast_value(source):
            return

        struct_name = target.base.removeprefix("struct ")
        if (
            struct_name in self.struct_table
            and target.pointer_depth == 0
            and not target.is_array
            and not target.generic_args
        ):
            self._error(
                f"Cannot cast scalar '{self._format_type(source)}' to aggregate struct '{struct_name}'",
                expression.line,
                expression.col,
            )
        elif (
            target.base in _RUNTIME_AGGREGATE_BASES
            and target.generic_args
            and target.pointer_depth == 0
            and not target.is_array
        ):
            self._error(
                f"Cannot cast scalar '{self._format_type(source)}' to "
                f"runtime generic value '{self._format_type(target)}'",
                expression.line,
                expression.col,
            )

    def _validate_cast_target_name(self, expression) -> bool:
        """Reject unknown bare names while preserving explicit C type syntax."""
        target = expression.target_type
        if target is None:
            return False
        if target.pointer_depth or target.generic_args or target.is_array or target.is_nullable:
            return True
        base = target.base
        if not base.isidentifier():
            return True
        if base in _PRIMITIVE_TYPE_NAMES or base in _BUILTIN_CAST_BASES:
            return True
        if (
            base in self.class_table
            or base in self.interface_table
            or base in self.enum_table
            or base in self.rich_enum_table
            or base in getattr(self, "declared_type_names", ())
        ):
            return True
        if self.current_class and base in self.current_class.generic_params:
            return True
        if base.endswith("_t"):
            return True
        self._error(f"Unknown type '{base}' in cast", expression.line, expression.col)
        return False

    def _is_void_value(self, type_expr) -> bool:
        return is_semantic_scalar_void(type_expr)

    def _nonportable_pointer_integer_cast(self, source, target, value) -> bool:
        source_pointer = bool(source.is_array or source.pointer_depth > 0 or self._managed_result_type(source))
        target_pointer = bool(target.is_array or target.pointer_depth > 0 or self._managed_result_type(target))
        if source_pointer == target_pointer:
            return False
        if target_pointer and not source_pointer and self._is_known_numeric_zero(value):
            return False
        scalar = target if source_pointer else source
        if scalar.base in {"intptr_t", "uintptr_t"}:
            return False
        return bool(
            scalar.pointer_depth == 0
            and not scalar.is_array
            and (
                self._is_numeric_value(scalar)
                or self._is_opaque_c_scalar(scalar)
                or self._is_native_enum_scalar(scalar)
            )
        )

    def _is_scalar_cast_value(self, type_expr) -> bool:
        if type_expr is None:
            return False
        if type_expr.pointer_depth > 0 or type_expr.is_array or type_expr.base == "string":
            return True
        return bool(
            type_expr.base == "bool"
            or self._is_numeric_value(type_expr)
            or self._is_opaque_c_scalar(type_expr)
            or self._is_native_enum_scalar(type_expr)
        )


__all__ = ["CastContractsMixin"]
