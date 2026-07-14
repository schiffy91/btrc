"""Stable dependency planning for typed C type declarations."""

from __future__ import annotations

from collections.abc import Iterable

from .expr_nodes import CType
from .optimizer_walk import (
    collect_value_references,
    identifier_pattern,
    iter_ir_nodes,
    scan_text,
)
from .top_nodes import (
    IREnumDef,
    IRFunctionPointerTypedef,
    IRStructDef,
    IRTaggedUnionDef,
    IRTypedefDef,
)

TypeDeclaration = IREnumDef | IRFunctionPointerTypedef | IRTypedefDef | IRTaggedUnionDef | IRStructDef

_AGGREGATE_TYPES = (IRStructDef, IRTaggedUnionDef)


def plan_type_declarations(module) -> list[TypeDeclaration]:
    """Return one stable order satisfying every strict-C type dependency."""
    declarations = _module_declarations(module)
    if not declarations:
        return []

    providers = _type_providers(declarations)
    type_pattern = identifier_pattern(set(providers))
    value_providers = _enum_value_providers(declarations)
    alias_targets = _alias_complete_targets(
        declarations,
        providers,
        type_pattern,
    )
    dependencies = [
        _dependencies(
            index,
            declaration,
            declarations,
            providers,
            type_pattern,
            value_providers,
            alias_targets,
        )
        for index, declaration in enumerate(declarations)
    ]
    return _stable_topological_order(declarations, dependencies)


def _module_declarations(module) -> list[TypeDeclaration]:
    return [
        *module.enum_defs,
        *module.function_pointer_typedefs,
        *module.typedef_defs,
        *module.tagged_union_defs,
        *module.struct_defs,
    ]


def _provided_names(declaration: TypeDeclaration) -> Iterable[str]:
    if isinstance(declaration, IREnumDef):
        if declaration.name is not None:
            yield declaration.name
        return
    yield declaration.name
    if isinstance(declaration, IRTaggedUnionDef):
        for variant in declaration.variants:
            if variant.fields:
                yield f"{declaration.name}_{variant.name}_Data"


def _type_providers(declarations: list[TypeDeclaration]) -> dict[str, int]:
    providers: dict[str, int] = {}
    for index, declaration in enumerate(declarations):
        for name in _provided_names(declaration):
            previous = providers.get(name)
            if previous is not None and previous != index:
                raise ValueError(f"duplicate typed C declaration provider '{name}'")
            providers[name] = index
    return providers


def _enum_value_providers(
    declarations: list[TypeDeclaration],
) -> dict[str, int]:
    providers: dict[str, int] = {}
    for index, declaration in enumerate(declarations):
        if not isinstance(declaration, IREnumDef):
            continue
        for value in declaration.values:
            previous = providers.get(value.name)
            if previous is not None and previous != index:
                raise ValueError(f"duplicate typed C enum-value provider '{value.name}'")
            providers[value.name] = index
    return providers


def _ctype_references(
    c_type: CType,
    pattern,
) -> set[str]:
    references: set[str] = set()
    scan_text(c_type.text, pattern, references)
    return references


def _alias_complete_targets(
    declarations: list[TypeDeclaration],
    providers: dict[str, int],
    pattern,
) -> dict[int, set[int]]:
    memo: dict[int, set[int]] = {}

    def resolve(index: int, visiting: set[int]) -> set[int]:
        if index in memo:
            return memo[index]
        if index in visiting:
            return set()
        declaration = declarations[index]
        if not isinstance(declaration, IRTypedefDef):
            return set()
        if "*" in declaration.target_type.text:
            memo[index] = set()
            return set()
        visiting.add(index)
        targets: set[int] = set()
        for name in _ctype_references(declaration.target_type, pattern):
            provider = providers[name]
            provided = declarations[provider]
            if isinstance(provided, _AGGREGATE_TYPES):
                targets.add(provider)
            elif isinstance(provided, IRTypedefDef):
                targets.update(resolve(provider, visiting))
        visiting.remove(index)
        memo[index] = targets
        return targets

    for index in range(len(declarations)):
        resolve(index, set())
    return memo


def _dependencies(
    declaration_index: int,
    declaration: TypeDeclaration,
    declarations: list[TypeDeclaration],
    providers: dict[str, int],
    type_pattern,
    value_providers: dict[str, int],
    alias_targets: dict[int, set[int]],
) -> set[int]:
    dependencies: set[int] = set()
    complete_type_context = isinstance(
        declaration,
        (*_AGGREGATE_TYPES, IREnumDef),
    )
    for node in iter_ir_nodes(declaration):
        if not isinstance(node, CType):
            continue
        requires_complete = complete_type_context and "*" not in node.text
        for name in _ctype_references(node, type_pattern):
            provider = providers[name]
            provided = declarations[provider]
            if not isinstance(provided, _AGGREGATE_TYPES) or requires_complete:
                dependencies.add(provider)
            if requires_complete and isinstance(provided, IRTypedefDef):
                dependencies.update(alias_targets.get(provider, ()))

    if isinstance(declaration, IREnumDef) and value_providers:
        references: set[str] = set()
        collect_value_references(
            declaration,
            set(value_providers),
            references,
        )
        dependencies.update(value_providers[name] for name in references if value_providers[name] != declaration_index)
    return dependencies


def _stable_topological_order(
    declarations: list[TypeDeclaration],
    dependencies: list[set[int]],
) -> list[TypeDeclaration]:
    completed: set[int] = set()
    ordered: list[TypeDeclaration] = []
    while len(ordered) < len(declarations):
        progressed = False
        for index, declaration in enumerate(declarations):
            if index in completed or not dependencies[index] <= completed:
                continue
            completed.add(index)
            ordered.append(declaration)
            progressed = True
        if progressed:
            continue
        names = ", ".join(
            _declaration_name(declarations[index]) for index in range(len(declarations)) if index not in completed
        )
        raise ValueError(f"cyclic typed C declaration dependency involving {names}")
    return ordered


def _declaration_name(declaration: TypeDeclaration) -> str:
    return declaration.name or "<anonymous enum>"
