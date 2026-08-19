"""Immutable generic-specialization plans for the ordinary lowering stack."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass

from src.compiler.python.analyzer.program import AnalyzedProgram
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.syntax.ast.codec import AstJsonCodec
from src.compiler.python.syntax.ast.generated import ClassDecl, TypeExpr


@dataclass(frozen=True, slots=True, init=False)
class TypeSubstitution:
    """Deeply immutable concrete bindings for one specialized declaration."""

    _argument_values: tuple[tuple[str, str], ...]
    _typedef_values: tuple[tuple[str, str], ...]
    identity: TypeIdentity

    def __init__(
        self,
        arguments: Mapping[str, TypeExpr],
        typedefs: Mapping[str, TypeExpr],
        identity: TypeIdentity,
    ) -> None:
        codec = AstJsonCodec()
        object.__setattr__(self, "_argument_values", self._freeze(arguments, codec))
        object.__setattr__(self, "_typedef_values", self._freeze(typedefs, codec))
        object.__setattr__(self, "identity", identity)

    def resolve(self, type_expr: TypeExpr | None) -> TypeExpr | None:
        arguments = self._thaw(self._argument_values)
        return self.identity.substitute(type_expr, arguments, reference_resolver=self._resolve_typedef)

    def _resolve_typedef(self, type_expr: TypeExpr) -> TypeExpr:
        typedefs = self._thaw(self._typedef_values)
        seen: set[str] = set()
        resolved = type_expr
        while resolved.base in typedefs and resolved.base not in seen:
            seen.add(resolved.base)
            resolved = typedefs[resolved.base]
        return resolved

    @staticmethod
    def _freeze(values: Mapping[str, TypeExpr], codec: AstJsonCodec) -> tuple[tuple[str, str], ...]:
        return tuple(
            sorted(
                (
                    name,
                    json.dumps(codec.encode(value), sort_keys=True, separators=(",", ":")),
                )
                for name, value in values.items()
            )
        )

    @staticmethod
    def _thaw(values: tuple[tuple[str, str], ...]) -> dict[str, TypeExpr]:
        codec = AstJsonCodec()
        return {name: codec.decode(json.loads(value)) for name, value in values}


@dataclass(frozen=True, slots=True)
class SpecializedDeclarationView:
    """One declaration plus its immutable concrete type and symbol view."""

    declaration: object
    substitution: TypeSubstitution
    symbol: str
    base_name: str
    type_arguments: tuple[TypeExpr, ...]


class GenericSpecializer:
    """Plan specializations without owning or invoking a second emitter."""

    def __init__(self, analyzed: AnalyzedProgram, type_identity: TypeIdentity) -> None:
        self._analyzed = analyzed
        self._type_identity = type_identity

    def class_views(self) -> Iterator[SpecializedDeclarationView]:
        declarations = {
            declaration.name: declaration
            for declaration in self._analyzed.program.declarations
            if isinstance(declaration, ClassDecl) and declaration.generic_params
        }
        for base_name, instances in self._analyzed.generic_instances.items():
            declaration = declarations.get(base_name)
            info = self._analyzed.class_table.get(base_name)
            if declaration is None or info is None:
                continue
            for arguments in instances:
                yield self._view(declaration, base_name, info.generic_params, arguments)

    def method_views(self) -> Iterator[SpecializedDeclarationView]:
        for (class_name, method_name), instances in self._analyzed.generic_method_instances.items():
            info = self._analyzed.class_table.get(class_name)
            method = info.methods.get(method_name) if info is not None else None
            if info is None or method is None:
                continue
            for class_arguments, method_arguments in instances:
                parameters = [*info.generic_params, *method.generic_params]
                arguments = [*class_arguments, *method_arguments]
                substitution = self._substitution(parameters, arguments)
                symbol = self._type_identity.method_instance_symbol(
                    class_name, class_arguments, method_name, method_arguments
                )
                yield SpecializedDeclarationView(
                    declaration=method,
                    substitution=substitution,
                    symbol=symbol,
                    base_name=f"{class_name}.{method_name}",
                    type_arguments=tuple(arguments),
                )

    def _view(
        self, declaration: object, base_name: str, parameters: Sequence[str], arguments: Sequence[TypeExpr]
    ) -> SpecializedDeclarationView:
        concrete = tuple(arguments)
        self._type_identity.ensure_supported_generic_arguments(concrete)
        return SpecializedDeclarationView(
            declaration=declaration,
            substitution=self._substitution(parameters, concrete),
            symbol=self._type_identity.specialization_symbol(base_name, concrete),
            base_name=base_name,
            type_arguments=concrete,
        )

    def _substitution(self, parameters: Sequence[str], arguments: Sequence[TypeExpr]) -> TypeSubstitution:
        return TypeSubstitution(
            arguments=dict(zip(parameters, arguments, strict=True)),
            typedefs=self._analyzed.typedef_table,
            identity=self._type_identity,
        )
