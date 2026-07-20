"""Reachability pruning for file-scope value declarations."""

from __future__ import annotations

from .expr_nodes import IRCall, IRStmtExpr, IRUnaryOp
from .nodes import IRGlobalDecl, IRModule
from .optimizer_walk import (
    collect_callable_references,
    collect_value_references,
    identifier_pattern,
    iter_ir_nodes,
    scan_macro_replacements,
)

_ENTRY_POINTS = frozenset({"main", "btrc_main"})
_MUTATING_UNARY_OPERATORS = frozenset({"++", "--"})


def eliminate_dead_globals(module: IRModule) -> None:
    """Drop internal globals outside the live top-level value graph.

    Functions and globals form one reachability graph.  This pass computes that
    graph before function DCE so an otherwise dead function and global cannot
    keep each other alive.  Runtime helpers are deliberately absent: registry
    C is emitted before module globals and therefore cannot name an internal
    ``IRGlobalDecl``; helper-owned state lives inside the helper source itself.
    """
    if not module.global_decls:
        return

    functions = {function.name: function for function in module.function_defs}
    globals_by_name: dict[str, list[IRGlobalDecl]] = {}
    for declaration in module.global_decls:
        globals_by_name.setdefault(declaration.name, []).append(declaration)
    function_names = set(functions)
    global_names = set(globals_by_name)
    function_pattern = identifier_pattern(function_names)
    global_pattern = identifier_pattern(global_names)

    live_functions = function_names & _ENTRY_POINTS
    live_globals = {
        name
        for name, declarations in globals_by_name.items()
        if any(_is_global_root(declaration) for declaration in declarations)
    }
    scan_macro_replacements(module.preprocessor_decls, function_pattern, live_functions)
    scan_macro_replacements(module.preprocessor_decls, global_pattern, live_globals)

    worklist = [("function", name) for name in live_functions] + [("global", name) for name in live_globals]
    while worklist:
        kind, name = worklist.pop()
        function_refs: set[str] = set()
        global_refs: set[str] = set()
        if kind == "function":
            _collect_structured_references(
                functions[name].body,
                function_names,
                global_names,
                function_refs,
                global_refs,
            )
        else:
            for declaration in globals_by_name[name]:
                for value in (declaration.init, declaration.array_size):
                    _collect_structured_references(
                        value,
                        function_names,
                        global_names,
                        function_refs,
                        global_refs,
                    )

        _extend_worklist(worklist, "function", function_refs, live_functions)
        _extend_worklist(worklist, "global", global_refs, live_globals)

    module.global_decls = [declaration for declaration in module.global_decls if declaration.name in live_globals]


def _is_global_root(declaration: IRGlobalDecl) -> bool:
    # Volatile changes the semantics of an access, but an unreachable internal
    # object has no access to preserve. External linkage and real references
    # independently root volatile storage that can be observed.
    return bool(
        not declaration.is_static
        or declaration.is_extern
        or _initializer_has_side_effects(declaration.init)
        or _initializer_has_side_effects(declaration.array_size)
    )


def _initializer_has_side_effects(value) -> bool:
    """Conservatively recognize effects in a file-scope initializer."""
    for node in iter_ir_nodes(value):
        if isinstance(node, (IRCall, IRStmtExpr)):
            return True
        if isinstance(node, IRUnaryOp) and node.op in _MUTATING_UNARY_OPERATORS:
            return True
    return False


def _collect_structured_references(
    value,
    function_names: set[str],
    global_names: set[str],
    function_refs: set[str],
    global_refs: set[str],
) -> None:
    collect_callable_references(value, function_names, function_refs)
    collect_value_references(value, global_names, global_refs)
    for node in iter_ir_nodes(value):
        if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in global_names:
            global_refs.add(node.callee)


def _extend_worklist(
    worklist: list[tuple[str, str]],
    kind: str,
    references: set[str],
    live: set[str],
) -> None:
    for reference in references - live:
        live.add(reference)
        worklist.append((kind, reference))


__all__ = ["eliminate_dead_globals"]
