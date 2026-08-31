"""Canonical semantic types, inference, conversions, and operators."""

from __future__ import annotations

import ctypes
import math
from collections.abc import Callable, Iterable, Mapping, Set
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import ClassVar

from src.compiler.python.analyzer.program import AnalysisSession, DeclarationIndex
from src.compiler.python.lexer.lexer import LiteralDecoder
from src.compiler.python.syntax.ast.generated import (
    BraceInitializer,
    ClassDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    ListLiteral,
    MapLiteral,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
    TypeExpr,
    VarDeclStmt,
)


@dataclass(frozen=True)
class IndexedProtocol:
    """Declared protocol names plus the signatures proven safe to lower."""

    class_info: object
    declared_getter: object | None
    declared_setter: object | None
    getter: object | None
    setter: object | None

    def substitutions(self, object_type) -> dict:
        return dict(zip(self.class_info.generic_params, object_type.generic_args))


class IndexedProtocolResolver:
    """Resolve indexed access against one compiler's analyzed class universe."""

    def __init__(self, type_identity: TypeIdentity, class_table: Mapping[str, object]) -> None:
        self._type_identity = type_identity
        self._class_table = class_table

    def resolve(self, type_expr, *, active_type_params=None) -> IndexedProtocol | None:
        """Describe a direct class value that declares ``get`` or ``set``."""
        if type_expr is None or type_expr.is_array:
            return None
        if active_type_params and type_expr.base in active_type_params:
            return None
        info = self._class_table.get(type_expr.base)
        if info is None or type_expr.pointer_depth > 1:
            return None
        getter = info.methods.get("get")
        setter = info.methods.get("set")
        if getter is None and setter is None:
            return None
        return IndexedProtocol(
            class_info=info,
            declared_getter=getter,
            declared_setter=setter,
            getter=getter if self._valid_getter(getter) else None,
            setter=setter if self._valid_setter(setter) else None,
        )

    def class_info(self, type_expr, *, method: str | None = None, active_type_params=None):
        """Return the owning class for a proven indexed method."""
        protocol = self.resolve(type_expr, active_type_params=active_type_params)
        if protocol is None:
            return None
        if method is None:
            return protocol.class_info
        if method not in {"get", "set"} or getattr(protocol, method + "ter") is None:
            return None
        return protocol.class_info

    def _valid_getter(self, method) -> bool:
        return bool(
            method
            and method.access != "class"
            and (not method.generic_params)
            and (len(method.params) == 1)
            and (not method.params[0].keep)
            and (method.return_type is not None)
            and (not self._type_identity.is_scalar_void(method.return_type))
        )

    def _valid_setter(self, method) -> bool:
        return bool(
            method
            and method.access != "class"
            and (not method.generic_params)
            and (len(method.params) == 2)
            and (not method.params[0].keep)
            and self._type_identity.is_scalar_void(method.return_type)
        )


@dataclass(frozen=True)
class CIntegerWidths:
    """Bit widths of the C integer ranks used by generated code."""

    char: int
    short: int
    int_: int
    long: int
    long_long: int

    @classmethod
    def native(cls) -> CIntegerWidths:
        """Describe the ABI targeted by the running compiler process."""
        return cls(
            char=ctypes.sizeof(ctypes.c_byte) * 8,
            short=ctypes.sizeof(ctypes.c_short) * 8,
            int_=ctypes.sizeof(ctypes.c_int) * 8,
            long=ctypes.sizeof(ctypes.c_long) * 8,
            long_long=ctypes.sizeof(ctypes.c_longlong) * 8,
        )


class NumericLiteralSemantics:
    """Own target-dependent literal typing and integral conversion."""

    _SIGNED_ALIASES = MappingProxyType(
        {
            "byte": "signed char",
            "short int": "short",
            "signed short": "short",
            "signed short int": "short",
            "signed": "int",
            "signed int": "int",
            "long int": "long",
            "signed long": "long",
            "signed long int": "long",
            "long long int": "long long",
            "signed long long": "long long",
            "signed long long int": "long long",
        }
    )
    _UNSIGNED_ALIASES = MappingProxyType(
        {
            "uint": "unsigned int",
            "unsigned": "unsigned int",
            "unsigned short int": "unsigned short",
            "unsigned long int": "unsigned long",
            "unsigned long long int": "unsigned long long",
        }
    )

    def __init__(self, widths: CIntegerWidths | None = None) -> None:
        self.widths = widths if widths is not None else CIntegerWidths.native()
        self._signed_limits = MappingProxyType(
            {
                "signed char": self._signed_range(self.widths.char),
                "short": self._signed_range(self.widths.short),
                "int": self._signed_range(self.widths.int_),
                "long": self._signed_range(self.widths.long),
                "long long": self._signed_range(self.widths.long_long),
            }
        )
        self._unsigned_limits = MappingProxyType(
            {
                "unsigned char": self._unsigned_range(self.widths.char),
                "unsigned short": self._unsigned_range(self.widths.short),
                "unsigned int": self._unsigned_range(self.widths.int_),
                "unsigned long": self._unsigned_range(self.widths.long),
                "unsigned long long": self._unsigned_range(self.widths.long_long),
            }
        )

    def integer_type(self, raw: str, value: int) -> str:
        """Return the first C11 candidate type that can represent ``value``."""
        body, suffix = LiteralDecoder.integer_parts(raw)
        decimal = not (
            body.startswith(("0x", "0X", "0b", "0B", "0o", "0O")) or (len(body) > 1 and body.startswith("0"))
        )
        for candidate in self._integer_candidates(suffix, decimal):
            limits = self._type_limits(candidate)
            if limits is not None and limits[0] <= value <= limits[1]:
                return candidate
        raise ValueError(f"Integer literal '{raw}' is out of range for its C suffix")

    @staticmethod
    def float_type(raw: str) -> str:
        return "float" if raw.endswith(("f", "F")) else "double"

    def convert_integral(self, value: int | float, target_base: str) -> int | None:
        """Apply a defined C scalar-to-integer constant conversion."""
        if target_base == "bool":
            return int(value != 0)
        limits = self._type_limits(target_base)
        if limits is None:
            return None
        minimum, maximum = limits
        converted = math.trunc(value) if isinstance(value, float) else value
        if isinstance(value, float):
            return converted if minimum <= converted <= maximum else None
        if minimum == 0:
            return converted % (maximum + 1)
        return converted if minimum <= converted <= maximum else None

    @staticmethod
    def _signed_range(bits: int) -> tuple[int, int]:
        return (-(1 << bits - 1), (1 << bits - 1) - 1)

    @staticmethod
    def _unsigned_range(bits: int) -> tuple[int, int]:
        return (0, (1 << bits) - 1)

    @staticmethod
    def _integer_candidates(suffix: str, decimal: bool) -> tuple[str, ...]:
        if suffix == "":
            return (
                ("int", "long", "long long")
                if decimal
                else ("int", "unsigned int", "long", "unsigned long", "long long", "unsigned long long")
            )
        if suffix == "u":
            return ("unsigned int", "unsigned long", "unsigned long long")
        if suffix == "l":
            return ("long", "long long") if decimal else ("long", "unsigned long", "long long", "unsigned long long")
        if suffix in {"ul", "lu"}:
            return ("unsigned long", "unsigned long long")
        if suffix == "ll":
            return ("long long",) if decimal else ("long long", "unsigned long long")
        if suffix in {"ull", "llu"}:
            return ("unsigned long long",)
        raise ValueError(f"invalid integer suffix '{suffix}'")

    def _type_limits(self, base: str) -> tuple[int, int] | None:
        base = self._SIGNED_ALIASES.get(base, self._UNSIGNED_ALIASES.get(base, base))
        if base == "char":
            return None
        if base in self._signed_limits:
            return self._signed_limits[base]
        if base in self._unsigned_limits:
            return self._unsigned_limits[base]
        if base.startswith(("int", "uint")) and base.endswith("_t"):
            unsigned = base.startswith("uint")
            digits = "".join(character for character in base if character.isdigit())
            if digits and "least" not in base and ("fast" not in base):
                bits = int(digits)
                return self._unsigned_range(bits) if unsigned else self._signed_range(bits)
        return None


class OperatorTypeError(ValueError):
    """A typed operator has no portable meaning for its concrete operands."""


