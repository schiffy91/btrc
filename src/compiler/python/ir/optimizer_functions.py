"""Function reachability and prototype pruning for IR optimization."""

from __future__ import annotations

import dataclasses

from .nodes import IRCall, IRFunctionRef, IRLiteral, IRModule
from .optimizer_walk import (
    collect_value_references,
    identifier_pattern,
    scan_macro_replacements,
)

_ENTRY_POINTS = frozenset({"main", "btrc_main"})


def eliminate_dead_functions(module: IRModule) -> None:
    """Keep functions and ARC descriptors reachable from executable roots."""
    functions = module.function_defs
    if not functions:
        return

    names = {function.name for function in functions}
    by_name = {function.name: function for function in functions}
    pattern = identifier_pattern(names)
    descriptors = _arc_descriptors(module)
    descriptor_names = set(descriptors)
    roots = names & _ENTRY_POINTS

    scan_macro_replacements(module.preprocessor_decls, pattern, roots)
    descriptor_roots: set[str] = set()
    if descriptor_names:
        scan_macro_replacements(
            module.preprocessor_decls,
            identifier_pattern(descriptor_names),
            descriptor_roots,
        )
    for declaration in module.global_decls:
        if declaration.name in descriptor_names:
            continue
        collect_function_references(declaration, names, roots)
        collect_value_references(
            declaration,
            descriptor_names,
            descriptor_roots,
        )

    keep = set(roots)
    worklist = list(roots)
    kept_descriptors: set[str] = set()
    descriptor_worklist = list(descriptor_roots)
    while worklist or descriptor_worklist:
        references: set[str] = set()
        if descriptor_worklist:
            descriptor_name = descriptor_worklist.pop()
            if descriptor_name in kept_descriptors:
                continue
            kept_descriptors.add(descriptor_name)
            collect_function_references(
                descriptors[descriptor_name],
                names,
                references,
            )
        else:
            function = by_name.get(worklist.pop())
            if function is None or function.body is None:
                continue
            collect_function_references(function.body, names, references)
            discovered_descriptors: set[str] = set()
            collect_value_references(
                function.body,
                descriptor_names,
                discovered_descriptors,
            )
            descriptor_worklist.extend(discovered_descriptors - kept_descriptors)
        for reference in references - keep:
            keep.add(reference)
            worklist.append(reference)

    module.global_decls = [
        declaration
        for declaration in module.global_decls
        if declaration.name not in descriptor_names or declaration.name in kept_descriptors
    ]
    module.function_defs = [function for function in functions if function.name in keep]
    _prune_removed_prototypes(module, names, keep)


def _arc_descriptors(module: IRModule):
    return {
        declaration.name: declaration
        for declaration in module.global_decls
        if str(declaration.c_type) == "const __btrc_arc_type"
    }


def collect_function_references(
    value: object,
    names: set[str],
    out: set[str],
) -> None:
    """Walk IR dataclasses and collect callable references conservatively."""
    if not dataclasses.is_dataclass(value):
        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                collect_function_references(item, names, out)
        elif isinstance(value, dict):
            for item in value.values():
                collect_function_references(item, names, out)
        return

    if isinstance(value, IRCall) and isinstance(value.callee, str) and value.callee in names:
        out.add(value.callee)
    if isinstance(value, IRFunctionRef) and value.name in names:
        out.add(value.name)
    if isinstance(value, IRLiteral):
        return

    for field in dataclasses.fields(value):
        item = getattr(value, field.name)
        if not isinstance(item, str):
            collect_function_references(item, names, out)


def _prune_removed_prototypes(
    module: IRModule,
    names: set[str],
    keep: set[str],
) -> None:
    removed = names - keep
    if not removed:
        return

    module.function_decls = [declaration for declaration in module.function_decls if declaration.name not in removed]
