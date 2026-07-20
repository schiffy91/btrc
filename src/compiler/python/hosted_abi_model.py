"""Value objects used by the canonical hosted ABI registry."""

from __future__ import annotations

from dataclasses import dataclass

from .ast_nodes import TypeExpr

VALUE = "value"
READ = "read"
MUTATE = "mutate"
# The callee may invalidate this allocation according to its raw lifetime
# protocol.  This is deliberately conservative: conditional consumers such as
# realloc still use CONSUME even though failure leaves the original allocation
# valid.  The effect forbids managed/raw crossing; it does not promise that the
# argument is unconditionally gone on return.
CONSUME = "consume"
UNKNOWN = "unknown"
RETURN_VALUE = "value"
RETURN_FRESH = "fresh"
RETURN_ALIAS = "alias"
RETURN_INDEPENDENT = "independent"
RETURN_OPAQUE = "opaque"
ALIAS_EXACT = "exact"
ALIAS_INTERIOR = "interior"
ALIAS_DEPENDENT = "dependent"
DEALLOC_FREE = "free"


@dataclass(frozen=True)
class AbiType:
    base: str
    pointer_depth: int = 0
    is_const: bool = False

    def as_type_expr(self) -> TypeExpr:
        return TypeExpr(
            base=self.base,
            pointer_depth=self.pointer_depth,
            is_const=self.is_const,
        )


@dataclass(frozen=True)
class HostedFunction:
    result: AbiType
    parameters: tuple[AbiType, ...] | None
    effects: tuple[str, ...] = ()
    variadic: bool = False
    semantic_result: AbiType | None = None
    return_effect: str = RETURN_VALUE
    return_alias_parameter: int | None = None
    return_alias_null_effect: str | None = None
    raw_lifetime: bool = False
    return_deallocator: str | None = None
    return_alias_shape: str | None = None
    consume_deallocator: str | None = None
    return_alias_null_deallocator: str | None = None

    def __post_init__(self) -> None:
        if self.parameters is None:
            if self.effects:
                raise ValueError("opaque hosted ABI cannot declare parameter effects")
            if self.variadic:
                raise ValueError("variadic hosted ABI requires a fixed parameter prefix")
        elif len(self.effects) != len(self.parameters):
            raise ValueError("hosted ABI effects must match the parameter count")
        valid_effects = {VALUE, READ, MUTATE, CONSUME, UNKNOWN}
        if any(effect not in valid_effects for effect in self.effects):
            raise ValueError("hosted ABI contains an unknown parameter effect")
        valid_return_effects = {
            RETURN_VALUE,
            RETURN_FRESH,
            RETURN_ALIAS,
            RETURN_INDEPENDENT,
            RETURN_OPAQUE,
        }
        if self.return_effect not in valid_return_effects:
            raise ValueError("hosted ABI contains an unknown return effect")
        if self.return_effect != RETURN_VALUE and self.result.pointer_depth == 0:
            raise ValueError("hosted ABI pointer-lifetime return effect requires a pointer result")
        aliasing = self.return_effect == RETURN_ALIAS
        if aliasing != (self.return_alias_parameter is not None):
            raise ValueError("hosted ABI alias result requires exactly one alias parameter")
        if self.return_alias_parameter is not None:
            index = self.return_alias_parameter
            if self.parameters is None or not 0 <= index < len(self.parameters):
                raise ValueError("hosted ABI return alias parameter is out of range")
            if self.effects[index] not in {READ, MUTATE}:
                raise ValueError("hosted ABI return alias must reference a borrowed parameter")
            if self.parameters[index].pointer_depth == 0:
                raise ValueError("hosted ABI return alias must reference a pointer parameter")
            if self.result.pointer_depth == 0:
                raise ValueError("hosted ABI scalar result cannot alias a pointer parameter")
        if self.return_alias_null_effect is not None:
            if not aliasing:
                raise ValueError("hosted ABI null-alias effect requires an alias result")
            if self.return_alias_null_effect not in {
                RETURN_FRESH,
                RETURN_INDEPENDENT,
                RETURN_OPAQUE,
            }:
                raise ValueError("hosted ABI contains an invalid null-alias effect")
        if self.return_alias_null_deallocator is not None:
            if self.return_alias_null_effect is None:
                raise ValueError("hosted ABI null deallocator requires a null-alias effect")
            if not self.return_alias_null_deallocator:
                raise ValueError("hosted ABI null deallocator cannot be empty")
        if aliasing != (self.return_alias_shape is not None):
            raise ValueError("hosted ABI alias result requires an explicit alias shape")
        if self.return_alias_shape not in {
            None,
            ALIAS_EXACT,
            ALIAS_INTERIOR,
            ALIAS_DEPENDENT,
        }:
            raise ValueError("hosted ABI contains an invalid alias shape")
        if self.return_deallocator is not None:
            if self.result.pointer_depth == 0 or aliasing:
                raise ValueError("hosted ABI deallocator requires a non-alias pointer result")
            if not self.return_deallocator:
                raise ValueError("hosted ABI deallocator cannot be empty")
        if self.raw_lifetime:
            if not self.parameters or self.effects[0] != CONSUME:
                raise ValueError("raw-lifetime ABI requires parameter zero to be consumed")
            if self.effects.count(CONSUME) != 1:
                raise ValueError("raw-lifetime ABI supports exactly one consumed parameter")
            for parameter, effect in zip(self.parameters, self.effects):
                if effect == CONSUME and parameter.pointer_depth == 0:
                    raise ValueError("raw-lifetime ABI cannot consume a scalar parameter")
            if not self.consume_deallocator:
                raise ValueError("raw-lifetime ABI requires a consumed deallocator family")
        elif self.consume_deallocator is not None:
            raise ValueError("hosted ABI deallocator family requires raw-lifetime consumption")

    @property
    def raw_lifetime_arity(self) -> int | None:
        if not self.raw_lifetime or self.parameters is None:
            return None
        return len(self.parameters)