class OperatorSemantics:
    """Own portable operator domains for one compiler composition."""

    def __init__(
        self,
        type_identity: TypeIdentity,
        *,
        class_table: Mapping[str, object] | None = None,
        interface_table: Mapping[str, object] | None = None,
        enum_names: Set[str] | Mapping[str, object] | None = None,
    ) -> None:
        self.type_identity = type_identity
        self.class_table = class_table if class_table is not None else {}
        self.interface_table = interface_table if interface_table is not None else {}
        self.enum_names = enum_names if enum_names is not None else frozenset()

    def comparison_domain(self, operator: str, left: TypeExpr | None, right: TypeExpr | None) -> str:
        """Return ``string``, ``numeric``, or ``reference`` after validation."""
        if operator not in COMPARISON_OPERATORS:
            raise OperatorTypeError(f"unsupported comparison operator '{operator}'")
        if left is None or right is None:
            raise OperatorTypeError(f"cannot resolve operand types for operator '{operator}'")
        identity = self.type_identity
        left_string = identity.is_scalar_string(left)
        right_string = identity.is_scalar_string(right)
        if left_string or right_string:
            if (left_string or identity.is_c_string_pointer(left) or identity.is_null(left)) and (
                right_string or identity.is_c_string_pointer(right) or identity.is_null(right)
            ):
                return "string"
            raise OperatorTypeError(
                f"cannot compare string and non-string operands ('{self.type_label(left)}' and '{self.type_label(right)}')"
            )
        if TypeSystem.is_numeric_type(left, self.enum_names) and TypeSystem.is_numeric_type(right, self.enum_names):
            return "numeric"
        left_reference = identity.is_reference(left, self.class_table, self.interface_table)
        right_reference = identity.is_reference(right, self.class_table, self.interface_table)
        if left_reference or right_reference:
            if operator not in EQUALITY_OPERATORS:
                raise OperatorTypeError(
                    f"operator '{operator}' is not defined for reference operands; only == and != are portable"
                )
            if identity.references_compatible(left, right, self.class_table, self.interface_table):
                return "reference"
            if (left.generic_args or right.generic_args) and identity.nominally_related(
                left.base, right.base, self.class_table, self.interface_table
            ):
                raise OperatorTypeError(
                    "cannot compare generic inheritance references with mismatched positional specialization arguments or arities"
                )
            raise OperatorTypeError(
                f"cannot compare incompatible reference operands ('{self.type_label(left)}' and '{self.type_label(right)}')"
            )
        raise OperatorTypeError(
            f"operator '{operator}' is not defined for aggregate operands '{self.type_label(left)}' and '{self.type_label(right)}'"
        )

    def hash_domain(self, operand: TypeExpr | None) -> str:
        """Return the runtime hashing domain for one concrete operand."""
        if operand is None:
            raise OperatorTypeError("cannot resolve operand type for __btrc_hash")
        if self.type_identity.is_scalar_string(operand):
            return "string"
        if TypeSystem.is_floating_type(operand):
            return "floating"
        if TypeSystem.is_numeric_type(operand, self.enum_names):
            return "integral"
        if operand.base == "__fn_ptr":
            raise OperatorTypeError("__btrc_hash does not support function-pointer operands portably")
        if self.type_identity.is_reference(operand, self.class_table, self.interface_table):
            return "reference"
        raise OperatorTypeError(f"__btrc_hash is not defined for aggregate operand '{self.type_label(operand)}'")

    def coalesce_domain(
        self, left: TypeExpr | None, right: TypeExpr | None, *, left_is_optional_value: bool = False
    ) -> str:
        """Validate ``??`` and identify reference or optional-value lowering."""
        if left is None or right is None:
            raise OperatorTypeError("cannot resolve null-coalescing operand types")
        identity = self.type_identity
        if left_is_optional_value and (not identity.is_reference(left, self.class_table, self.interface_table)):
            if TypeSystem.is_numeric_type(left, self.enum_names) and TypeSystem.is_numeric_type(right, self.enum_names):
                return "optional_value"
            raise OperatorTypeError(
                f"null-coalescing optional value and fallback are incompatible: '{self.type_label(left)}' and '{self.type_label(right)}'"
            )
        if identity.is_scalar_string(left):
            compatible = (
                identity.is_scalar_string(right) or identity.is_c_string_pointer(right) or identity.is_null(right)
            )
        else:
            compatible = identity.references_compatible(left, right, self.class_table, self.interface_table)
        if compatible:
            return "reference"
        raise OperatorTypeError(
            f"left operand of '??' must be a reference or optional-chain value; got '{self.type_label(left)}' and '{self.type_label(right)}'"
        )

    def type_label(self, type_expr: TypeExpr) -> str:
        """Format a recursive source type for operator diagnostics."""
        label = type_expr.base
        if type_expr.generic_args:
            arguments = ", ".join(self.type_label(item) for item in type_expr.generic_args)
            label += f"<{arguments}>"
        label += "[]" if type_expr.is_array else ""
        label += "*" * type_expr.pointer_depth
        return label


