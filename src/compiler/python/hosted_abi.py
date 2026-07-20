"""Canonical registry for compiler-owned hosted C symbols and ABI effects."""

from __future__ import annotations

from .ast_nodes import CastExpr, Identifier, NullLiteral, TypeExpr
from .hosted_abi_concurrency import (
    HOSTED_CONCURRENCY_FUNCTIONS,
    HOSTED_CONCURRENCY_NAMES,
)
from .hosted_abi_ctype import HOSTED_CTYPE_FUNCTIONS, HOSTED_CTYPE_NAMES
from .hosted_abi_macros import HOSTED_MACROS as HOSTED_C_MACROS
from .hosted_abi_math import HOSTED_MATH_FUNCTIONS, HOSTED_MATH_NAMES
from .hosted_abi_model import (
    ALIAS_DEPENDENT,
    ALIAS_EXACT,
    ALIAS_INTERIOR,
    CONSUME,
    DEALLOC_FREE,
    MUTATE,
    READ,
    RETURN_ALIAS,
    RETURN_FRESH,
    RETURN_INDEPENDENT,
    RETURN_OPAQUE,
    UNKNOWN,
    VALUE,
    AbiType,
    HostedFunction,
)
from .hosted_abi_native import HOSTED_NATIVE_FUNCTIONS, HOSTED_NATIVE_NAMES
from .hosted_abi_platform_names import (
    HOSTED_PLATFORM_FUNCTION_NAMES,
    HOSTED_PLATFORM_MACROS,
    HOSTED_PLATFORM_OBJECT_NAMES,
    HOSTED_PLATFORM_TYPE_NAMES,
    HOSTED_PLATFORM_TYPEDEF_NAMES,
)
from .hosted_abi_posix import HOSTED_POSIX_FUNCTIONS, HOSTED_POSIX_NAMES
from .hosted_abi_runtime import (
    SOURCE_RUNTIME_ADOPTING_HELPERS,
    SOURCE_RUNTIME_FUNCTIONS,
    SOURCE_RUNTIME_HELPERS,
)
from .hosted_abi_stdio import HOSTED_STDIO_FUNCTIONS, HOSTED_STDIO_NAMES
from .hosted_abi_stdlib import HOSTED_STDLIB_FUNCTIONS, HOSTED_STDLIB_NAMES
from .hosted_abi_string import HOSTED_STRING_FUNCTIONS, HOSTED_STRING_NAMES
from .hosted_abi_types import (
    HOSTED_OBJECT_NAMES as HOSTED_C_OBJECT_NAMES,
)
from .hosted_abi_types import (
    HOSTED_TYPE_NAMES as HOSTED_C_TYPE_NAMES,
)

HOSTED_MACROS = HOSTED_C_MACROS | HOSTED_PLATFORM_MACROS
HOSTED_OBJECT_NAMES = HOSTED_C_OBJECT_NAMES | HOSTED_PLATFORM_OBJECT_NAMES
HOSTED_TYPE_NAMES = HOSTED_C_TYPE_NAMES | HOSTED_PLATFORM_TYPE_NAMES
HOSTED_TYPEDEF_NAMES = HOSTED_C_TYPE_NAMES | HOSTED_PLATFORM_TYPEDEF_NAMES


def _merge_registries(*registries) -> dict[str, HostedFunction]:
    merged: dict[str, HostedFunction] = {}
    for registry in registries:
        for name, spec in registry.items():
            previous = merged.get(name)
            if previous is not None and previous != spec:
                raise ValueError(f"conflicting hosted ABI specs for {name!r}")
            merged[name] = spec
    return merged


HOSTED_FUNCTIONS = _merge_registries(
    HOSTED_STDIO_FUNCTIONS,
    HOSTED_STDLIB_FUNCTIONS,
    HOSTED_STRING_FUNCTIONS,
    HOSTED_CTYPE_FUNCTIONS,
    HOSTED_MATH_FUNCTIONS,
    HOSTED_CONCURRENCY_FUNCTIONS,
    HOSTED_POSIX_FUNCTIONS,
    HOSTED_NATIVE_FUNCTIONS,
    SOURCE_RUNTIME_FUNCTIONS,
)
HOSTED_FUNCTION_OWNED_NAMES = frozenset(
    {
        *HOSTED_STDIO_NAMES,
        *HOSTED_STDLIB_NAMES,
        *HOSTED_STRING_NAMES,
        *HOSTED_CTYPE_NAMES,
        *HOSTED_MATH_NAMES,
        *HOSTED_CONCURRENCY_NAMES,
        *HOSTED_POSIX_NAMES,
        *HOSTED_PLATFORM_FUNCTION_NAMES,
        *HOSTED_NATIVE_NAMES,
        *SOURCE_RUNTIME_HELPERS,
    }
)
HOSTED_OWNED_NAMES = frozenset(
    {
        *HOSTED_FUNCTION_OWNED_NAMES,
        *HOSTED_MACROS,
        *HOSTED_TYPE_NAMES,
        *HOSTED_OBJECT_NAMES,
    }
)


def hosted_function(name: str) -> HostedFunction | None:
    return HOSTED_FUNCTIONS.get(name)


def hosted_owned_name(name: str) -> bool:
    return name in HOSTED_OWNED_NAMES


def hosted_macro_name(name: str) -> bool:
    return name in HOSTED_MACROS


def hosted_function_owned_name(name: str) -> bool:
    return name in HOSTED_FUNCTION_OWNED_NAMES


