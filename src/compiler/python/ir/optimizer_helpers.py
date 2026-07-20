"""Runtime-helper reachability and dependency closure."""

from __future__ import annotations

from .nodes import IRCall, IRFunctionRef, IRModule
from .optimizer_walk import (
    identifier_pattern,
    iter_ir_nodes,
    scan_macro_replacements,
    scan_text,
)


def eliminate_dead_helpers(module: IRModule) -> None:
    """Keep helpers referenced by live IR and their transitive dependencies."""
    if not module.helper_decls:
        return

    helpers_by_name = {helper.name: helper for helper in module.helper_decls}
    names = set(helpers_by_name)
    pattern = identifier_pattern(names)
    # Structured type declarations can depend on a helper-provided ABI without
    # containing a call node (for example the embedded ARC header). Generators
    # record those explicit non-call roots on the module.
    used: set[str] = set(module.runtime_roots) & names

    for root in (*module.function_defs, *module.global_decls):
        _collect_ir_helper_references(root, names, pattern, used)
    scan_macro_replacements(module.preprocessor_decls, pattern, used)

    keep = _dependency_closure(used & names, helpers_by_name, pattern)
    module.helper_decls = [helper for helper in module.helper_decls if helper.name in keep]


def _collect_ir_helper_references(
    root: object,
    names: set[str],
    pattern,
    used: set[str],
) -> None:
    for node in iter_ir_nodes(root):
        if isinstance(node, IRCall):
            if node.helper_ref in names:
                used.add(node.helper_ref)
            if isinstance(node.callee, str) and node.callee in names:
                used.add(node.callee)
        elif isinstance(node, IRFunctionRef) and node.name in names:
            # Runtime callbacks are helper symbols used as values rather than
            # callees (cleanup destructors and Mutex ownership hooks).
            used.add(node.name)


def _dependency_closure(used: set[str], helpers_by_name: dict, pattern) -> set[str]:
    keep = set(used)
    worklist = list(used)
    while worklist:
        helper = helpers_by_name[worklist.pop()]
        dependencies = {dependency for dependency in helper.depends_on if dependency in helpers_by_name}
        scan_text(helper.c_source, pattern, dependencies)
        for dependency in dependencies - keep:
            keep.add(dependency)
            worklist.append(dependency)
    return keep
