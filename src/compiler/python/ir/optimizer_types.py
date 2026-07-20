"""Top-level type and external-function reachability passes."""

from __future__ import annotations

from typing import Protocol

from .nodes import IREnumDef, IRModule, IRTaggedUnionDef
from .optimizer_walk import (
    collect_c_type_references,
    collect_callable_references,
    collect_value_references,
    identifier_pattern,
    scan_macro_replacements,
    scan_text,
)

DeclarationKey = tuple[str, int]


class _NamedDeclaration(Protocol):
    name: str | None


def eliminate_dead_type_declarations(module: IRModule) -> None:
    """Keep the transitive closure of referenced named C declarations.

    Resolved ``CType`` leaves and structured enum-value references are the only
    typed roots. Macro replacements and surviving helper bodies are deliberately
    opaque C boundaries, so whole identifiers in those two sources also root
    declarations.
    """
    declarations = _type_declarations(module)
    if not declarations:
        return

    type_providers: dict[str, set[DeclarationKey]] = {}
    value_providers: dict[str, set[DeclarationKey]] = {}
    for key, declaration in declarations.items():
        for name in _provided_type_names(declaration):
            type_providers.setdefault(name, set()).add(key)
        for name in _provided_value_names(declaration):
            value_providers.setdefault(name, set()).add(key)

    type_names = set(type_providers)
    value_names = set(value_providers)
    type_pattern = identifier_pattern(type_names)
    value_pattern = identifier_pattern(value_names)
    referenced_types: set[str] = set()
    referenced_values: set[str] = set()

    for root in (
        *module.function_defs,
        *module.global_decls,
        *module.function_decls,
    ):
        collect_c_type_references(root, type_pattern, referenced_types)
        collect_value_references(root, value_names, referenced_values)
    for helper in module.helper_decls:
        scan_text(helper.c_source, type_pattern, referenced_types)
        scan_text(helper.c_source, value_pattern, referenced_values)
    scan_macro_replacements(module.preprocessor_decls, type_pattern, referenced_types)
    scan_macro_replacements(module.preprocessor_decls, value_pattern, referenced_values)

    keep = _provider_keys(referenced_types, type_providers) | _provider_keys(
        referenced_values,
        value_providers,
    )
    worklist = list(keep)
    while worklist:
        declaration = declarations[worklist.pop()]
        dependencies: set[str] = set()
        value_dependencies: set[str] = set()
        collect_c_type_references(declaration, type_pattern, dependencies)
        collect_value_references(declaration, value_names, value_dependencies)
        required = _provider_keys(dependencies, type_providers) | _provider_keys(
            value_dependencies,
            value_providers,
        )
        for key in required - keep:
            keep.add(key)
            worklist.append(key)

    module.enum_defs = _kept(module.enum_defs, "enum", keep)
    module.struct_forwards = _kept(module.struct_forwards, "forward", keep)
    module.function_pointer_typedefs = _kept(module.function_pointer_typedefs, "fnptr", keep)
    module.typedef_defs = _kept(module.typedef_defs, "typedef", keep)
    module.tagged_union_defs = _kept(module.tagged_union_defs, "tagged", keep)
    module.struct_defs = _kept(module.struct_defs, "struct", keep)


def _type_declarations(module: IRModule) -> dict[DeclarationKey, _NamedDeclaration]:
    groups = (
        ("enum", module.enum_defs),
        ("forward", module.struct_forwards),
        ("fnptr", module.function_pointer_typedefs),
        ("typedef", module.typedef_defs),
        ("tagged", module.tagged_union_defs),
        ("struct", module.struct_defs),
    )
    return {(kind, index): declaration for kind, group in groups for index, declaration in enumerate(group)}


def _provided_type_names(declaration: _NamedDeclaration) -> set[str]:
    names = {declaration.name} if declaration.name is not None else set()
    if isinstance(declaration, IRTaggedUnionDef):
        names.update(f"{declaration.name}_{variant.name}_Data" for variant in declaration.variants if variant.fields)
    return names


def _provided_value_names(declaration: _NamedDeclaration) -> set[str]:
    if not isinstance(declaration, IREnumDef):
        return set()
    return {value.name for value in declaration.values}


def _provider_keys(names: set[str], providers: dict[str, set[DeclarationKey]]) -> set[DeclarationKey]:
    return {key for name in names for key in providers.get(name, ())}


def _kept[DeclarationT](
    declarations: list[DeclarationT],
    kind: str,
    keep: set[DeclarationKey],
) -> list[DeclarationT]:
    return [declaration for index, declaration in enumerate(declarations) if (kind, index) in keep]


def eliminate_dead_externs(module: IRModule) -> None:
    """Drop unreferenced external function declarations."""
    defined = {function.name for function in module.function_defs}
    declaration_by_name = {
        declaration.name: declaration for declaration in module.function_decls if declaration.name not in defined
    }
    if not declaration_by_name:
        return

    names = set(declaration_by_name)
    pattern = identifier_pattern(names)
    referenced: set[str] = set()
    for root in (*module.function_defs, *module.global_decls):
        collect_callable_references(root, names, referenced)
    scan_macro_replacements(module.preprocessor_decls, pattern, referenced)
    for helper in module.helper_decls:
        scan_text(helper.c_source, pattern, referenced)

    dead_names = {name for name in declaration_by_name if name not in referenced}
    module.function_decls = [declaration for declaration in module.function_decls if declaration.name not in dead_names]
