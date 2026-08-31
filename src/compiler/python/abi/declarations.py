"""Value objects and invariants for exact hosted-C ABI declarations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.compiler.python.syntax.ast.generated import TypeExpr

if TYPE_CHECKING:
    from .generated import GeneratedAbiTypeRow, GeneratedHostedFunctionRow


VALUE = "value"
READ = "read"
MUTATE = "mutate"
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


@dataclass(frozen=True, slots=True)
class AbiType:
    """A source-representable C type shape at a hosted boundary."""

    base: str
    pointer_depth: int = 0
    is_const: bool = False
    generic_args: tuple[AbiType, ...] = ()

    @classmethod
    def from_generated(cls, row: GeneratedAbiTypeRow) -> AbiType:
        return cls(
            row.base,
            row.pointer_depth,
            row.is_const,
            tuple(cls.from_generated(argument) for argument in getattr(row, "generic_args", ())),
        )

    def as_type_expr(self) -> TypeExpr:
        return TypeExpr(
            base="__fn_ptr" if self.base == "CFunction" else self.base,
            pointer_depth=self.pointer_depth,
            is_const=self.is_const,
            generic_args=[argument.as_type_expr() for argument in self.generic_args],
        )


@dataclass(frozen=True, slots=True)
class HostedFunction:
    """An immutable exact signature plus ownership/lifetime effects."""

    result: AbiType
    parameters: tuple[AbiType, ...] | None
    effects: tuple[str, ...] = ()
    callback_lifetimes: tuple[str | None, ...] = ()
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

    @classmethod
    def from_generated(cls, row: GeneratedHostedFunctionRow) -> HostedFunction:
        parameters = None
        effects: tuple[str, ...] = ()
        if row.parameters is not None:
            parameters = tuple(AbiType.from_generated(parameter.type_shape) for parameter in row.parameters)
            effects = tuple(parameter.effect for parameter in row.parameters)
            callback_lifetimes = tuple(getattr(parameter, "callback_lifetime", None) for parameter in row.parameters)
        else:
            callback_lifetimes = ()
        return cls(
            result=AbiType.from_generated(row.result),
            parameters=parameters,
            effects=effects,
            callback_lifetimes=callback_lifetimes,
            variadic=row.variadic,
            semantic_result=(AbiType.from_generated(row.semantic_result) if row.semantic_result is not None else None),
            return_effect=row.return_effect,
            return_alias_parameter=row.return_alias_parameter,
            return_alias_null_effect=row.return_alias_null_effect,
            raw_lifetime=row.raw_lifetime,
            return_deallocator=row.return_deallocator,
            return_alias_shape=row.return_alias_shape,
            consume_deallocator=row.consume_deallocator,
            return_alias_null_deallocator=row.return_alias_null_deallocator,
        )

    def __post_init__(self) -> None:
        if self.parameters is None:
            if self.effects:
                raise ValueError("opaque hosted ABI cannot declare parameter effects")
            if self.variadic:
                raise ValueError("variadic hosted ABI requires a fixed parameter prefix")
        elif len(self.effects) != len(self.parameters):
            raise ValueError("hosted ABI effects must match the parameter count")
        if self.parameters is not None and not self.callback_lifetimes:
            object.__setattr__(self, "callback_lifetimes", (None,) * len(self.parameters))
        if self.parameters is None:
            if self.callback_lifetimes:
                raise ValueError("opaque hosted ABI cannot declare callback lifetimes")
        elif len(self.callback_lifetimes) != len(self.parameters):
            raise ValueError("hosted ABI callback lifetimes must match the parameter count")
        if any(effect not in {VALUE, READ, MUTATE, CONSUME, UNKNOWN} for effect in self.effects):
            raise ValueError("hosted ABI contains an unknown parameter effect")
        if self.return_effect not in {
            RETURN_VALUE,
            RETURN_FRESH,
            RETURN_ALIAS,
            RETURN_INDEPENDENT,
            RETURN_OPAQUE,
        }:
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
        if self.return_alias_null_effect is not None:
            if not aliasing or self.return_alias_null_effect not in {
                RETURN_FRESH,
                RETURN_INDEPENDENT,
                RETURN_OPAQUE,
            }:
                raise ValueError("hosted ABI contains an invalid null-alias effect")
        if self.return_alias_null_deallocator is not None and self.return_alias_null_effect is None:
            raise ValueError("hosted ABI null deallocator requires a null-alias effect")
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
