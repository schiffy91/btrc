"""Owned C type rendering plus stateless IR type predicates and identity."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from ...ast_nodes import TypeExpr
from ...type_composition import (
    nullable_collapses_reference_layer,
    resolved_reference_shape,
)
from ...type_identity import TypeIdentity
from ..nodes import CType, IRFunctionPointerTypedef

if TYPE_CHECKING:
    from .default_arguments import DefaultArgumentLoweringContext

# Primitive btrc types → C type strings
_PRIMITIVE_MAP = {
    "int": "int",
    "float": "float",
    "double": "double",
    "bool": "bool",
    "char": "char",
    "string": "char*",
    "void": "void",
    "long": "long",
    "short": "short",
    "byte": "unsigned char",
    "uint": "unsigned int",
    "size_t": "size_t",
}


_FnPtrSignature = tuple[str, tuple[str, ...]]


class FunctionPointerTypedefRegistry:
    """Own ordered callback declarations for one C translation unit."""

    def __init__(self, type_identity: TypeIdentity) -> None:
        self._type_identity = type_identity
        self._definitions: dict[str, _FnPtrSignature] = {}
        self._emitted: set[str] = set()

    def register(
        self,
        type_expr: TypeExpr,
        *,
        return_type: str,
        parameter_types: list[str],
    ) -> str:
        name = self._type_identity.function_pointer_symbol(type_expr.generic_args)
        self._definitions.setdefault(name, (return_type, tuple(parameter_types)))
        return name

    def consume_pending(self) -> list[IRFunctionPointerTypedef]:
        pending = [
            IRFunctionPointerTypedef(
                name=name,
                return_type=CType(text=return_type),
                param_types=[CType(text=parameter) for parameter in parameters],
            )
            for name, (return_type, parameters) in self._definitions.items()
            if name not in self._emitted
        ]
        self._emitted.update(self._definitions)
        return pending


class CTypeRenderer:
    """Render source types and own callback typedefs for one lowering run."""

    def __init__(
        self,
        typedefs: Mapping[str, TypeExpr] | None = None,
        default_arguments: DefaultArgumentLoweringContext | None = None,
        type_identity: TypeIdentity | None = None,
    ) -> None:
        self.type_identity = type_identity if type_identity is not None else TypeIdentity()
        self._typedefs = MappingProxyType(dict(typedefs or {}))
        self._function_pointers = FunctionPointerTypedefRegistry(self.type_identity)
        self._default_arguments = default_arguments

    def render(self, type_expr: TypeExpr | None) -> str:
        """Convert one btrc type to its source-preserving C spelling."""
        if self._default_arguments is not None:
            type_expr = self._default_arguments.resolve_type(type_expr)
        if type_expr is None:
            return "void"
        base = type_expr.base
        prefix = "const " if getattr(type_expr, "is_const", False) else ""

        if base == "__fn_ptr" and type_expr.generic_args:
            c_type = self._function_pointer_name(type_expr)
        elif base == "Thread" and type_expr.generic_args:
            c_type = "__btrc_thread_t*"
        elif base == "Mutex" and type_expr.generic_args:
            c_type = "__btrc_mutex_val_t*"
        elif base in _PRIMITIVE_MAP and not type_expr.generic_args:
            c_type = _PRIMITIVE_MAP[base]
        elif base == "Tuple" or base.startswith("("):
            c_type = (
                self.type_identity.generic_symbol("Tuple", type_expr.generic_args)
                if type_expr.generic_args
                else "btrc_Tuple"
            )
        elif type_expr.generic_args:
            self.type_identity.ensure_supported_generic_arguments(type_expr.generic_args)
            c_type = self.type_identity.generic_symbol(base, type_expr.generic_args)
        else:
            c_type = base

        depth = type_expr.pointer_depth
        base_is_reference = c_type.endswith("*") or base == "__fn_ptr" or self._typedef_base_is_reference(base)
        if nullable_collapses_reference_layer(
            type_expr,
            base_is_reference=base_is_reference,
        ):
            depth -= 1
        c_type += "*" * depth
        if type_expr.is_array:
            c_type += "*"
        return prefix + c_type

    def element_type(self, type_expr: TypeExpr) -> str:
        """Render a collection's element C type."""
        if type_expr.generic_args:
            return self.render(type_expr.generic_args[0])
        return "void*"

    def format_spec(self, type_expr: TypeExpr | None) -> str:
        """Return the portable printf format for one source type."""
        if type_expr is None:
            return "%d"
        base = type_expr.base
        if base == "__fn_ptr":
            return "%s"
        if self.type_identity.is_scalar_string(type_expr) or self.type_identity.is_c_string_pointer(type_expr):
            return "%s"
        if self.render(type_expr).rstrip().endswith("*") or type_expr.is_array:
            return "%p"
        if base in (
            "int",
            "short",
            "short int",
            "signed int",
            "signed short",
            "signed short int",
        ):
            return "%d"
        if base in (
            "byte",
            "uint",
            "unsigned int",
            "unsigned short",
            "unsigned short int",
            "unsigned char",
        ):
            return "%u"
        if base in ("long", "long int", "signed long", "signed long int"):
            return "%ld"
        if base in ("unsigned long", "unsigned long int"):
            return "%lu"
        if base in (
            "long long",
            "long long int",
            "signed long long",
            "signed long long int",
        ):
            return "%lld"
        if base in ("unsigned long long", "unsigned long long int"):
            return "%llu"
        if base == "size_t":
            return "%zu"
        if base in ("float", "double"):
            return "%f"
        if base == "long double":
            return "%Lf"
        if base == "char":
            return "%c"
        if base == "bool":
            return "%s"
        return "%d"

    def consume_function_pointer_typedefs(self) -> list[IRFunctionPointerTypedef]:
        """Drain callback declarations registered since the previous phase."""
        return self._function_pointers.consume_pending()

    def _function_pointer_name(self, type_expr: TypeExpr) -> str:
        # Recursive rendering registers nested callbacks before their owners.
        return_type = self.render(type_expr.generic_args[0])
        parameter_types = [self.render(argument) for argument in type_expr.generic_args[1:]]
        return self._function_pointers.register(
            type_expr,
            return_type=return_type,
            parameter_types=parameter_types,
        )

    def _typedef_base_is_reference(self, base: str) -> bool:
        if base not in self._typedefs:
            return False
        from .type_resolution import canonical_type

        resolved = canonical_type(TypeExpr(base=base), dict(self._typedefs))
        return bool(resolved and resolved_reference_shape(resolved))