def abi_type(base: str, depth: int = 0, *, const: bool = False) -> AbiType:
    return AbiType(base, depth, const)


VOID = abi_type("void")
INT = abi_type("int")
UINT = abi_type("unsigned int")
LONG = abi_type("long")
ULONG = abi_type("unsigned long")
LLONG = abi_type("long long")
ULLONG = abi_type("unsigned long long")
SIZE = abi_type("size_t")
FLOAT = abi_type("float")
DOUBLE = abi_type("double")
LDOUBLE = abi_type("long double")
CHAR_PTR = abi_type("char", 1)
CONST_CHAR_PTR = abi_type("char", 1, const=True)
CHAR_PTR_PTR = abi_type("char", 2)
VOID_PTR = abi_type("void", 1)
CONST_VOID_PTR = abi_type("void", 1, const=True)
FILE_PTR = abi_type("FILE", 1)


def function(
    result: AbiType,
    *parameters: AbiType,
    effects: tuple[str, ...] | None = None,
    variadic: bool = False,
    semantic_result: AbiType | None = None,
    return_effect: str | None = None,
    return_alias_parameter: int | None = None,
    return_alias_null_effect: str | None = None,
    raw_lifetime: bool = False,
    return_deallocator: str | None = None,
    return_alias_shape: str | None = None,
    consume_deallocator: str | None = None,
    return_alias_null_deallocator: str | None = None,
) -> HostedFunction:
    return HostedFunction(
        result,
        tuple(parameters),
        effects or tuple(VALUE for _ in parameters),
        variadic,
        semantic_result,
        return_effect or (RETURN_OPAQUE if result.pointer_depth else RETURN_VALUE),
        return_alias_parameter,
        return_alias_null_effect,
        raw_lifetime,
        return_deallocator,
        return_alias_shape,
        consume_deallocator,
        return_alias_null_deallocator,
    )


def uniform(names: str, result: AbiType, *parameters: AbiType) -> dict[str, HostedFunction]:
    return {name: function(result, *parameters) for name in names.split()}


__all__ = [name for name in globals() if name.isupper()] + [
    "AbiType",
    "HostedFunction",
    "abi_type",
    "function",
    "uniform",
]
