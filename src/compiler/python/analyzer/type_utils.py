"""Type utilities: method return type lookup, compatibility checking."""

from __future__ import annotations

from ..ast_nodes import TypeExpr
from ..numeric_semantics import is_known_integer_typedef_name
from ..string_methods import STRING_METHODS
from ..type_composition import compose_type_expr, nullable_collapses_reference_layer
from ..type_identity import TypeShapeError, substitute_type_expr


class TypeUtilsMixin:
    _NUMERIC_TYPES = frozenset(
        (
            "byte",
            "char",
            "short",
            "short int",
            "int",
            "long",
            "long int",
            "long long",
            "long long int",
            "float",
            "double",
            "long double",
            "uint",
            "unsigned int",
            "signed",
            "unsigned",
            "unsigned char",
            "unsigned short",
            "unsigned short int",
            "unsigned long",
            "unsigned long int",
            "unsigned long long",
            "unsigned long long int",
            "signed char",
            "signed short",
            "signed short int",
            "signed int",
            "signed long",
            "signed long int",
            "signed long long",
            "signed long long int",
        )
    )

    def _string_method_return_type(self, method_name: str) -> TypeExpr | None:
        """Return the type of a string method call (shared spec table)."""
        spec = STRING_METHODS.get(method_name)
        if spec is None:
            return None
        if spec.return_type == "string*":
            return TypeExpr(base="string", pointer_depth=1)
        return TypeExpr(base=spec.return_type)

    def _format_type(self, t) -> str:
        """Format a TypeExpr for error messages."""
        result = t.base
        if t.generic_args:
            args = ", ".join(self._format_type(a) for a in t.generic_args)
            result += f"<{args}>"
        result += "*" * t.pointer_depth
        if t.is_array:
            result += "[]"
        return result

    def _is_opaque_c_scalar(self, type_expr) -> bool:
        """Whether a type is an unresolved C/POSIX scalar typedef.

        Imported headers do not expose typedef definitions to the btrc parser,
        so only the shared, explicit C/POSIX integer registry is admitted.
        """
        return bool(
            type_expr
            and (is_known_integer_typedef_name(type_expr.base) or type_expr.base.startswith("enum "))
            and type_expr.pointer_depth == 0
            and not type_expr.is_array
            and not type_expr.generic_args
        )

    def _is_native_enum_scalar(self, type_expr) -> bool:
        """Whether ``type_expr`` is an int-backed btrc enum value."""
        return bool(
            type_expr
            and type_expr.base in self.enum_table
            and type_expr.pointer_depth == 0
            and not type_expr.is_array
            and not type_expr.generic_args
        )

    def _types_compatible(self, target, source) -> bool:
        """Check if source type can be assigned to target type."""
        if target is None or source is None:
            return False
        target = self._array_value_type(target)
        source = self._array_value_type(source)
        target = self._canonical_type(target)
        source = self._canonical_type(source)

        # The null literal is compatible only with nullable/pointer values.
        if source.base == "null" or (source.base == "void" and source.pointer_depth > 0):
            return target.pointer_depth > 0 or target.is_array or target.base == "string"

        # Nullable sugar adds one pointer level. While analyzing a generic
        # template, ``T`` may later become an intrinsic reference type (where
        # that extra level collapses) or a value type. Defer the lift from T to
        # T? until the concrete instance is lowered instead of rejecting valid
        # reference-type instances such as Box<string>.
        if (
            target.base == source.base
            and self._is_active_type_parameter(target)
            and target.is_nullable
            and target.pointer_depth == source.pointer_depth + 1
        ):
            return self._generic_args_equal(target, source)

        # C array expressions decay to a pointer to their first element when
        # passed to functions or used as values.
        if (
            source.is_array
            and not target.is_array
            and target.base == source.base
            and target.pointer_depth == source.pointer_depth + 1
        ):
            return self._const_conversion_allowed(target, source) and self._generic_args_equal(target, source)

        if target.base == source.base:
            if self._semantic_pointer_depth(target) != self._semantic_pointer_depth(source):
                return False
            if target.is_array != source.is_array:
                return False
            return self._const_conversion_allowed(target, source) and self._generic_args_equal(target, source)

        if (
            target.base in self._NUMERIC_TYPES
            and source.base in self._NUMERIC_TYPES
            and target.pointer_depth == source.pointer_depth == 0
            and not target.is_array
            and not source.is_array
            and not target.generic_args
            and not source.generic_args
        ):
            return True
        if (
            (self._is_opaque_c_scalar(target) and source.base in self._NUMERIC_TYPES)
            or (self._is_opaque_c_scalar(source) and target.base in self._NUMERIC_TYPES)
            or (self._is_opaque_c_scalar(target) and self._is_opaque_c_scalar(source))
        ):
            return True
        if (self._is_native_enum_scalar(target) and source.base in self._NUMERIC_TYPES) or (
            self._is_native_enum_scalar(source) and target.base in self._NUMERIC_TYPES
        ):
            return True
        if target.base == "string" and source.base == "char" and (source.pointer_depth >= 1 or source.is_array):
            return self._const_conversion_allowed(target, source)
        if source.base == "string" and target.base == "char" and (target.pointer_depth >= 1 or target.is_array):
            return self._const_conversion_allowed(target, source)
        from ..string_conversion import requires_class_to_string

        if requires_class_to_string(
            self.class_table,
            target,
            source,
            canonicalize=self._canonical_type,
        ):
            return True
        # ISO C permits object-pointer conversions through void*.
        if (
            target.base == "void"
            and target.pointer_depth == 1
            and (self._semantic_pointer_depth(source) > 0 or source.is_array)
        ):
            return self._const_conversion_allowed(target, source)
        if (
            source.base == "void"
            and source.pointer_depth == 1
            and (self._semantic_pointer_depth(target) > 0 or target.is_array)
        ):
            return self._const_conversion_allowed(target, source)
        if target.base in self.class_table and source.base in self.class_table:
            return self._reference_shapes_compatible(target, source) and self._is_subclass(source.base, target.base)
        if target.base in self.interface_table and source.base in self.class_table:
            return self._reference_shapes_compatible(target, source) and self._is_subclass(source.base, target.base)
        if target.base in self.interface_table and source.base in self.interface_table:
            return self._reference_shapes_compatible(target, source) and self._is_interface_subtype(
                source.base, target.base
            )
        return False

    def _is_active_type_parameter(self, type_expr) -> bool:
        if type_expr is None or type_expr.generic_args:
            return False
        parameters = set(
            (self.current_class.generic_params if self.current_class else [])
            + (self.current_method.generic_params if self.current_method else [])
        )
        return type_expr.base in parameters

    def _generic_args_equal(self, left, right) -> bool:
        left_args = left.generic_args or []
        right_args = right.generic_args or []
        return len(left_args) == len(right_args) and all(self._types_equal(a, b) for a, b in zip(left_args, right_args))

    def _types_equal(self, left, right) -> bool:
        """Position-independent structural equality for signature types."""
        if left is None or right is None:
            return left is right
        left = self._canonical_type(left)
        right = self._canonical_type(right)
        if (
            left.base != right.base
            or (self._semantic_pointer_depth(left) != self._semantic_pointer_depth(right))
            or left.is_array != right.is_array
            or left.is_nullable != right.is_nullable
            or left.is_const != right.is_const
            or left.is_volatile != right.is_volatile
        ):
            return False
        left_args = left.generic_args or []
        right_args = right.generic_args or []
        return len(left_args) == len(right_args) and all(self._types_equal(a, b) for a, b in zip(left_args, right_args))

    def _semantic_pointer_depth(self, type_expr) -> int:
        """Pointer depth after intrinsic-reference nullable sugar collapses."""
        depth = type_expr.pointer_depth
        intrinsic_base = type_expr.base in {"string", "Thread", "Mutex", "__fn_ptr"}
        if nullable_collapses_reference_layer(
            type_expr,
            base_is_reference=intrinsic_base,
        ):
            depth -= 1
        if intrinsic_base:
            depth += 1
        elif type_expr.base in {"Vector", "List", "Map", "Set", "Array"} and type_expr.generic_args and depth == 0:
            depth = 1
        return depth

    def _canonical_type(self, type_expr, seen=None):
        """Resolve typedef aliases while preserving use-site modifiers."""
        if type_expr is None or type_expr.base not in self.typedef_table:
            return type_expr
        seen = set() if seen is None else seen
        if type_expr.base in seen:
            return type_expr
        seen.add(type_expr.base)
        resolved = self._canonical_type(self.typedef_table[type_expr.base], seen)
        return compose_type_expr(type_expr, resolved, reference_shape=resolved)

    def _is_interface_subtype(self, child: str, parent: str) -> bool:
        """Whether an interface is the same as or transitively extends another."""
        current = child
        visited: set[str] = set()
        while current and current not in visited:
            if current == parent:
                return True
            visited.add(current)
            info = self.interface_table.get(current)
            current = info.parent if info else None
        return False

    def _is_subclass(self, child: str, parent: str) -> bool:
        """Check if child class extends parent (directly or transitively)."""
        if child == parent:
            return True
        info = self.class_table.get(child)
        if not info:
            return False
        if parent in self.interface_table:
            cur = info
            visited = set()
            while cur and cur.name not in visited:
                visited.add(cur.name)
                if any(self._is_interface_subtype(interface, parent) for interface in cur.interfaces):
                    return True
                cur = self.class_table.get(cur.parent) if cur.parent else None
            return False
        visited = set()
        while info and info.parent and info.parent not in visited:
            visited.add(info.parent)
            if info.parent == parent:
                return True
            info = self.class_table.get(info.parent)
        return False

    def _substitute_type(self, t: TypeExpr | None, subs: dict) -> TypeExpr | None:
        """Recursively substitute type parameters in a TypeExpr."""
        try:
            return substitute_type_expr(t, subs, reference_resolver=self._canonical_type)
        except TypeShapeError as error:
            self._report_type_shape_error(str(error), error.type_expr or t, getattr(t, "line", 0), getattr(t, "col", 0))
            return t
