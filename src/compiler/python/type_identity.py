"""Owned recursive identity, shape policy, and symbol spelling for source types."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace

from .ast_nodes import TypeExpr
from .type_composition import compose_type_expr, nullable_collapses_reference_layer


class TypeShapeError(ValueError):
    """A type shape cannot be represented as a coherent specialization."""

    def __init__(self, message: str, type_expr: TypeExpr | None = None):
        self.type_expr = type_expr
        super().__init__(message)


@dataclass(frozen=True, slots=True, init=False)
class TypeIdentity:
    """Own type-shape validity and generated-symbol identity for one compiler.

    The policy is immutable after construction.  Compiler composition roots
    share one instance across semantic analysis and IR lowering, while direct
    stage construction receives an isolated default instance.
    """

    _reserved_prefix: str
    _forbidden_generic_flags: tuple[tuple[str, str], ...]

    def __init__(
        self,
        *,
        reserved_prefix: str = "ZQ",
        forbidden_generic_flags: Iterable[tuple[str, str]] | None = None,
    ) -> None:
        if not self._is_ascii_identifier(reserved_prefix):
            raise ValueError("reserved type-symbol prefix must be a non-empty ASCII identifier")
        object.__setattr__(self, "_reserved_prefix", reserved_prefix)
        object.__setattr__(
            self,
            "_forbidden_generic_flags",
            tuple(
                forbidden_generic_flags
                if forbidden_generic_flags is not None
                else (
                    ("is_const", "const"),
                    ("is_static", "static"),
                    ("is_extern", "extern"),
                    ("is_volatile", "volatile"),
                )
            ),
        )

    @property
    def reserved_prefix(self) -> str:
        return self._reserved_prefix

    @property
    def forbidden_generic_flags(self) -> tuple[tuple[str, str], ...]:
        return self._forbidden_generic_flags

    def shape_key(self, type_expr: TypeExpr) -> tuple:
        """Return the position-independent semantic identity of ``type_expr``."""
        return (
            type_expr.base,
            tuple(self.shape_key(argument) for argument in (type_expr.generic_args or [])),
            type_expr.pointer_depth,
            bool(type_expr.is_nullable),
            type_expr.nullable_outer_depth,
            bool(type_expr.is_array),
            bool(type_expr.is_const),
            bool(type_expr.is_static),
            bool(type_expr.is_extern),
            bool(type_expr.is_volatile),
        )

    def generic_instance_key(self, base: str, arguments: Iterable[TypeExpr]) -> tuple:
        """Canonical analyzer/IR key for one generic class specialization."""
        return base, tuple(self.shape_key(argument) for argument in arguments)

    def references_names(self, type_expr: TypeExpr, names: Iterable[str]) -> bool:
        """Return whether a recursive type shape still names a parameter."""
        parameter_names = frozenset(names)
        return self._references_names(type_expr, parameter_names)

    def generic_argument_problem(self, type_expr: TypeExpr) -> tuple[str, TypeExpr] | None:
        """Return the first unsupported generic-argument modifier."""
        for attribute, spelling in self._forbidden_generic_flags:
            if getattr(type_expr, attribute, False):
                return f"generic arguments cannot be {spelling}-qualified", type_expr
        for argument in type_expr.generic_args or []:
            problem = self.generic_argument_problem(argument)
            if problem is not None:
                return problem
        return None

    def ensure_supported_generic_arguments(self, arguments: Iterable[TypeExpr]) -> None:
        """Fail closed when codegen sees an analyzer-rejected argument."""
        for argument in arguments:
            problem = self.generic_argument_problem(argument)
            if problem is not None:
                message, bad_type = problem
                raise TypeShapeError(message, bad_type)

    def substitute(
        self,
        type_expr: TypeExpr | None,
        substitutions: Mapping[str, TypeExpr],
        *,
        reference_resolver: Callable[[TypeExpr], TypeExpr | None] | None = None,
    ) -> TypeExpr | None:
        """Substitute recursively, composing every representable modifier.

        ``reference_resolver`` makes typedefs transparent only for shape
        decisions.  The returned value keeps the substitution's source
        spelling so generated specialization identities remain stable.
        """
        if type_expr is None:
            return None
        if type_expr.base in substitutions and not type_expr.generic_args:
            resolved = substitutions[type_expr.base]
            reference_shape = reference_resolver(resolved) if reference_resolver else resolved
            reference_shape = reference_shape or resolved
            if type_expr.is_array and reference_shape.is_array:
                raise TypeShapeError(
                    f"nested array composition for type parameter '{type_expr.base}' is not supported",
                    type_expr,
                )
            return compose_type_expr(type_expr, resolved, reference_shape=reference_shape)
        if type_expr.generic_args:
            return replace(
                type_expr,
                generic_args=[
                    self.substitute(
                        argument,
                        substitutions,
                        reference_resolver=reference_resolver,
                    )
                    for argument in type_expr.generic_args
                ],
            )
        return type_expr

    def is_scalar_string(self, type_expr: TypeExpr | None) -> bool:
        """True only for a string represented by one collapsed ``char*``."""
        if type_expr is None or type_expr.base != "string" or type_expr.generic_args or type_expr.is_array:
            return False
        depth = type_expr.pointer_depth
        if nullable_collapses_reference_layer(type_expr, base_is_reference=True):
            depth -= 1
        return depth == 0

    def is_scalar_void(self, type_expr: TypeExpr | None) -> bool:
        """True only for scalar ``void``, never ``void*``."""
        return bool(
            type_expr
            and type_expr.base == "void"
            and type_expr.pointer_depth == 0
            and not type_expr.is_array
            and not type_expr.generic_args
        )

    def is_null(self, type_expr: TypeExpr | None) -> bool:
        """Whether a type is the nullable null-literal domain."""
        return bool(
            type_expr and type_expr.base in {"null", "void"} and type_expr.pointer_depth > 0 and type_expr.is_nullable
        )

    def is_c_string_pointer(self, type_expr: TypeExpr | None) -> bool:
        """Whether a C interop type is exactly one ``char`` pointer/array."""
        return bool(
            type_expr
            and type_expr.base == "char"
            and type_expr.pointer_depth + int(type_expr.is_array) == 1
            and not type_expr.generic_args
        )

    def is_reference(
        self,
        type_expr: TypeExpr | None,
        class_table: Mapping[str, object] | None = None,
        interface_table: Mapping[str, object] | None = None,
    ) -> bool:
        """Whether a concrete source value belongs to a reference domain."""
        if type_expr is None:
            return False
        if self.is_null(type_expr) or self.is_scalar_string(type_expr):
            return True
        classes = class_table or {}
        interfaces = interface_table or {}
        return bool(
            type_expr.pointer_depth > 0
            or type_expr.is_array
            or type_expr.base in classes
            or type_expr.base in interfaces
            or type_expr.base in {"Thread", "Mutex", "__fn_ptr"}
        )

    def references_compatible(
        self,
        left: TypeExpr | None,
        right: TypeExpr | None,
        class_table: Mapping[str, object] | None = None,
        interface_table: Mapping[str, object] | None = None,
    ) -> bool:
        """Whether two concrete reference domains have a portable C relation."""
        classes = class_table or {}
        interfaces = interface_table or {}
        if self.is_null(left):
            return self.is_reference(right, classes, interfaces)
        if self.is_null(right):
            return self.is_reference(left, classes, interfaces)
        if not (self.is_reference(left, classes, interfaces) and self.is_reference(right, classes, interfaces)):
            return False
        assert left is not None and right is not None
        if left.base == "__fn_ptr" or right.base == "__fn_ptr":
            return left.base == right.base == "__fn_ptr" and left.generic_args == right.generic_args
        if self._is_void_pointer(left) or self._is_void_pointer(right):
            return True
        if (self.is_scalar_string(left) and self.is_c_string_pointer(right)) or (
            self.is_scalar_string(right) and self.is_c_string_pointer(left)
        ):
            return True
        if self._reference_depth(left) != self._reference_depth(right):
            return False
        if left.base == right.base:
            return left.generic_args == right.generic_args
        if (left.base not in classes and left.base not in interfaces) or (
            right.base not in classes and right.base not in interfaces
        ):
            return False
        return self._specialization_is_subtype(
            left,
            right,
            classes,
            interfaces,
        ) or self._specialization_is_subtype(
            right,
            left,
            classes,
            interfaces,
        )

    def nominally_related(
        self,
        left: str,
        right: str,
        class_table: Mapping[str, object],
        interface_table: Mapping[str, object],
    ) -> bool:
        """Whether either nominal type is an ancestor of the other."""
        return self._is_nominal_subtype(
            left,
            right,
            class_table,
            interface_table,
        ) or self._is_nominal_subtype(
            right,
            left,
            class_table,
            interface_table,
        )

    def symbol_component(self, type_expr: TypeExpr) -> str:
        """Return an injective C-identifier component for one type."""
        legacy = self._legacy_component(type_expr)
        return legacy if legacy is not None else self._reserved_prefix + "t" + self._encode_type(type_expr)

    def generic_symbol(self, base: str, arguments: Iterable[TypeExpr]) -> str:
        """Return an injective C symbol for a parameterized type."""
        arguments = tuple(arguments)
        legacy_arguments = self._legacy_sequence(arguments)
        if self._safe_base(base) and legacy_arguments is not None:
            suffix = f"_{legacy_arguments}" if legacy_arguments else ""
            return f"btrc_{base}{suffix}"
        return "btrc_" + self._reserved_prefix + "g" + self._encode_name_and_types(base, arguments)

    def specialization_symbol(self, base: str, arguments: Iterable[TypeExpr]) -> str:
        """Validate and spell one concrete generic class specialization."""
        arguments = tuple(arguments)
        self.ensure_supported_generic_arguments(arguments)
        return self.generic_symbol(base, arguments)

    def method_instance_symbol(
        self,
        class_base: str,
        class_arguments: Iterable[TypeExpr],
        method_name: str,
        method_arguments: Iterable[TypeExpr],
    ) -> str:
        """Return a symbol for class- and method-level substitutions."""
        class_arguments = tuple(class_arguments)
        method_arguments = tuple(method_arguments)
        self.ensure_supported_generic_arguments((*class_arguments, *method_arguments))
        class_legacy = self._legacy_sequence(class_arguments)
        method_legacy = self._legacy_sequence(method_arguments)
        if (
            self._safe_base(class_base)
            and self._safe_base(method_name)
            and class_legacy is not None
            and method_legacy is not None
        ):
            class_part = class_base
            if class_arguments:
                class_part = f"btrc_{class_base}_{class_legacy}"
            method_part = f"_{method_name}"
            if method_legacy:
                method_part += f"_{method_legacy}"
            return class_part + method_part
        payload = self._encode_name_and_types(class_base, class_arguments)
        payload += self._field("m", method_name.encode("utf-8").hex())
        payload += self._encode_types(method_arguments)
        return "btrc_" + self._reserved_prefix + "m" + payload

    def function_pointer_symbol(self, arguments: Iterable[TypeExpr]) -> str:
        """Return an injective typedef name for a function-pointer signature."""
        arguments = tuple(arguments)
        legacy = self._legacy_sequence(arguments)
        if legacy is not None:
            return f"__btrc_fn_{legacy}"
        return f"__btrc_fn_{self._reserved_prefix}f{self._encode_types(arguments)}"

    def _references_names(self, type_expr: TypeExpr, names: frozenset[str]) -> bool:
        if type_expr.base in names:
            return True
        return any(self._references_names(argument, names) for argument in type_expr.generic_args or [])

    def _reference_depth(self, type_expr: TypeExpr) -> int:
        depth = type_expr.pointer_depth + int(type_expr.is_array)
        intrinsic_base = type_expr.base in {"string", "Thread", "Mutex", "__fn_ptr"}
        collapse = nullable_collapses_reference_layer(
            type_expr,
            base_is_reference=intrinsic_base,
        )
        return depth - int(collapse) + int(intrinsic_base)

    def _is_void_pointer(self, type_expr: TypeExpr) -> bool:
        return type_expr.base == "void" and self._reference_depth(type_expr) == 1

    def _specialization_is_subtype(
        self,
        child: TypeExpr,
        parent: TypeExpr,
        class_table: Mapping[str, object],
        interface_table: Mapping[str, object],
    ) -> bool:
        pending = [(child.base, tuple(child.generic_args))]
        seen = set()
        while pending:
            name, arguments = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            if name == parent.base:
                return arguments == tuple(parent.generic_args)
            info = class_table.get(name) or interface_table.get(name)
            if info is None:
                continue
            ancestors = (
                getattr(info, "parent", None),
                *(getattr(info, "interfaces", ()) or ()),
            )
            for ancestor in ancestors:
                if not ancestor:
                    continue
                ancestor_info = class_table.get(ancestor) or interface_table.get(ancestor)
                if ancestor_info is None:
                    continue
                ancestor_arity = len(getattr(ancestor_info, "generic_params", ()))
                current_arity = len(getattr(info, "generic_params", ()))
                if ancestor_arity == 0:
                    ancestor_arguments = ()
                elif ancestor_arity == current_arity == len(arguments):
                    ancestor_arguments = arguments
                else:
                    continue
                pending.append((ancestor, ancestor_arguments))
        return False

    def _is_nominal_subtype(
        self,
        child: str,
        parent: str,
        class_table: Mapping[str, object],
        interface_table: Mapping[str, object],
    ) -> bool:
        pending = [child]
        seen = set()
        while pending:
            name = pending.pop()
            if name == parent:
                return True
            if name in seen:
                continue
            seen.add(name)
            info = class_table.get(name) or interface_table.get(name)
            if info is None:
                continue
            candidate_parent = getattr(info, "parent", None)
            if candidate_parent:
                pending.append(candidate_parent)
            pending.extend(getattr(info, "interfaces", ()) or ())
        return False

    def _safe_base(self, base: str) -> bool:
        return self._is_ascii_identifier(base) and not base.startswith(self._reserved_prefix)

    @staticmethod
    def _is_ascii_identifier(value: str) -> bool:
        return bool(
            value
            and value[0].isascii()
            and value[0].isalpha()
            and all(character.isascii() and character.isalnum() for character in value[1:])
        )

    def _legacy_component(self, type_expr: TypeExpr) -> str | None:
        if (
            type_expr.generic_args
            or not self._safe_base(type_expr.base)
            or type_expr.nullable_outer_depth
            or any(getattr(type_expr, flag, False) for flag, _spelling in self._forbidden_generic_flags)
        ):
            return None
        suffix = f"_p{type_expr.pointer_depth}" if type_expr.pointer_depth else ""
        if type_expr.is_nullable:
            suffix += "_n"
        if type_expr.is_array:
            suffix += "_a"
        return type_expr.base + suffix

    def _legacy_sequence(self, arguments: tuple[TypeExpr, ...]) -> str | None:
        components = [self._legacy_component(argument) for argument in arguments]
        if any(component is None for component in components):
            return None
        if len(arguments) > 1 and any(
            argument.pointer_depth or argument.is_nullable or argument.is_array for argument in arguments
        ):
            return None
        return "_".join(component for component in components if component is not None)

    @staticmethod
    def _field(tag: str, text: str) -> str:
        return f"{tag}{len(text)}_{text}"

    def _encode_type(self, type_expr: TypeExpr) -> str:
        base = type_expr.base.encode("utf-8").hex()
        qualifiers = sum(
            (1 << index) if getattr(type_expr, attribute, False) else 0
            for index, (attribute, _spelling) in enumerate(self._forbidden_generic_flags)
        )
        shape = (
            f"p{type_expr.pointer_depth}n{int(type_expr.is_nullable)}"
            f"o{type_expr.nullable_outer_depth}a{int(type_expr.is_array)}q{qualifiers}"
        )
        return self._field("b", base) + shape + self._encode_types(type_expr.generic_args or [])

    def _encode_types(self, arguments: Iterable[TypeExpr]) -> str:
        encoded = [self._encode_type(argument) for argument in arguments]
        return f"k{len(encoded)}" + "".join(self._field("t", item) for item in encoded)

    def _encode_name_and_types(self, base: str, arguments: Iterable[TypeExpr]) -> str:
        return self._field("b", base.encode("utf-8").hex()) + self._encode_types(arguments)


__all__ = ["TypeIdentity", "TypeShapeError"]
