"""Stable dependency planning for typed C type declarations."""

from __future__ import annotations

from collections.abc import Iterable

from .expr_nodes import CType
from .optimizer_walk import IdentifierReferences, IRTree
from .top_nodes import (
    IREnumDef,
    IRFunctionPointerTypedef,
    IRStructDef,
    IRTaggedUnionDef,
    IRTypedefDef,
)

TypeDeclaration = IREnumDef | IRFunctionPointerTypedef | IRTypedefDef | IRTaggedUnionDef | IRStructDef

_AGGREGATE_TYPES = (IRStructDef, IRTaggedUnionDef)
_COMPLETE_TYPE_CONTEXTS = (*_AGGREGATE_TYPES, IREnumDef)


class TypeDeclarationPlanner:
    """Own one strict-C declaration-order plan for an IR module."""

    def __init__(self, module):
        self._declarations: tuple[TypeDeclaration, ...] = (
            *module.enum_defs,
            *module.function_pointer_typedefs,
            *module.typedef_defs,
            *module.tagged_union_defs,
            *module.struct_defs,
        )
        self._providers = self._type_providers()
        self._value_providers = self._enum_value_providers()
        self._type_references = IdentifierReferences(self._providers)

    def plan(self) -> list[TypeDeclaration]:
        if not self._declarations:
            return []

        alias_targets = self._alias_complete_targets()
        dependencies = [
            self._dependencies(index, declaration, alias_targets)
            for index, declaration in enumerate(self._declarations)
        ]
        return self._stable_topological_order(dependencies)

    def _provided_names(self, declaration: TypeDeclaration) -> Iterable[str]:
        if isinstance(declaration, IREnumDef):
            if declaration.name is not None:
                yield declaration.name
            return
        yield declaration.name
        if isinstance(declaration, IRTaggedUnionDef):
            for variant in declaration.variants:
                if variant.fields:
                    yield f"{declaration.name}_{variant.name}_Data"

    def _type_providers(self) -> dict[str, int]:
        providers: dict[str, int] = {}
        for index, declaration in enumerate(self._declarations):
            for name in self._provided_names(declaration):
                previous = providers.get(name)
                if previous is not None and previous != index:
                    raise ValueError(f"duplicate typed C declaration provider '{name}'")
                providers[name] = index
        return providers

    def _enum_value_providers(self) -> dict[str, int]:
        providers: dict[str, int] = {}
        for index, declaration in enumerate(self._declarations):
            if not isinstance(declaration, IREnumDef):
                continue
            for value in declaration.values:
                previous = providers.get(value.name)
                if previous is not None and previous != index:
                    raise ValueError(f"duplicate typed C enum-value provider '{value.name}'")
                providers[value.name] = index
        return providers

    def _ctype_references(self, c_type: CType) -> set[str]:
        references: set[str] = set()
        self._type_references.scan(c_type.text, references)
        return references

    def _alias_complete_targets(self) -> dict[int, set[int]]:
        memo: dict[int, set[int]] = {}
        for index in range(len(self._declarations)):
            self._resolve_alias_targets(index, memo, set())
        return memo

    def _resolve_alias_targets(
        self,
        index: int,
        memo: dict[int, set[int]],
        visiting: set[int],
    ) -> set[int]:
        if index in memo:
            return memo[index]
        if index in visiting:
            return set()
        declaration = self._declarations[index]
        if not isinstance(declaration, IRTypedefDef):
            return set()
        if "*" in declaration.target_type.text:
            memo[index] = set()
            return set()

        visiting.add(index)
        targets: set[int] = set()
        for name in self._ctype_references(declaration.target_type):
            provider = self._providers[name]
            provided = self._declarations[provider]
            if isinstance(provided, _AGGREGATE_TYPES):
                targets.add(provider)
            elif isinstance(provided, IRTypedefDef):
                targets.update(self._resolve_alias_targets(provider, memo, visiting))
        visiting.remove(index)
        memo[index] = targets
        return targets

    def _dependencies(
        self,
        declaration_index: int,
        declaration: TypeDeclaration,
        alias_targets: dict[int, set[int]],
    ) -> set[int]:
        dependencies: set[int] = set()
        complete_type_context = isinstance(declaration, _COMPLETE_TYPE_CONTEXTS)
        for node in IRTree(declaration):
            if not isinstance(node, CType):
                continue
            requires_complete = complete_type_context and "*" not in node.text
            for name in self._ctype_references(node):
                provider = self._providers[name]
                provided = self._declarations[provider]
                if not isinstance(provided, _AGGREGATE_TYPES) or requires_complete:
                    dependencies.add(provider)
                if requires_complete and isinstance(provided, IRTypedefDef):
                    dependencies.update(alias_targets.get(provider, ()))

        if isinstance(declaration, IREnumDef) and self._value_providers:
            references: set[str] = set()
            IRTree(declaration).collect_value_references(
                set(self._value_providers),
                references,
            )
            dependencies.update(
                self._value_providers[name] for name in references if self._value_providers[name] != declaration_index
            )
        return dependencies

    def _stable_topological_order(self, dependencies: list[set[int]]) -> list[TypeDeclaration]:
        completed: set[int] = set()
        ordered: list[TypeDeclaration] = []
        while len(ordered) < len(self._declarations):
            progressed = False
            for index, declaration in enumerate(self._declarations):
                if index in completed or not dependencies[index] <= completed:
                    continue
                completed.add(index)
                ordered.append(declaration)
                progressed = True
            if progressed:
                continue
            names = ", ".join(
                self._declaration_name(self._declarations[index])
                for index in range(len(self._declarations))
                if index not in completed
            )
            raise ValueError(f"cyclic typed C declaration dependency involving {names}")
        return ordered

    def _declaration_name(self, declaration: TypeDeclaration) -> str:
        return declaration.name or "<anonymous enum>"


__all__ = ["TypeDeclarationPlanner"]
