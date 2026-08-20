"""Immutable hosted-C ABI repository and semantic query policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType

from src.compiler.python.syntax.ast.generated import CallExpr, CastExpr, Identifier, NullLiteral, TypeExpr

from .declarations import (
    CONSUME,
    MUTATE,
    READ,
    RETURN_ALIAS,
    RETURN_OPAQUE,
    UNKNOWN,
    VALUE,
    HostedFunction,
)
from .generated import (
    HOSTED_ABI_FINGERPRINT,
    HOSTED_FUNCTION_NAMES,
    HOSTED_FUNCTION_ROWS,
    HOSTED_MACRO_NAMES,
    HOSTED_NATIVE_INTERNAL_NAMES,
    HOSTED_NATIVE_NAMES,
    HOSTED_OBJECT_NAMES,
    HOSTED_OWNED_NAMES,
    HOSTED_PLATFORM_FUNCTION_NAMES,
    HOSTED_PLATFORM_MACRO_NAMES,
    HOSTED_PLATFORM_OBJECT_NAMES,
    HOSTED_PLATFORM_TYPE_NAMES,
    HOSTED_PLATFORM_TYPEDEF_NAMES,
    HOSTED_RUNTIME_ADOPTING_HELPERS,
    HOSTED_STDLIB_SOURCE_MARKER,
    HOSTED_TYPE_NAMES,
    HOSTED_TYPEDEF_NAMES,
    HOSTED_USER_SOURCE_MARKER,
)


class HostedAbiRepository:
    """Own exact declarations, hosted namespaces, and all ABI queries."""

    def __init__(self) -> None:
        functions = {row.name: HostedFunction.from_generated(row) for row in HOSTED_FUNCTION_ROWS}
        if len(functions) != len(HOSTED_FUNCTION_ROWS):
            raise ValueError("generated hosted ABI contains duplicate exact functions")
        self._functions = MappingProxyType(functions)
        self._function_names = frozenset(HOSTED_FUNCTION_NAMES)
        self._macros = frozenset(HOSTED_MACRO_NAMES)
        self._objects = frozenset(HOSTED_OBJECT_NAMES)
        self._types = frozenset(HOSTED_TYPE_NAMES)
        self._typedefs = frozenset(HOSTED_TYPEDEF_NAMES)
        self._owned = frozenset(HOSTED_OWNED_NAMES)
        self._native = frozenset(HOSTED_NATIVE_NAMES)
        self._native_internal = frozenset(HOSTED_NATIVE_INTERNAL_NAMES)
        self._runtime_adopting = frozenset(HOSTED_RUNTIME_ADOPTING_HELPERS)
        self._platform_functions = frozenset(HOSTED_PLATFORM_FUNCTION_NAMES)
        self._platform_macros = frozenset(HOSTED_PLATFORM_MACRO_NAMES)
        self._platform_objects = frozenset(HOSTED_PLATFORM_OBJECT_NAMES)
        self._platform_types = frozenset(HOSTED_PLATFORM_TYPE_NAMES)
        self._platform_typedefs = frozenset(HOSTED_PLATFORM_TYPEDEF_NAMES)

    @property
    def functions(self) -> Mapping[str, HostedFunction]:
        return self._functions

    @property
    def function_names(self) -> frozenset[str]:
        return self._function_names

    @property
    def macros(self) -> frozenset[str]:
        return self._macros

    @property
    def objects(self) -> frozenset[str]:
        return self._objects

    @property
    def types(self) -> frozenset[str]:
        return self._types

    @property
    def typedefs(self) -> frozenset[str]:
        return self._typedefs

    @property
    def owned_names(self) -> frozenset[str]:
        return self._owned

    @property
    def native_names(self) -> frozenset[str]:
        return self._native

    @property
    def native_internal_names(self) -> frozenset[str]:
        return self._native_internal

    @property
    def platform_function_names(self) -> frozenset[str]:
        return self._platform_functions

    @property
    def platform_macro_names(self) -> frozenset[str]:
        return self._platform_macros

    @property
    def platform_object_names(self) -> frozenset[str]:
        return self._platform_objects

    @property
    def platform_type_names(self) -> frozenset[str]:
        return self._platform_types

    @property
    def platform_typedef_names(self) -> frozenset[str]:
        return self._platform_typedefs

    @property
    def stdlib_source_marker(self) -> str:
        return HOSTED_STDLIB_SOURCE_MARKER

    @property
    def user_source_marker(self) -> str:
        return HOSTED_USER_SOURCE_MARKER

    @property
    def fingerprint(self) -> str:
        return HOSTED_ABI_FINGERPRINT

    def function(self, name: str) -> HostedFunction | None:
        return self._functions.get(name)

    def owned_name(self, name: str) -> bool:
        return name in self._owned

    def macro_name(self, name: str) -> bool:
        return name in self._macros

    def function_owned_name(self, name: str) -> bool:
        return name in self._function_names

    def macro_reference_requires_semantic_call(self, name: str) -> bool:
        if not self.function_owned_name(name):
            return False
        spec = self.function(name)
        if spec is None or spec.parameters is None or spec.variadic:
            return True
        semantic_result = spec.semantic_result or spec.result
        if semantic_result.pointer_depth > 0:
            return True
        return any(
            effect != (READ if parameter.pointer_depth > 0 else VALUE)
            for parameter, effect in zip(spec.parameters, spec.effects)
        )

    def semantic_result(self, name: str) -> TypeExpr | None:
        spec = self.function(name)
        if spec is None:
            return None
        return (spec.semantic_result or spec.result).as_type_expr()

    def raw_lifetime_arity(self, name: str) -> int | None:
        spec = self.function(name)
        return spec.raw_lifetime_arity if spec is not None else None

    def parameter_effect(self, name: str, index: int) -> str:
        spec = self.function(name)
        if spec is None or not 0 <= index < len(spec.effects):
            return UNKNOWN
        return spec.effects[index]

    def parameter_is_nonescaping(self, name: str, index: int) -> bool:
        return self.parameter_effect(name, index) in {READ, MUTATE, VALUE}

    def parameter_is_read_only_borrow(self, name: str, index: int) -> bool:
        spec = self.function(name)
        if spec is None or spec.parameters is None or not 0 <= index < len(spec.parameters):
            return False
        effect = self.parameter_effect(name, index)
        return effect == READ or (effect == VALUE and spec.parameters[index].pointer_depth == 0)

    def return_alias_parameter(self, name: str) -> int | None:
        spec = self.function(name)
        if spec is None or spec.return_effect != RETURN_ALIAS:
            return None
        return spec.return_alias_parameter

    def return_effect(self, name: str, *, alias_argument_is_null: bool = False) -> str:
        spec = self.function(name)
        if spec is None:
            return RETURN_OPAQUE
        if alias_argument_is_null and spec.return_alias_null_effect is not None:
            return spec.return_alias_null_effect
        return spec.return_effect

    def return_deallocator(self, name: str, *, alias_argument_is_null: bool = False) -> str | None:
        spec = self.function(name)
        if spec is None:
            return None
        if alias_argument_is_null and spec.return_alias_null_effect is not None:
            return spec.return_alias_null_deallocator
        return spec.return_deallocator

    def return_alias_shape(self, name: str) -> str | None:
        spec = self.function(name)
        return spec.return_alias_shape if spec is not None else None

    def consume_deallocator(self, name: str) -> str | None:
        spec = self.function(name)
        return spec.consume_deallocator if spec is not None else None

    def source_helper_adopts_raw_string(self, name: str, index: int) -> bool:
        return name in self._runtime_adopting and index == 0 and self.parameter_effect(name, index) == CONSUME

    def alias_argument_is_provably_null(self, name: str, arguments: Sequence[object]) -> bool:
        spec = self.function(name)
        if spec is None or spec.return_alias_parameter is None:
            return False
        index = spec.return_alias_parameter
        if not 0 <= index < len(arguments):
            return False
        expression = arguments[index]
        while isinstance(expression, CastExpr):
            expression = expression.expr
        return isinstance(expression, NullLiteral) or (isinstance(expression, Identifier) and expression.name == "NULL")

    def source_function_symbol(self, name: str) -> str:
        return f"__btrc_source_{name}" if self.owned_name(name) else name

    def resolved_alias_argument(self, expression: object, hosted_call_ids: set[int]) -> object | None:
        """Return the aliased operand only for an analyzer-resolved hosted call."""

        if (
            not isinstance(expression, CallExpr)
            or not isinstance(expression.callee, Identifier)
            or id(expression) not in hosted_call_ids
        ):
            return None
        index = self.return_alias_parameter(expression.callee.name)
        if index is None or not 0 <= index < len(expression.args):
            return None
        return expression.args[index]


HOSTED_ABI = HostedAbiRepository()