@dataclass(frozen=True)
class StringMethod:
    return_type: str
    helper: str | None = None
    tracked: bool = False
    argument_types: tuple[str, ...] = ()


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
        self, *, reserved_prefix: str = "ZQ", forbidden_generic_flags: Iterable[tuple[str, str]] | None = None
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
            tuple(self.shape_key(argument) for argument in type_expr.generic_args or []),
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
        return (base, tuple(self.shape_key(argument) for argument in arguments))

    def references_names(self, type_expr: TypeExpr, names: Iterable[str]) -> bool:
        """Return whether a recursive type shape still names a parameter."""
        parameter_names = frozenset(names)
        return self._references_names(type_expr, parameter_names)

    def generic_argument_problem(self, type_expr: TypeExpr) -> tuple[str, TypeExpr] | None:
        """Return the first unsupported generic-argument modifier."""
        for attribute, spelling in self._forbidden_generic_flags:
            if getattr(type_expr, attribute, False):
                return (f"generic arguments cannot be {spelling}-qualified", type_expr)
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
        if type_expr.base in substitutions and (not type_expr.generic_args):
            resolved = substitutions[type_expr.base]
            reference_shape = reference_resolver(resolved) if reference_resolver else resolved
            reference_shape = reference_shape or resolved
            if type_expr.is_array and reference_shape.is_array:
                raise TypeShapeError(
                    f"nested array composition for type parameter '{type_expr.base}' is not supported", type_expr
                )
            return TypeSystem.compose_type_expr(type_expr, resolved, reference_shape=reference_shape)
        if type_expr.generic_args:
            return replace(
                type_expr,
                generic_args=[
                    self.substitute(argument, substitutions, reference_resolver=reference_resolver)
                    for argument in type_expr.generic_args
                ],
            )
        return type_expr

    def is_scalar_string(self, type_expr: TypeExpr | None) -> bool:
        """True only for a string represented by one collapsed ``char*``."""
        if type_expr is None or type_expr.base != "string" or type_expr.generic_args or type_expr.is_array:
            return False
        depth = type_expr.pointer_depth
        if TypeSystem.nullable_collapses_reference_layer(type_expr, base_is_reference=True):
            depth -= 1
        return depth == 0

    def is_scalar_void(self, type_expr: TypeExpr | None) -> bool:
        """True only for scalar ``void``, never ``void*``."""
        return bool(
            type_expr
            and type_expr.base == "void"
            and (type_expr.pointer_depth == 0)
            and (not type_expr.is_array)
            and (not type_expr.generic_args)
        )

    def is_null(self, type_expr: TypeExpr | None) -> bool:
        """Whether a type is the nullable null-literal domain."""
        return bool(
            type_expr and type_expr.base in {"null", "void"} and (type_expr.pointer_depth > 0) and type_expr.is_nullable
        )

    def is_c_string_pointer(self, type_expr: TypeExpr | None) -> bool:
        """Whether a C interop type is exactly one ``char`` pointer/array."""
        return bool(
            type_expr
            and type_expr.base == "char"
            and (type_expr.pointer_depth + int(type_expr.is_array) == 1)
            and (not type_expr.generic_args)
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
            or (type_expr.base in interfaces)
            or (type_expr.base in {"Thread", "Mutex", "__fn_ptr"})
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
        return self._specialization_is_subtype(left, right, classes, interfaces) or self._specialization_is_subtype(
            right, left, classes, interfaces
        )

    def specialization_is_subtype(
        self,
        child: TypeExpr,
        parent: TypeExpr,
        class_table: Mapping[str, object],
        interface_table: Mapping[str, object],
    ) -> bool:
        """Whether one concrete class/interface specialization derives from another."""
        return self._specialization_is_subtype(child, parent, class_table, interface_table)

    def nominally_related(
        self, left: str, right: str, class_table: Mapping[str, object], interface_table: Mapping[str, object]
    ) -> bool:
        """Whether either nominal type is an ancestor of the other."""
        return self._is_nominal_subtype(left, right, class_table, interface_table) or self._is_nominal_subtype(
            right, left, class_table, interface_table
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
            and (class_legacy is not None)
            and (method_legacy is not None)
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
        collapse = TypeSystem.nullable_collapses_reference_layer(type_expr, base_is_reference=intrinsic_base)
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
            ancestors = (getattr(info, "parent", None), *(getattr(info, "interfaces", ()) or ()))
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
        self, child: str, parent: str, class_table: Mapping[str, object], interface_table: Mapping[str, object]
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
        return self._is_ascii_identifier(base) and (not base.startswith(self._reserved_prefix))

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
            or any((getattr(type_expr, flag, False) for flag, _spelling in self._forbidden_generic_flags))
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
            (
                1 << index if getattr(type_expr, attribute, False) else 0
                for index, (attribute, _spelling) in enumerate(self._forbidden_generic_flags)
            )
        )
        shape = f"p{type_expr.pointer_depth}n{int(type_expr.is_nullable)}o{type_expr.nullable_outer_depth}a{int(type_expr.is_array)}q{qualifiers}"
        return self._field("b", base) + shape + self._encode_types(type_expr.generic_args or [])

    def _encode_types(self, arguments: Iterable[TypeExpr]) -> str:
        encoded = [self._encode_type(argument) for argument in arguments]
        return f"k{len(encoded)}" + "".join(self._field("t", item) for item in encoded)

    def _encode_name_and_types(self, base: str, arguments: Iterable[TypeExpr]) -> str:
        return self._field("b", base.encode("utf-8").hex()) + self._encode_types(arguments)


C_SCALAR_CALL_RESULTS = {
    "S_ISDIR": "bool",
    "S_ISLNK": "bool",
    "S_ISREG": "bool",
    "WEXITSTATUS": "int",
    "WIFEXITED": "bool",
    "WIFSIGNALED": "bool",
    "WTERMSIG": "int",
}
C_POINTER_CALL_RESULTS = {}
_C_PREDEFINED_STRING_IDENTIFIERS = frozenset({"__DATE__", "__FILE__", "__TIME__"})
_C_PREDEFINED_INT_IDENTIFIERS = frozenset({"__LINE__", "__STDC__", "__STDC_HOSTED__"})
_PRIMITIVE_TYPE_NAMES = frozenset(
    ("void", "bool", "byte", "char", "short", "int", "long", "float", "double", "string", "uint", "unsigned", "signed")
)
_BUILTIN_CAST_BASES = frozenset(("Vector", "List", "Map", "Set", "Array", "Thread", "Mutex", "Tuple"))
_RUNTIME_AGGREGATE_BASES = frozenset(("Vector", "List", "Map", "Set", "Array", "Tuple"))
_RUNTIME_TYPE_BASES = frozenset({"Array", "List", "Map", "Mutex", "Set", "Thread", "Tuple", "Vector", "__fn_ptr"})
_EXPLICIT_C_TAG_PREFIXES = ("struct ", "enum ", "union ")
_FLOATING_BASES = frozenset(("float", "double", "long double"))
_INTEGRAL_KINDS = {
    "bool": (3, False),
    "byte": (3, False),
    "char": (3, False),
    "signed char": (3, False),
    "unsigned char": (3, False),
    "short": (3, False),
    "short int": (3, False),
    "signed short": (3, False),
    "signed short int": (3, False),
    "unsigned short": (3, False),
    "unsigned short int": (3, False),
    "int": (3, False),
    "signed": (3, False),
    "signed int": (3, False),
    "uint": (3, True),
    "unsigned": (3, True),
    "unsigned int": (3, True),
    "long": (4, False),
    "long int": (4, False),
    "signed long": (4, False),
    "signed long int": (4, False),
    "unsigned long": (4, True),
    "unsigned long int": (4, True),
    "long long": (5, False),
    "long long int": (5, False),
    "signed long long": (5, False),
    "signed long long int": (5, False),
    "unsigned long long": (5, True),
    "unsigned long long int": (5, True),
}
_STANDARD_INTEGER_TYPEDEFS = frozenset(
    (
        "int8_t",
        "uint8_t",
        "int16_t",
        "uint16_t",
        "int32_t",
        "uint32_t",
        "int64_t",
        "uint64_t",
        "int_least8_t",
        "uint_least8_t",
        "int_least16_t",
        "uint_least16_t",
        "int_least32_t",
        "uint_least32_t",
        "int_least64_t",
        "uint_least64_t",
        "int_fast8_t",
        "uint_fast8_t",
        "int_fast16_t",
        "uint_fast16_t",
        "int_fast32_t",
        "uint_fast32_t",
        "int_fast64_t",
        "uint_fast64_t",
        "intptr_t",
        "uintptr_t",
        "intmax_t",
        "uintmax_t",
        "ptrdiff_t",
        "size_t",
        "wchar_t",
        "wint_t",
        "sig_atomic_t",
        "ssize_t",
        "pid_t",
        "uid_t",
        "gid_t",
        "off_t",
        "mode_t",
        "dev_t",
        "ino_t",
        "nlink_t",
        "blksize_t",
        "blkcnt_t",
        "time_t",
        "clock_t",
        "suseconds_t",
        "useconds_t",
        "socklen_t",
        "tcflag_t",
    )
)
_PORTABLE_WIDTH_TYPEDEFS = frozenset(
    {
        "int8_t",
        "uint8_t",
        "int16_t",
        "uint16_t",
        "int32_t",
        "uint32_t",
        "int64_t",
        "uint64_t",
        "int_least8_t",
        "uint_least8_t",
        "int_least16_t",
        "uint_least16_t",
        "int_least32_t",
        "uint_least32_t",
        "int_least64_t",
        "uint_least64_t",
    }
)
_ABI_DEPENDENT_INTEGER_TYPEDEFS = _STANDARD_INTEGER_TYPEDEFS - _PORTABLE_WIDTH_TYPEDEFS
_UNSIGNED_TYPEDEFS = frozenset(
    (
        "uint8_t",
        "uint16_t",
        "uint32_t",
        "uint64_t",
        "uint_least8_t",
        "uint_least16_t",
        "uint_least32_t",
        "uint_least64_t",
        "uint_fast8_t",
        "uint_fast16_t",
        "uint_fast32_t",
        "uint_fast64_t",
        "uintptr_t",
        "uintmax_t",
        "size_t",
        "uid_t",
        "gid_t",
        "mode_t",
        "dev_t",
        "ino_t",
        "nlink_t",
        "useconds_t",
        "socklen_t",
        "tcflag_t",
    )
)
_RESULT_BASE = {
    (3, False): "int",
    (3, True): "uint",
    (4, False): "long",
    (4, True): "unsigned long",
    (5, False): "long long",
    (5, True): "unsigned long long",
}
COMPARISON_OPERATORS = frozenset(("==", "!=", "<", ">", "<=", ">="))
EQUALITY_OPERATORS = frozenset(("==", "!="))
GENERIC_COMPARISON_INTRINSICS = {"__btrc_eq": "==", "__btrc_lt": "<", "__btrc_gt": ">"}
GENERIC_INTRINSICS = frozenset((*GENERIC_COMPARISON_INTRINSICS, "__btrc_hash"))
STRING_METHODS: dict[str, StringMethod] = {
    "len": StringMethod("int"),
    "byteLen": StringMethod("int"),
    "length": StringMethod("int"),
    "charLen": StringMethod("int", "__btrc_charLen"),
    "equals": StringMethod("bool", argument_types=("string",)),
    "contains": StringMethod("bool", "__btrc_strContains", argument_types=("string",)),
    "startsWith": StringMethod("bool", "__btrc_startsWith", argument_types=("string",)),
    "endsWith": StringMethod("bool", "__btrc_endsWith", argument_types=("string",)),
    "indexOf": StringMethod("int", "__btrc_indexOf", argument_types=("string",)),
    "lastIndexOf": StringMethod("int", "__btrc_lastIndexOf", argument_types=("string",)),
    "find": StringMethod("int", "__btrc_find", argument_types=("string", "int")),
    "count": StringMethod("int", "__btrc_count", argument_types=("string",)),
    "charAt": StringMethod("char", "__btrc_charAt", argument_types=("int",)),
    "isEmpty": StringMethod("bool", "__btrc_isEmpty"),
    "isBlank": StringMethod("bool", "__btrc_isBlank"),
    "isUpper": StringMethod("bool", "__btrc_isUpper"),
    "isLower": StringMethod("bool", "__btrc_isLower"),
    "isAlnum": StringMethod("bool", "__btrc_isAlnumStr"),
    "isAlnumStr": StringMethod("bool", "__btrc_isAlnumStr"),
    "isDigit": StringMethod("bool", "__btrc_isDigitStr"),
    "isDigitStr": StringMethod("bool", "__btrc_isDigitStr"),
    "isAlpha": StringMethod("bool", "__btrc_isAlphaStr"),
    "isAlphaStr": StringMethod("bool", "__btrc_isAlphaStr"),
    "trim": StringMethod("string", "__btrc_trim", tracked=True),
    "lstrip": StringMethod("string", "__btrc_lstrip", tracked=True),
    "rstrip": StringMethod("string", "__btrc_rstrip", tracked=True),
    "toUpper": StringMethod("string", "__btrc_toUpper", tracked=True),
    "toLower": StringMethod("string", "__btrc_toLower", tracked=True),
    "substring": StringMethod("string", "__btrc_substring", tracked=True, argument_types=("int", "int")),
    "replace": StringMethod("string", "__btrc_replace", tracked=True, argument_types=("string", "string")),
    "repeat": StringMethod("string", "__btrc_repeat", tracked=True, argument_types=("int",)),
    "reverse": StringMethod("string", "__btrc_reverse", tracked=True),
    "capitalize": StringMethod("string", "__btrc_capitalize", tracked=True),
    "title": StringMethod("string", "__btrc_title", tracked=True),
    "swapCase": StringMethod("string", "__btrc_swapCase", tracked=True),
    "padLeft": StringMethod("string", "__btrc_padLeft", tracked=True, argument_types=("int", "char")),
    "padRight": StringMethod("string", "__btrc_padRight", tracked=True, argument_types=("int", "char")),
    "center": StringMethod("string", "__btrc_center", tracked=True, argument_types=("int", "char")),
    "zfill": StringMethod("string", "__btrc_zfill", tracked=True, argument_types=("int",)),
    "removePrefix": StringMethod("string", "__btrc_removePrefix", tracked=True, argument_types=("string",)),
    "removeSuffix": StringMethod("string", "__btrc_removeSuffix", tracked=True, argument_types=("string",)),
    "split": StringMethod("string*", "__btrc_split", argument_types=("string",)),
    "toInt": StringMethod("int"),
    "toFloat": StringMethod("float"),
    "toDouble": StringMethod("double"),
    "toLong": StringMethod("long"),
    "toBool": StringMethod("bool"),
}
STRING_CONVERSIONS: dict[str, tuple[str, str | None]] = {
    "toInt": ("__btrc_parseInt", None),
    "toFloat": ("strtof", None),
    "toDouble": ("strtod", None),
    "toLong": ("__btrc_parseLong", None),
    "toBool": ("__btrc_parseBool", None),
}
_INTRINSIC_REFERENCE_BASES = frozenset(
    {"Array", "List", "Map", "Mutex", "Set", "Thread", "Vector", "__fn_ptr", "string"}
)


class TypeSystem:
    """Canonical semantic types, inference, conversions, and operators."""

    def __init__(
        self,
        session: AnalysisSession,
        index: DeclarationIndex,
        *,
        numeric_literals: NumericLiteralSemantics | None = None,
        type_identity: TypeIdentity | None = None,
    ) -> None:
        self.session = session
        self.index = index
        self._numeric_literals = numeric_literals if numeric_literals is not None else NumericLiteralSemantics()
        self._type_identity = type_identity if type_identity is not None else TypeIdentity()
        self._operator_types = OperatorSemantics(
            self._type_identity,
            class_table=index.class_table,
            interface_table=index.interface_table,
            enum_names=index.enum_table,
        )
        self._index_protocols = IndexedProtocolResolver(self._type_identity, index.class_table)

    def function_pointer_signature(self, type_expr):
        """Return the canonical callable shape: return type followed by parameters."""
        canonical = self.canonical_type(type_expr)
        if (
            canonical is None
            or canonical.base != "__fn_ptr"
            or canonical.pointer_depth != 0
            or canonical.is_array
            or (not canonical.generic_args)
        ):
            return None
        return canonical.generic_args

    @staticmethod
    def function_value_type(declaration) -> TypeExpr:
        """Represent a function value without declaration storage flags."""
        return TypeExpr(
            base="__fn_ptr",
            generic_args=[
                TypeSystem.function_signature_component(declaration.return_type),
                *(TypeSystem.function_signature_component(parameter.type) for parameter in declaration.params),
            ],
        )

    @staticmethod
    def function_signature_component(type_expr: TypeExpr) -> TypeExpr:
        return replace(type_expr, is_extern=False, is_static=False)

    def current_self_type(self) -> TypeExpr | None:
        """Return the specialized receiver type for the active class body."""
        current = self.session.current_class
        if current is None:
            return None
        generic_args = [TypeExpr(base=name) for name in current.generic_params]
        return TypeExpr(base=current.name, generic_args=generic_args, pointer_depth=1)

    def type_shape_key(self, type_expr: TypeExpr) -> tuple:
        """Return the canonical structural identity for a semantic type."""
        return self._type_identity.shape_key(type_expr)

    def generic_instance_key(self, base: str, arguments: Iterable[TypeExpr]) -> tuple:
        """Return the canonical identity of one generic specialization."""
        return self._type_identity.generic_instance_key(base, arguments)

    def type_references_names(self, type_expr: TypeExpr, names: Iterable[str]) -> bool:
        """Whether a recursive type shape still references any given names."""
        return self._type_identity.references_names(type_expr, names)

    def generic_argument_problem(self, type_expr: TypeExpr) -> tuple[str, TypeExpr] | None:
        """Return the first unsupported generic-argument modifier."""
        return self._type_identity.generic_argument_problem(type_expr)

    def is_scalar_string_value(self, type_expr: TypeExpr | None) -> bool:
        """Whether a type is exactly one language string value."""
        return self._type_identity.is_scalar_string(self.canonical_type(type_expr))

    def generic_symbol(self, base: str, arguments: Iterable[TypeExpr]) -> str:
        """Spell the generated C symbol for a parameterized type."""
        return self._type_identity.generic_symbol(base, arguments)

    def method_instance_symbol(
        self,
        class_base: str,
        class_arguments: Iterable[TypeExpr],
        method_name: str,
        method_arguments: Iterable[TypeExpr],
    ) -> str:
        """Spell one concrete generic-method C symbol."""
        return self._type_identity.method_instance_symbol(class_base, class_arguments, method_name, method_arguments)

    def resolve_index_protocol(self, type_expr, *, active_type_params=None) -> IndexedProtocol | None:
        """Resolve a type's indexed-access protocol."""
        return self._index_protocols.resolve(type_expr, active_type_params=active_type_params)

    def has_index_protocol(self, type_expr, *, method: str | None = None, active_type_params=None) -> bool:
        """Whether a type declares an indexed-access protocol of the requested shape."""
        return (
            self._index_protocols.class_info(type_expr, method=method, active_type_params=active_type_params)
            is not None
        )

    def float_literal_type(self, raw: str) -> TypeExpr:
        """Decode a floating literal suffix into its semantic type."""
        return TypeExpr(base=self._numeric_literals.float_type(raw))

    def convert_integral_literal(self, value: int | float, target_base: str) -> int | None:
        """Convert an integral constant under the target type's portable bounds."""
        return self._numeric_literals.convert_integral(value, target_base)

    def comparison_domain(self, operator: str, left: TypeExpr | None, right: TypeExpr | None) -> str:
        """Validate and classify a comparison's operand domain."""
        return self._operator_types.comparison_domain(operator, left, right)

    def hash_domain(self, operand: TypeExpr | None) -> str:
        """Validate and classify one hash operand."""
        return self._operator_types.hash_domain(operand)

    def coalesce_domain(
        self, left: TypeExpr | None, right: TypeExpr | None, *, left_is_optional_value: bool = False
    ) -> str:
        """Validate and classify a null-coalescing expression."""
        return self._operator_types.coalesce_domain(left, right, left_is_optional_value=left_is_optional_value)

    @staticmethod
    def c_predefined_identifier_type(name: str) -> str | None:
        """Return the strict-C11 scalar type of a guaranteed predefined macro."""
        if name in _C_PREDEFINED_STRING_IDENTIFIERS:
            return "const char*"
        if name == "__STDC_VERSION__":
            return "long"
        if name in _C_PREDEFINED_INT_IDENTIFIERS:
            return "int"
        return None

    @staticmethod
    def c_integer_identifier(name: str) -> bool:
        """Whether an identifier is accepted by the C integer-constant seam."""
        return name == "errno" or (name.isupper() and name != "NULL")

    @staticmethod
    def c_opaque_value_identifier(name: str) -> bool:
        """Whether C, rather than btrc, determines an identifier's value type."""
        return name != "errno" and TypeSystem.c_integer_identifier(name)

    def validate_cast_target_name(self, expression) -> bool:
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
            base in self.index.class_table
            or base in self.index.interface_table
            or base in self.index.enum_table
            or (base in self.index.rich_enum_table)
            or (base in self.index.declared_type_names)
        ):
            return True
        if self.session.current_class and base in self.session.current_class.generic_params:
            return True
        if base.endswith("_t"):
            return True
        self.session.error(f"Unknown type '{base}' in cast", expression.line, expression.col)
        return False

    def is_void_value(self, type_expr) -> bool:
        return self._type_identity.is_scalar_void(type_expr)

    def requires_string_conversion(self, target, source) -> bool:
        """Whether assignment compatibility implies a runtime toString call."""
        target = self.canonical_type(target)
        source = self.canonical_type(source)
        return self.requires_class_to_string(target, source)

    @staticmethod
    def is_empty_contextual_literal(expression) -> bool:
        return (
            (isinstance(expression, BraceInitializer) and (not expression.elements))
            or (isinstance(expression, ListLiteral) and (not expression.elements))
            or (isinstance(expression, MapLiteral) and (not expression.entries))
        )

    def element_type(self, iter_type, line, col):
        """Get the element type for for-in iteration."""
        if iter_type is None:
            return None
        if iter_type.base == "string" or (iter_type.base == "char" and iter_type.pointer_depth >= 1):
            return TypeExpr(base="char")
        if iter_type.is_array:
            return self.strip_outer_storage(iter_type, array=True)
        if iter_type.base in {"Array", "List", "Set", "Vector"} and len(iter_type.generic_args) == 1:
            return iter_type.generic_args[0]
        if iter_type.base == "Map" and len(iter_type.generic_args) == 2:
            return iter_type.generic_args[0]
        if iter_type.base in self.index.class_table:
            cls = self.index.class_table[iter_type.base]
            if "iterGet" in cls.methods:
                result = cls.methods["iterGet"].return_type
                if cls.generic_params and iter_type.generic_args:
                    substitutions = dict(zip(cls.generic_params, iter_type.generic_args))
                    return self.substitute_type(result, substitutions)
                return result
            self.session.error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None
        if iter_type.base in ("int", "float", "double", "bool"):
            self.session.error(f"Type '{iter_type.base}' is not iterable", line, col)
            return None
        return None

    def iterable_value_type(self, iter_type, line, col):
        """Resolve the second binding type for key/value iteration."""
        if iter_type is None:
            return None
        if iter_type.base == "Map" and len(iter_type.generic_args) == 2:
            return iter_type.generic_args[1]
        cls = self.index.class_table.get(iter_type.base)
        method = cls.methods.get("iterValueAt") if cls else None
        if method is None:
            self.session.error(f"Type '{iter_type.base}' does not support key/value iteration", line, col)
            return None
        result = method.return_type
        if cls.generic_params and iter_type.generic_args:
            substitutions = dict(zip(cls.generic_params, iter_type.generic_args))
            result = self.substitute_type(result, substitutions)
        return result

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

    def operator_method(self, receiver_type, operator, *, unary=False):
        """Return an overload and its class substitutions, if one exists."""
        receiver_type = self.canonical_type(receiver_type)
        if receiver_type is None:
            return None
        cls = self.index.class_table.get(receiver_type.base)
        names = self._UNARY_OVERLOADS if unary else self._BINARY_OVERLOADS
        method = cls.methods.get(names.get(operator, "")) if cls else None
        if method is None:
            return None
        substitutions = {}
        if cls.generic_params and len(receiver_type.generic_args) == len(cls.generic_params):
            substitutions.update(zip(cls.generic_params, receiver_type.generic_args))
        return (method, substitutions)

    def operator_return_type(self, receiver_type, operator, *, unary=False):
        resolved = self.operator_method(receiver_type, operator, unary=unary)
        if resolved is None:
            return None
        method, substitutions = resolved
        if substitutions:
            return self.substitute_type(method.return_type, substitutions)
        return method.return_type

    def infer_integer_literal_type(self, raw: str, value: int) -> TypeExpr:
        return TypeExpr(base=self._numeric_literals.integer_type(raw, value))

    def collection_literal_type(self, base, generic_args):
        return TypeExpr(base=base, generic_args=generic_args, pointer_depth=1 if base in self.index.class_table else 0)

    def _contains_mutex_storage(self, type_expr, visiting=frozenset()) -> bool:
        canonical = self.canonical_type(type_expr)
        if canonical is None:
            return False
        if canonical.base == "Mutex":
            return True
        arguments = canonical.generic_args or []
        if canonical.base == "__fn_ptr":
            arguments = arguments[1:]
        if any(self._contains_mutex_storage(argument, visiting) for argument in arguments):
            return True
        if canonical.pointer_depth > 0:
            return False
        return any(
            self._contains_mutex_storage(field, nested)
            for field, nested in self._aggregate_field_types(canonical, visiting)
        )

    def thread_result_contains_unsized_array(self, type_expr, visiting=frozenset()) -> bool:
        canonical = self.canonical_type(type_expr)
        if canonical is None:
            return False
        if canonical.is_array:
            if canonical.array_size is None:
                return True
            canonical = self.strip_outer_storage(canonical, array=True)
        if canonical.pointer_depth > 0:
            return False
        if canonical.base == "Tuple":
            return any(
                self.thread_result_contains_unsized_array(argument, visiting) for argument in canonical.generic_args
            )
        return any(
            self.thread_result_contains_unsized_array(field, nested)
            for field, nested in self._aggregate_field_types(canonical, visiting)
        )

    def is_direct_managed_thread_result(self, type_expr) -> bool:
        canonical = self.canonical_type(type_expr)
        if canonical is None or canonical.is_array:
            return False
        scalar_string = self._type_identity.is_scalar_string(canonical)
        class_reference = canonical.base in self.index.class_table and canonical.pointer_depth <= 1
        return scalar_string or class_reference

    def thread_result_aggregate_contains_managed_reference(self, type_expr, visiting=frozenset()) -> bool:
        canonical = self.canonical_type(type_expr)
        if canonical is None:
            return False
        if canonical.is_array:
            return self.thread_result_aggregate_contains_managed_reference(
                self.strip_outer_storage(canonical, array=True), visiting
            )
        if self.is_direct_managed_thread_result(canonical):
            return True
        if canonical.pointer_depth > 0:
            return False
        if canonical.base == "Tuple":
            return any(
                self.thread_result_aggregate_contains_managed_reference(argument, visiting)
                for argument in canonical.generic_args
            )
        return any(
            self.thread_result_aggregate_contains_managed_reference(field, nested)
            for field, nested in self._aggregate_field_types(canonical, visiting)
        )

    def _aggregate_field_types(self, canonical, visiting):
        name = canonical.base.removeprefix("struct ")
        kind = "struct" if name in self.index.struct_table else "rich-enum"
        visit_key = f"{kind}:{name}"
        if visit_key in visiting:
            return ()
        nested_visiting = visiting | {visit_key}
        declaration = self.index.struct_table.get(name)
        if declaration and (not declaration.is_forward):
            return tuple((field.type, nested_visiting) for field in declaration.fields)
        rich_enum = self.index.rich_enum_table.get(name)
        if rich_enum:
            return tuple(
                (parameter.type, nested_visiting) for variant in rich_enum.variants for parameter in variant.params
            )
        return ()

    def validate_declared_type(
        self, type_expr, subject, line=0, col=0, *, role="object", active_type_params=()
    ) -> None:
        if type_expr is None:
            return
        type_line = type_expr.line or line
        type_col = type_expr.col or col
        self._validate_storage_qualifiers(type_expr, subject, role, type_line, type_col)
        if role == "return" and self._return_type_has_outer_cv_qualifier(type_expr):
            self.session.error(
                f"{subject} cannot carry an outer const/volatile qualifier; C discards qualifiers on returned values",
                type_line,
                type_col,
            )
        self._validate_generic_arity(type_expr, type_expr.base in set(active_type_params))
        if type_expr.is_array and type_expr.base in self.index.typedef_table:
            alias_target = self.canonical_type(self.index.typedef_table[type_expr.base])
            if alias_target is not None and alias_target.is_array:
                self.report_type_shape_error(
                    "Nested array composition through typedef is not supported", type_expr, type_line, type_col
                )
        if type_expr.base in self.index.interface_table and type_expr.base not in set(active_type_params):
            self.report_type_shape_error(
                f"Interface type '{type_expr.base}' cannot be used as a runtime value; use an implementing concrete class",
                type_expr,
                type_line,
                type_col,
            )
        canonical = self.canonical_type(type_expr)
        if (
            canonical
            and canonical.base == "Mutex"
            and (canonical.pointer_depth > 0 or canonical.is_array or canonical.is_const)
        ):
            self.session.error(
                "Mutex<T> owner type must be one direct mutable handle; pointer, array, and const Mutex shapes are not supported",
                type_line,
                type_col,
            )
        if (
            canonical
            and canonical.base not in {"Mutex", "Thread", "__fn_ptr"}
            and (canonical.base not in self.index.class_table)
            and self._contains_mutex_storage(canonical)
        ):
            self.session.error(
                f"{subject} cannot embed a Mutex handle in shallow by-value storage; keep Mutex<T> as a direct managed value",
                type_line,
                type_col,
            )
        if (
            canonical
            and canonical.base == "Thread"
            and (canonical.pointer_depth > 0 or canonical.is_array or canonical.is_const or canonical.is_nullable)
        ):
            self.session.error(
                "Thread<T> owner type must be one direct mutable handle; pointer, array, const, and nullable Thread shapes are not supported",
                type_line,
                type_col,
            )
        if role in {"field", "parameter"} and self.contains_thread_storage(type_expr):
            self.session.error(
                f"{subject} cannot own a Thread handle; keep each Thread<T> in one initialized local variable or return it",
                type_line,
                type_col,
            )
        if canonical and canonical.base == "Thread" and canonical.generic_args:
            result_type = canonical.generic_args[0]
            if self.thread_result_contains_unsized_array(result_type):
                self.session.error(
                    "Thread<T> result type cannot contain an unsized array; return a managed collection or another explicitly owned value",
                    type_line,
                    type_col,
                )
            if self.contains_thread_storage(result_type):
                self.session.error("Thread<T> result type cannot contain another Thread handle", type_line, type_col)
            if self._contains_mutex_storage(result_type):
                self.session.error("Thread<T> result type cannot contain a Mutex handle", type_line, type_col)
            if not self.is_direct_managed_thread_result(
                result_type
            ) and self.thread_result_aggregate_contains_managed_reference(result_type):
                self.session.error(
                    "Thread<T> aggregate result type cannot contain string or class references; return the managed value directly or use a scalar-only aggregate",
                    type_line,
                    type_col,
                )
        if role not in {"alias", "return"} and self.is_nonpointer_void_object(canonical):
            self.session.error(f"{subject} cannot have scalar/non-pointer void type", type_line, type_col)
        if not self._is_known_declaration_type(type_expr, active_type_params):
            self.session.error(
                f"{subject} uses unknown by-value type '{self.format_type(type_expr)}'", type_line, type_col
            )
        arguments = type_expr.generic_args or []
        for index, argument in enumerate(arguments):
            result_slot = type_expr.base in {"__fn_ptr", "Thread"} and index == 0
            argument_role = "return" if result_slot else "object"
            self.validate_declared_type(
                argument,
                f"Generic argument {index + 1} of {subject}",
                type_line,
                type_col,
                role=argument_role,
                active_type_params=active_type_params,
            )

    def _validate_generic_arity(self, type_expr, is_active_type_parameter=False) -> None:
        if type_expr is None:
            return
        expected = None
        if type_expr.base in self.index.class_table:
            expected = len(self.index.class_table[type_expr.base].generic_params)
        elif type_expr.base in self.index.interface_table:
            expected = len(self.index.interface_table[type_expr.base].generic_params)
        elif type_expr.base in {"Array", "List", "Mutex", "Set", "Thread", "Vector"}:
            expected = 1
        elif type_expr.base == "Map":
            expected = 2
        elif type_expr.base == "__fn_ptr":
            expected = None
        if expected is not None and (not is_active_type_parameter) and len(type_expr.generic_args or []) != expected:
            self.report_type_shape_error(
                f"Type '{type_expr.base}' expects {expected} generic argument(s) but got {len(type_expr.generic_args or [])}",
                type_expr,
                type_expr.line,
                type_expr.col,
            )

    def report_type_shape_error(self, message, type_expr, line=0, col=0) -> None:
        error_line = getattr(type_expr, "line", 0) or line
        error_col = getattr(type_expr, "col", 0) or col
        marker = (message, error_line, error_col)
        reported = self.session.reported_type_shape_errors
        if marker in reported:
            return
        reported.add(marker)
        self.session.error(message, error_line, error_col)

    def _return_type_has_outer_cv_qualifier(self, type_expr) -> bool:
        """Whether C would discard a qualifier on the returned value itself.

        Canonicalizing first is insufficient here: flattening a typedef keeps
        the qualifier bit but loses the declarator layer that says whether it
        belongs to the value or to a pointee.  Const and volatile also have
        intentionally different source semantics.  ``const T*`` qualifies
        ``T``, while an explicit ``volatile T*`` qualifies the pointer storage;
        typedef-inherited qualifiers remain below any pointer shell applied at
        the use site.
        """
        return self._declarator_has_outer_const(type_expr) or self._declarator_has_outer_volatile(type_expr)

    def _declarator_has_outer_const(self, type_expr, seen=frozenset()) -> bool:
        if type_expr is None:
            return False
        target = self._qualifier_typedef_target(type_expr, seen)
        applied_layers = self._qualifier_applied_storage_layers(type_expr, target)
        implicit_pointee = target is None and type_expr.base in {"Mutex", "Thread", "string"}
        if type_expr.is_const and (applied_layers + int(implicit_pointee) == 0):
            return True
        if target is None or applied_layers > 0:
            return False
        return self._declarator_has_outer_const(target, seen | {type_expr.base})

    def _declarator_has_outer_volatile(self, type_expr, seen=frozenset()) -> bool:
        if type_expr is None:
            return False
        if type_expr.is_volatile:
            return True
        target = self._qualifier_typedef_target(type_expr, seen)
        if target is None or self._qualifier_applied_pointer_layers(type_expr, target) > 0:
            return False
        return self._declarator_has_outer_volatile(target, seen | {type_expr.base})

    def _qualifier_typedef_target(self, type_expr, seen):
        if type_expr.generic_args or type_expr.base in seen:
            return None
        return self.index.typedef_table.get(type_expr.base)

    @staticmethod
    def _qualifier_applied_storage_layers(type_expr, target) -> int:
        return TypeSystem._qualifier_applied_pointer_layers(type_expr, target) + int(type_expr.is_array)

    @staticmethod
    def _qualifier_applied_pointer_layers(type_expr, target) -> int:
        reference_shape = TypeSystem.resolved_reference_shape(target) if target is not None else False
        return type_expr.pointer_depth - int(
            TypeSystem.nullable_collapses_reference_layer(type_expr, base_is_reference=reference_shape)
        )

    def _is_known_declaration_type(self, type_expr, active_type_params=()) -> bool:
        base = type_expr.base
        if type_expr.pointer_depth > 0 and (not type_expr.generic_args):
            return True
        if base in active_type_params:
            return True
        if base in self.NUMERIC_TYPES or base in {"bool", "string", "void"}:
            return True
        if base in _RUNTIME_TYPE_BASES:
            return True
        if base in self.index.class_table or base in self.index.interface_table:
            return True
        if base in self.index.enum_table or base in self.index.rich_enum_table:
            return True
        if base in self.index.struct_table or base in self.index.typedef_table:
            return True
        if base in self.index.declared_type_names:
            return True
        if base.endswith("_t") or self.is_known_integer_typedef_name(base):
            return True
        return base.startswith(_EXPLICIT_C_TAG_PREFIXES)

    def is_nonpointer_void_object(self, type_expr) -> bool:
        return self._type_identity.is_scalar_void(type_expr)

    def contains_thread_storage(self, type_expr) -> bool:
        """Whether a concrete value shape contains a uniquely owned handle."""
        canonical = self.canonical_type(type_expr)
        if canonical is None:
            return False
        if canonical.base == "Thread":
            return True
        arguments = canonical.generic_args or []
        if canonical.base == "__fn_ptr":
            arguments = arguments[1:]
        return any(self.contains_thread_storage(argument) for argument in arguments)

    def _validate_storage_qualifiers(self, type_expr, subject, role, line, col) -> None:
        if type_expr.is_static and type_expr.is_extern:
            self.session.error(f"{subject} cannot be both static and extern", line, col)
        if role in {"parameter", "field"} and (type_expr.is_static or type_expr.is_extern):
            self.session.error(f"{subject} cannot carry static/extern storage qualifiers", line, col)

    def upgrade_class_type(self, type_expr, shadowed_names=None):
        """Auto-upgrade class references without capturing type parameters.

        A lexical generic parameter shadows a top-level declaration with the
        same spelling. This matters in composed programs: a user ``class T``
        must not turn every stdlib ``Vector<T>`` template parameter into a
        pointer to that unrelated class.
        """
        if type_expr is None:
            return type_expr
        if shadowed_names is None:
            shadowed_names = set()
            if self.session.current_class is not None:
                shadowed_names.update(self.session.current_class.generic_params)
            if self.session.current_method is not None:
                shadowed_names.update(self.session.current_method.generic_params)
        else:
            shadowed_names = set(shadowed_names)
        auto_upgraded = getattr(type_expr, "auto_upgraded", False)
        upgraded_args = type_expr.generic_args
        if type_expr.generic_args:
            upgraded_args = [self.upgrade_class_type(argument, shadowed_names) for argument in type_expr.generic_args]
            if upgraded_args != type_expr.generic_args:
                type_expr = replace(type_expr, generic_args=upgraded_args)
        if type_expr.base not in self.index.class_table or type_expr.base in shadowed_names:
            return type_expr
        if type_expr.pointer_depth > 1:
            return replace(type_expr, generic_args=upgraded_args)
        if type_expr.pointer_depth == 1 and (not type_expr.is_nullable) and (not auto_upgraded):
            self.session.error(
                f"Redundant pointer for class type '{type_expr.base}' — classes are always heap-allocated. Use '{type_expr.base}' instead of '{type_expr.base}*'",
                type_expr.line,
                type_expr.col,
            )
        upgraded = replace(type_expr, generic_args=upgraded_args, pointer_depth=1)
        upgraded.auto_upgraded = True
        return upgraded

    def normalize_declarations(self, program):
        """Resolve class reference types on every declaration signature.

        Method bodies may legally precede the class whose fields they read.
        Type inference consults the registered declaration table, so those
        fields and signatures must already have the same normalized types that
        later monomorphization sees.  Normalizing opportunistically while each
        owning declaration was analyzed made code generation depend on import
        and declaration order: an early ``Vector<Item>`` field access mangled
        calls without ``Item``'s synthesized pointer suffix, while the field's
        eventual generic instance was emitted as ``Vector<Item*>``.

        The normal per-declaration analysis remains idempotent and still owns
        generic-instance collection and body validation; this pass establishes
        only the order-independent type context they consume.
        """
        for decl in self.session.declarations(program):
            if isinstance(decl, FunctionDecl):
                for param in decl.params:
                    param.type = self.upgrade_class_type(param.type)
                decl.return_type = self.upgrade_class_type(decl.return_type)
            elif isinstance(decl, ClassDecl):
                class_params = set(decl.generic_params)
                for member in decl.members:
                    if isinstance(member, (FieldDecl, PropertyDecl)):
                        member.type = self.upgrade_class_type(member.type, class_params)
                    elif isinstance(member, MethodDecl):
                        shadowed = class_params | set(member.generic_params)
                        for param in member.params:
                            param.type = self.upgrade_class_type(param.type, shadowed)
                        member.return_type = self.upgrade_class_type(member.return_type, shadowed)
            elif isinstance(decl, InterfaceDecl):
                interface_params = set(decl.generic_params)
                for method in decl.methods:
                    for param in method.params:
                        param.type = self.upgrade_class_type(param.type, interface_params)
                    method.return_type = self.upgrade_class_type(method.return_type, interface_params)
            elif isinstance(decl, TypedefDecl):
                decl.original = self.upgrade_class_type(decl.original)
                self.index.typedef_table[decl.alias] = decl.original
            elif isinstance(decl, StructDecl):
                for field in decl.fields:
                    field.type = self.upgrade_class_type(field.type)
            elif isinstance(decl, RichEnumDecl):
                for variant in decl.variants:
                    for parameter in variant.params:
                        parameter.type = self.upgrade_class_type(parameter.type)
            elif isinstance(decl, VarDeclStmt) and decl.type is not None:
                decl.type = self.upgrade_class_type(decl.type)
                symbol = self.session.global_scope.symbols.get(decl.name)
                if symbol is not None:
                    symbol.type = decl.type

    NUMERIC_TYPES = frozenset(
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

    _INTEGRAL_TYPES = frozenset(
        {
            "bool",
            "byte",
            "char",
            "short",
            "short int",
            "int",
            "long",
            "long int",
            "long long",
            "long long int",
            "signed",
            "unsigned",
            "unsigned char",
            "uint",
            "unsigned int",
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
        }
    )

    def is_numeric_value(self, type_expr) -> bool:
        """Whether a canonical value participates in numeric operators."""
        type_expr = self.canonical_type(type_expr)
        return (
            bool(
                type_expr
                and type_expr.base in self.NUMERIC_TYPES
                and (type_expr.pointer_depth == 0)
                and (not type_expr.is_array)
                and (not type_expr.generic_args)
            )
            or self.is_opaque_c_scalar(type_expr)
            or self.is_native_enum_scalar(type_expr)
        )

    def is_integral_value(self, type_expr) -> bool:
        """Whether a canonical value participates in integral operators."""
        type_expr = self.canonical_type(type_expr)
        return (
            bool(
                type_expr
                and type_expr.base in self._INTEGRAL_TYPES
                and (type_expr.pointer_depth == 0)
                and (not type_expr.is_array)
                and (not type_expr.generic_args)
            )
            or self.is_opaque_c_scalar(type_expr)
            or self.is_native_enum_scalar(type_expr)
        )

    def is_pointer_value(self, type_expr) -> bool:
        """Whether a value uses pointer-like source representation."""
        type_expr = self.canonical_type(type_expr)
        return bool(type_expr and (type_expr.pointer_depth > 0 or type_expr.is_array or type_expr.base == "string"))

    def string_method_return_type(self, method_name: str) -> TypeExpr | None:
        """Return the type of a string method call (shared spec table)."""
        spec = STRING_METHODS.get(method_name)
        if spec is None:
            return None
        if spec.return_type == "string*":
            return TypeExpr(base="string", pointer_depth=1)
        return TypeExpr(base=spec.return_type)

    def format_type(self, t) -> str:
        """Format a TypeExpr for error messages."""
        result = "const " if t.is_const else ""
        result += "CFunction" if t.base == "__fn_ptr" else t.base
        if t.generic_args:
            args = ", ".join(self.format_type(a) for a in t.generic_args)
            result += f"<{args}>"
        result += "*" * t.pointer_depth
        if t.is_array:
            result += "[]"
        return result

    def is_opaque_c_scalar(self, type_expr) -> bool:
        """Whether a type is an unresolved C/POSIX scalar typedef.

        Imported headers do not expose typedef definitions to the btrc parser,
        so only the shared, explicit C/POSIX integer registry is admitted.
        """
        return bool(
            type_expr
            and (self.is_known_integer_typedef_name(type_expr.base) or type_expr.base.startswith("enum "))
            and (type_expr.pointer_depth == 0)
            and (not type_expr.is_array)
            and (not type_expr.generic_args)
        )

    def is_native_enum_scalar(self, type_expr) -> bool:
        """Whether ``type_expr`` is an int-backed btrc enum value."""
        return bool(
            type_expr
            and type_expr.base in self.index.enum_table
            and (type_expr.pointer_depth == 0)
            and (not type_expr.is_array)
            and (not type_expr.generic_args)
        )

    def types_compatible(self, target, source) -> bool:
        """Check if source type can be assigned to target type."""
        if target is None or source is None:
            return False
        target = self.array_value_type(target)
        source = self.array_value_type(source)
        target = self.canonical_type(target)
        source = self.canonical_type(source)
        if source.base == "null" or (source.base == "void" and source.pointer_depth > 0):
            return target.pointer_depth > 0 or target.is_array or target.base == "string"
        if (
            target.base == source.base
            and self.is_active_type_parameter(target)
            and target.is_nullable
            and (target.pointer_depth == source.pointer_depth + 1)
        ):
            return self.generic_args_equal(target, source)
        if (
            source.is_array
            and (not target.is_array)
            and (target.base == source.base)
            and (target.pointer_depth == source.pointer_depth + 1)
        ):
            return self._const_conversion_allowed(target, source) and self.generic_args_equal(target, source)
        if target.base == source.base:
            if self.semantic_pointer_depth(target) != self.semantic_pointer_depth(source):
                return False
            if target.is_array != source.is_array:
                return False
            return self._const_conversion_allowed(target, source) and self.generic_args_equal(target, source)
        if (
            target.base in self.NUMERIC_TYPES
            and source.base in self.NUMERIC_TYPES
            and (target.pointer_depth == source.pointer_depth == 0)
            and (not target.is_array)
            and (not source.is_array)
            and (not target.generic_args)
            and (not source.generic_args)
        ):
            return True
        if (
            (self.is_opaque_c_scalar(target) and source.base in self.NUMERIC_TYPES)
            or (self.is_opaque_c_scalar(source) and target.base in self.NUMERIC_TYPES)
            or (self.is_opaque_c_scalar(target) and self.is_opaque_c_scalar(source))
        ):
            return True
        if (self.is_native_enum_scalar(target) and source.base in self.NUMERIC_TYPES) or (
            self.is_native_enum_scalar(source) and target.base in self.NUMERIC_TYPES
        ):
            return True
        if target.base == "string" and source.base == "char" and (source.pointer_depth >= 1 or source.is_array):
            return self._const_conversion_allowed(target, source)
        if source.base == "string" and target.base == "char" and (target.pointer_depth >= 1 or target.is_array):
            return self._const_conversion_allowed(target, source)
        if self.requires_class_to_string(target, source):
            return True
        if (
            target.base == "void"
            and target.pointer_depth == 1
            and (self.semantic_pointer_depth(source) > 0 or source.is_array)
        ):
            return self._const_conversion_allowed(target, source)
        if (
            source.base == "void"
            and source.pointer_depth == 1
            and (self.semantic_pointer_depth(target) > 0 or target.is_array)
        ):
            return self._const_conversion_allowed(target, source)
        if target.base in self.index.class_table and source.base in self.index.class_table:
            return self._reference_shapes_compatible(target, source) and self.is_subclass(source.base, target.base)
        if target.base in self.index.interface_table and source.base in self.index.class_table:
            return self._reference_shapes_compatible(target, source) and self.is_subclass(source.base, target.base)
        if target.base in self.index.interface_table and source.base in self.index.interface_table:
            return self._reference_shapes_compatible(target, source) and self._is_interface_subtype(
                source.base, target.base
            )
        return False

    def array_value_type(self, type_expr):
        canonical = self.canonical_type(type_expr)
        if type_expr is None or canonical is None or type_expr.is_array or (not canonical.is_array):
            return type_expr
        return self.add_outer_pointer(canonical, clear_array=True)

    def _reference_shapes_compatible(self, target, source) -> bool:
        return bool(
            self.semantic_pointer_depth(target) == self.semantic_pointer_depth(source)
            and target.is_array == source.is_array
            and self._const_conversion_allowed(target, source)
            and self.generic_args_equal(target, source)
        )

    def _const_conversion_allowed(self, target, source) -> bool:
        target_depth = self._qualifier_indirection_depth(target)
        source_depth = self._qualifier_indirection_depth(source)
        if target_depth == 0 or source_depth == 0:
            return True
        if source.is_const and (not target.is_const):
            return False
        if target_depth > 1 or source_depth > 1:
            return target.is_const == source.is_const
        return True

    def _qualifier_indirection_depth(self, type_expr) -> int:
        depth = self.semantic_pointer_depth(type_expr) + int(type_expr.is_array)
        if type_expr.base == "string" and depth == 0:
            return 1
        return depth

    def is_active_type_parameter(self, type_expr) -> bool:
        if type_expr is None or type_expr.generic_args:
            return False
        parameters = set(
            (self.session.current_class.generic_params if self.session.current_class else [])
            + (self.session.current_method.generic_params if self.session.current_method else [])
        )
        return type_expr.base in parameters

    def generic_args_equal(self, left, right) -> bool:
        left_args = left.generic_args or []
        right_args = right.generic_args or []
        return len(left_args) == len(right_args) and all(
            (self.types_equal(a, b) for a, b in zip(left_args, right_args))
        )

    def types_equal(self, left, right) -> bool:
        """Position-independent structural equality for signature types."""
        if left is None or right is None:
            return left is right
        left = self.canonical_type(left)
        right = self.canonical_type(right)
        if (
            left.base != right.base
            or self.semantic_pointer_depth(left) != self.semantic_pointer_depth(right)
            or left.is_array != right.is_array
            or (left.is_nullable != right.is_nullable)
            or (left.is_const != right.is_const)
            or (left.is_volatile != right.is_volatile)
        ):
            return False
        left_args = left.generic_args or []
        right_args = right.generic_args or []
        return len(left_args) == len(right_args) and all(
            (self.types_equal(a, b) for a, b in zip(left_args, right_args))
        )

    def semantic_pointer_depth(self, type_expr) -> int:
        """Pointer depth after intrinsic-reference nullable sugar collapses."""
        depth = type_expr.pointer_depth
        intrinsic_base = type_expr.base in {"string", "Thread", "Mutex", "__fn_ptr"}
        if self.nullable_collapses_reference_layer(type_expr, base_is_reference=intrinsic_base):
            depth -= 1
        if intrinsic_base:
            depth += 1
        elif type_expr.base in {"Vector", "List", "Map", "Set", "Array"} and type_expr.generic_args and (depth == 0):
            depth = 1
        return depth

    def canonical_type(self, type_expr, seen=None):
        """Resolve typedef aliases while preserving use-site modifiers."""
        return self.canonical_declaration_type(type_expr, self.index.typedef_table, seen)

    @staticmethod
    def canonical_declaration_type(type_expr, typedefs, seen=None):
        """Resolve declaration aliases while preserving use-site modifiers."""
        if type_expr is None or type_expr.base not in typedefs:
            return type_expr
        seen = set() if seen is None else seen
        if type_expr.base in seen:
            return type_expr
        seen.add(type_expr.base)
        resolved = TypeSystem.canonical_declaration_type(typedefs[type_expr.base], typedefs, seen)
        return TypeSystem.compose_type_expr(type_expr, resolved, reference_shape=resolved)

    def _is_interface_subtype(self, child: str, parent: str) -> bool:
        """Whether an interface is the same as or transitively extends another."""
        current = child
        visited: set[str] = set()
        while current and current not in visited:
            if current == parent:
                return True
            visited.add(current)
            info = self.index.interface_table.get(current)
            current = info.parent if info else None
        return False

    def is_subclass(self, child: str, parent: str) -> bool:
        """Check if child class extends parent (directly or transitively)."""
        if child == parent:
            return True
        info = self.index.class_table.get(child)
        if not info:
            return False
        if parent in self.index.interface_table:
            cur = info
            visited = set()
            while cur and cur.name not in visited:
                visited.add(cur.name)
                if any(self._is_interface_subtype(interface, parent) for interface in cur.interfaces):
                    return True
                cur = self.index.class_table.get(cur.parent) if cur.parent else None
            return False
        visited = set()
        while info and info.parent and (info.parent not in visited):
            visited.add(info.parent)
            if info.parent == parent:
                return True
            info = self.index.class_table.get(info.parent)
        return False

    def substitute_type(self, t: TypeExpr | None, subs: dict) -> TypeExpr | None:
        """Recursively substitute type parameters in a TypeExpr."""
        try:
            return self._type_identity.substitute(t, subs, reference_resolver=self.canonical_type)
        except TypeShapeError as error:
            self.report_type_shape_error(str(error), error.type_expr or t, getattr(t, "line", 0), getattr(t, "col", 0))
            return t

    @staticmethod
    def is_floating_type(type_expr: TypeExpr | None) -> bool:
        return bool(TypeSystem._is_scalar(type_expr) and type_expr.base in _FLOATING_BASES)

    @staticmethod
    def is_numeric_type(type_expr: TypeExpr | None, enum_names: Set[str] = frozenset()) -> bool:
        if not TypeSystem._is_scalar(type_expr):
            return False
        assert type_expr is not None
        return (
            type_expr.base in _INTEGRAL_KINDS
            or type_expr.base in _FLOATING_BASES
            or type_expr.base in _STANDARD_INTEGER_TYPEDEFS
            or (type_expr.base in enum_names)
            or type_expr.base.startswith("enum ")
        )

    @staticmethod
    def is_known_integer_typedef_name(name: str) -> bool:
        """Whether an undeclared C/POSIX typedef has a known integer contract."""
        return name in _STANDARD_INTEGER_TYPEDEFS

    @staticmethod
    def integer_mix_is_portable(left: TypeExpr | None, right: TypeExpr | None) -> bool:
        """Whether integer conversions have one result on every supported ABI."""
        if left is None or right is None:
            return True
        if TypeSystem.is_floating_type(left) or TypeSystem.is_floating_type(right):
            return True
        if left.base == right.base:
            return True
        return not (left.base in _ABI_DEPENDENT_INTEGER_TYPEDEFS or right.base in _ABI_DEPENDENT_INTEGER_TYPEDEFS)

    @staticmethod
    def numeric_result_type(
        left: TypeExpr | None, right: TypeExpr | None, enum_names: Set[str] = frozenset()
    ) -> TypeExpr | None:
        """Return an operand-order-independent btrc arithmetic result type."""
        if not (TypeSystem.is_numeric_type(left, enum_names) and TypeSystem.is_numeric_type(right, enum_names)):
            return None
        assert left is not None and right is not None
        floating = [base for base in (left.base, right.base) if base in _FLOATING_BASES]
        if floating:
            rank = {"float": 1, "double": 2, "long double": 3}
            return TypeExpr(base=max(floating, key=rank.__getitem__))
        if not TypeSystem.integer_mix_is_portable(left, right):
            return None
        if left.base == right.base and left.base in _STANDARD_INTEGER_TYPEDEFS:
            return TypeExpr(base=left.base)
        left_rank, left_unsigned = TypeSystem._integral_kind(left.base, enum_names)
        right_rank, right_unsigned = TypeSystem._integral_kind(right.base, enum_names)
        rank = max(left_rank, right_rank)
        unsigned = left_unsigned or right_unsigned
        return TypeExpr(base=_RESULT_BASE[rank, unsigned])

    @staticmethod
    def numeric_operands_need_cast(left: TypeExpr, right: TypeExpr, enum_names: Set[str] = frozenset()) -> bool:
        """Whether host C usual conversions can differ from btrc's result rule."""
        if left.base == right.base:
            return False
        if not TypeSystem.integer_mix_is_portable(left, right):
            return False
        if left.base in _STANDARD_INTEGER_TYPEDEFS or right.base in _STANDARD_INTEGER_TYPEDEFS:
            return True
        if TypeSystem.is_floating_type(left) or TypeSystem.is_floating_type(right):
            return False
        left_rank, left_unsigned = TypeSystem._integral_kind(left.base, enum_names)
        right_rank, right_unsigned = TypeSystem._integral_kind(right.base, enum_names)
        if left_unsigned == right_unsigned:
            return False
        signed_rank = left_rank if not left_unsigned else right_rank
        unsigned_rank = left_rank if left_unsigned else right_rank
        return signed_rank > unsigned_rank

    @staticmethod
    def _integral_kind(base: str, enum_names: Set[str]) -> tuple[int, bool]:
        if base in _INTEGRAL_KINDS:
            return _INTEGRAL_KINDS[base]
        if base in enum_names or base.startswith("enum "):
            return (3, False)
        if base in _PORTABLE_WIDTH_TYPEDEFS:
            digits = next((item for item in (64, 32, 16, 8) if str(item) in base), 64)
            rank = 5 if digits >= 64 else 3
            return (rank, base in _UNSIGNED_TYPEDEFS)
        if base in _ABI_DEPENDENT_INTEGER_TYPEDEFS:
            raise ValueError(f"ABI-dependent integer typedef has no portable rank: {base}")
        raise ValueError(f"not an integral type: {base}")

    @staticmethod
    def _is_scalar(type_expr: TypeExpr | None) -> bool:
        return bool(
            type_expr and type_expr.pointer_depth == 0 and (not type_expr.is_array) and (not type_expr.generic_args)
        )

    @staticmethod
    def is_scalar_string(type_expr) -> bool:
        """Whether a type is exactly the language's scalar string value."""
        return bool(
            type_expr
            and type_expr.base == "string"
            and (type_expr.pointer_depth == 0)
            and (not type_expr.is_array)
            and (not type_expr.generic_args)
        )

    def has_scalar_to_string(self, source_type) -> bool:
        """Whether a semantic class reference provides scalar toString()."""
        source_type = self.canonical_type(source_type)
        if (
            source_type is None
            or source_type.base not in self.index.class_table
            or source_type.pointer_depth != 1
            or source_type.is_array
        ):
            return False
        method = self.index.class_table[source_type.base].methods.get("toString")
        return_type = method.return_type if method is not None else None
        return_type = self.canonical_type(return_type)
        return bool(method and (not method.params) and TypeSystem.is_scalar_string(return_type))

    def requires_class_to_string(self, target_type, source_type) -> bool:
        """Whether these exact source/target shapes require runtime conversion."""
        target_type = self.canonical_type(target_type)
        return TypeSystem.is_scalar_string(target_type) and self.has_scalar_to_string(source_type)

    @staticmethod
    def resolved_reference_shape(type_expr: TypeExpr) -> bool:
        return bool(type_expr.pointer_depth > 0 or type_expr.is_array or type_expr.base in _INTRINSIC_REFERENCE_BASES)

    @staticmethod
    def nullable_collapses_reference_layer(type_expr: TypeExpr, *, base_is_reference: bool = False) -> bool:
        """Whether ``?`` annotates an inner reference instead of adding C storage."""
        if not type_expr.is_nullable or type_expr.pointer_depth <= 0:
            return False
        inner_storage = type_expr.pointer_depth + int(type_expr.is_array) - type_expr.nullable_outer_depth
        return inner_storage > 1 or (base_is_reference and inner_storage > 0)

    @staticmethod
    def compose_type_expr(
        applied: TypeExpr, resolved: TypeExpr, *, reference_shape: TypeExpr | None = None
    ) -> TypeExpr:
        """Apply one source type shell without losing a resolved nullable boundary."""
        reference_shape = reference_shape or resolved
        collapse_applied = TypeSystem.nullable_collapses_reference_layer(
            applied, base_is_reference=TypeSystem.resolved_reference_shape(reference_shape)
        )
        applied_pointer_depth = applied.pointer_depth - int(collapse_applied)
        surviving_shell_storage = applied_pointer_depth + int(applied.is_array)
        if resolved.is_nullable:
            nullable_outer_depth = resolved.nullable_outer_depth + surviving_shell_storage
        elif applied.is_nullable:
            nullable_outer_depth = surviving_shell_storage if collapse_applied else applied.nullable_outer_depth
        else:
            nullable_outer_depth = 0
        return replace(
            resolved,
            pointer_depth=resolved.pointer_depth + applied_pointer_depth,
            is_array=applied.is_array or resolved.is_array,
            array_size=applied.array_size if applied.array_size is not None else resolved.array_size,
            is_const=applied.is_const or resolved.is_const,
            is_nullable=applied.is_nullable or resolved.is_nullable,
            nullable_outer_depth=nullable_outer_depth,
            is_static=applied.is_static or resolved.is_static,
            is_extern=applied.is_extern or resolved.is_extern,
            is_volatile=applied.is_volatile or resolved.is_volatile,
            line=applied.line or resolved.line,
            col=applied.col or resolved.col,
        )

    @staticmethod
    def strip_outer_storage(type_expr: TypeExpr, *, array: bool = False) -> TypeExpr:
        """Remove one outer pointer/array layer and its nullable provenance."""
        changes = {}
        if array:
            changes.update(is_array=False, array_size=None)
        else:
            changes["pointer_depth"] = type_expr.pointer_depth - 1
        if type_expr.nullable_outer_depth > 0:
            changes["nullable_outer_depth"] = type_expr.nullable_outer_depth - 1
        elif type_expr.is_nullable:
            inner_storage = type_expr.pointer_depth + int(type_expr.is_array) - type_expr.nullable_outer_depth
            changes.update(is_nullable=False, nullable_outer_depth=0)
            if inner_storage > 1:
                changes["pointer_depth"] = changes.get("pointer_depth", type_expr.pointer_depth) - 1
        result = replace(type_expr, **changes)
        if (
            result.is_nullable
            and result.nullable_outer_depth == 0
            and (result.pointer_depth + int(result.is_array) == 0)
        ):
            result = replace(result, is_nullable=False)
        return result

    @staticmethod
    def add_outer_pointer(type_expr: TypeExpr, *, clear_array: bool = False) -> TypeExpr:
        """Add address-of storage outside any preserved nullable marker."""
        result = (
            TypeSystem.strip_outer_storage(type_expr, array=True) if clear_array and type_expr.is_array else type_expr
        )
        return replace(
            result,
            pointer_depth=result.pointer_depth + 1,
            nullable_outer_depth=result.nullable_outer_depth + int(result.is_nullable),
        )


__all__ = [
    "CIntegerWidths",
    "IndexedProtocol",
    "IndexedProtocolResolver",
    "NumericLiteralSemantics",
    "OperatorSemantics",
    "OperatorTypeError",
    "StringMethod",
    "TypeIdentity",
    "TypeShapeError",
    "TypeSystem",
]