def hosted_macro_reference_requires_semantic_call(name: str) -> bool:
    """Whether hiding a hosted call behind a macro would erase safety facts."""
    if not hosted_function_owned_name(name):
        return False
    spec = hosted_function(name)
    if spec is None or spec.parameters is None or spec.variadic:
        return True
    semantic_result = spec.semantic_result or spec.result
    if semantic_result.pointer_depth > 0:
        return True
    return any(
        effect != (READ if parameter.pointer_depth > 0 else VALUE)
        for parameter, effect in zip(spec.parameters, spec.effects)
    )


def hosted_semantic_result(name: str) -> TypeExpr | None:
    spec = hosted_function(name)
    if spec is None:
        return None
    return (spec.semantic_result or spec.result).as_type_expr()


def hosted_raw_lifetime_arity(name: str) -> int | None:
    spec = hosted_function(name)
    return spec.raw_lifetime_arity if spec is not None else None


def hosted_parameter_effect(name: str, index: int) -> str:
    spec = hosted_function(name)
    if spec is None or not 0 <= index < len(spec.effects):
        return UNKNOWN
    return spec.effects[index]


def hosted_parameter_is_nonescaping(name: str, index: int) -> bool:
    return hosted_parameter_effect(name, index) in {READ, MUTATE, VALUE}


def hosted_parameter_is_read_only_borrow(name: str, index: int) -> bool:
    """Whether a wrapper may preserve a raw borrow through this parameter.

    A mutating pointer may be non-escaping but is not safe for a wrapper that
    was handed a managed value's representation.  Scalar-by-value parameters
    carry no borrow and are harmless; pointer ``VALUE`` effects are not.
    """
    spec = hosted_function(name)
    if spec is None or spec.parameters is None or not 0 <= index < len(spec.parameters):
        return False
    effect = hosted_parameter_effect(name, index)
    return effect == READ or (effect == VALUE and spec.parameters[index].pointer_depth == 0)


def hosted_parameter_is_readonly(name: str, index: int) -> bool:
    """Compatibility spelling for the stable read-only-borrow query."""
    return hosted_parameter_is_read_only_borrow(name, index)


def hosted_return_alias_parameter(name: str) -> int | None:
    spec = hosted_function(name)
    if spec is None or spec.return_effect != RETURN_ALIAS:
        return None
    return spec.return_alias_parameter


def hosted_return_effect(name: str, *, alias_argument_is_null: bool = False) -> str:
    spec = hosted_function(name)
    if spec is None:
        return RETURN_OPAQUE
    if alias_argument_is_null and spec.return_alias_null_effect is not None:
        return spec.return_alias_null_effect
    return spec.return_effect


def hosted_return_deallocator(
    name: str,
    *,
    alias_argument_is_null: bool = False,
) -> str | None:
    spec = hosted_function(name)
    if spec is None:
        return None
    if alias_argument_is_null and spec.return_alias_null_effect is not None:
        return spec.return_alias_null_deallocator
    return spec.return_deallocator


def hosted_return_alias_shape(name: str) -> str | None:
    spec = hosted_function(name)
    return spec.return_alias_shape if spec is not None else None


def hosted_consume_deallocator(name: str) -> str | None:
    spec = hosted_function(name)
    return spec.consume_deallocator if spec is not None else None


def hosted_source_helper_adopts_raw_string(name: str, index: int) -> bool:
    """Whether this compiler helper adopts raw free-compatible string storage."""
    return name in SOURCE_RUNTIME_ADOPTING_HELPERS and index == 0 and hosted_parameter_effect(name, index) == CONSUME


def hosted_alias_argument_is_provably_null(name: str, arguments) -> bool:
    """Recognize a null alias operand through representation-only casts."""
    spec = hosted_function(name)
    if spec is None or spec.return_alias_parameter is None:
        return False
    index = spec.return_alias_parameter
    if not 0 <= index < len(arguments):
        return False
    expression = arguments[index]
    while isinstance(expression, CastExpr):
        expression = expression.expr
    return isinstance(expression, NullLiteral) or (isinstance(expression, Identifier) and expression.name == "NULL")


def source_hosted_function_symbol(name: str) -> str:
    return f"__btrc_source_{name}" if hosted_owned_name(name) else name


__all__ = [
    "ALIAS_DEPENDENT",
    "ALIAS_EXACT",
    "ALIAS_INTERIOR",
    "CONSUME",
    "DEALLOC_FREE",
    "HOSTED_FUNCTIONS",
    "HOSTED_FUNCTION_OWNED_NAMES",
    "HOSTED_MACROS",
    "HOSTED_NATIVE_NAMES",
    "HOSTED_OBJECT_NAMES",
    "HOSTED_OWNED_NAMES",
    "HOSTED_TYPEDEF_NAMES",
    "HOSTED_TYPE_NAMES",
    "MUTATE",
    "READ",
    "RETURN_ALIAS",
    "RETURN_FRESH",
    "RETURN_INDEPENDENT",
    "RETURN_OPAQUE",
    "SOURCE_RUNTIME_HELPERS",
    "UNKNOWN",
    "VALUE",
    "AbiType",
    "HostedFunction",
    "hosted_alias_argument_is_provably_null",
    "hosted_consume_deallocator",
    "hosted_function",
    "hosted_function_owned_name",
    "hosted_macro_name",
    "hosted_macro_reference_requires_semantic_call",
    "hosted_owned_name",
    "hosted_parameter_effect",
    "hosted_parameter_is_nonescaping",
    "hosted_parameter_is_read_only_borrow",
    "hosted_parameter_is_readonly",
    "hosted_raw_lifetime_arity",
    "hosted_return_alias_parameter",
    "hosted_return_alias_shape",
    "hosted_return_deallocator",
    "hosted_return_effect",
    "hosted_semantic_result",
    "hosted_source_helper_adopts_raw_string",
    "source_hosted_function_symbol",
]