def is_pointer_type(t: TypeExpr | None) -> bool:
    """Check if a type is a pointer (class instance, pointer depth > 0)."""
    if t is None:
        return False
    if t.pointer_depth > 0:
        return True
    if t.base in _PRIMITIVE_MAP and not t.generic_args:
        return t.base == "string"
    # User classes and generic collections are heap-allocated (pointers)
    return t.base not in _PRIMITIVE_MAP or t.generic_args


def is_numeric_type(t: TypeExpr | None) -> bool:
    """Check if a type is numeric."""
    if t is None:
        return False
    return t.base in {"int", "float", "double", "long", "short", "byte", "uint"}


def is_generic_class_type(t: TypeExpr | None, class_table: dict) -> bool:
    """Check if a type is a generic class (registered with generic_params)."""
    if t is None or not t.generic_args:
        return False
    info = class_table.get(t.base)
    return info is not None and bool(info.generic_params)


def is_direct_generic_instance_reference(
    t: TypeExpr | None,
    class_table: dict,
) -> bool:
    """Whether ``t`` is one generic heap reference, not storage around it."""
    if not is_generic_class_type(t, class_table) or t.is_array:
        return False
    # Analyzer normalization upgrades class values from semantic depth 0 to C
    # reference depth 1.  A composed/raw pointer around that value is depth 2+.
    depth = t.pointer_depth - int(nullable_collapses_reference_layer(t))
    return depth <= 1


__all__ = [
    "CTypeRenderer",
    "FunctionPointerTypedefRegistry",
    "is_direct_generic_instance_reference",
    "is_generic_class_type",
    "is_numeric_type",
    "is_pointer_type",
]
