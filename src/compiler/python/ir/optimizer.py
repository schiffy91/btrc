"""IR optimizer for the btrc compiler.

Currently implements:
- Dead function elimination: removes functions whose name is never referenced
  (e.g. unused monomorphized generic methods). Sound by construction — a
  function is kept if its name appears anywhere as a call, spawned thread
  function pointer, variable reference, or in any raw/vtable/global text.
- Dead helper elimination: removes runtime helpers not referenced by any function
"""

from __future__ import annotations

import dataclasses

from .nodes import (
    IRAddressOf,
    IRAssign,
    IRBinOp,
    IRBlock,
    IRCall,
    IRCast,
    IRDeref,
    IRDoWhile,
    IRExpr,
    IRExprStmt,
    IRFieldAccess,
    IRFor,
    IRIf,
    IRIndex,
    IRModule,
    IRRawC,
    IRReturn,
    IRSpawnThread,
    IRStmt,
    IRStmtExpr,
    IRSwitch,
    IRTernary,
    IRUnaryOp,
    IRVar,
    IRVarDecl,
    IRWhile,
)


def optimize(module: IRModule) -> IRModule:
    """Run all optimization passes on an IR module."""
    _eliminate_dead_functions(module)
    _eliminate_dead_helpers(module)
    return module


def _eliminate_dead_functions(module: IRModule):
    """Remove function definitions whose name is never referenced.

    Sound by construction: a name is collected as referenced if it appears as a
    call target, a spawned-thread function pointer, a variable, or as a substring
    of any raw/vtable/global/text fragment. `forward_decls` is intentionally NOT
    scanned (it lists every function's prototype). `main` is always kept.
    """
    funcs = module.function_defs
    if len(funcs) <= 1:
        return
    names = {f.name for f in funcs}

    referenced: set[str] = set()
    for func in funcs:
        if func.body:
            _collect_func_refs(func.body, names, referenced)
    for blob in (*module.raw_sections, *module.vtable_defs, *module.global_vars):
        if isinstance(blob, str):
            _scan_text_for_names(blob, names, referenced)

    # `*_visit` / `*_destroy` are per-class ARC lifecycle functions referenced by
    # emitter-generated cycle-collector code (e.g. __btrc_suspect(v, T_visit,
    # T_destroy)) that doesn't exist in the IR yet, so they must never be pruned.
    def _is_root(n):
        return (n == "main" or n == "btrc_main" or n in referenced
                or n.endswith("_visit") or n.endswith("_destroy"))

    keep = {n for n in names if _is_root(n)}
    module.function_defs = [f for f in funcs if f.name in keep]

    # Drop the forward declarations of removed functions too, otherwise a
    # dangling prototype (e.g. `Thread* Foo(...)`) keeps a type alive whose
    # defining helper is then dead-eliminated, leaving an undefined reference.
    removed = names - keep
    if removed:
        needles = tuple(f" {r}(" for r in removed)
        module.forward_decls = [
            fd for fd in module.forward_decls
            if not any(nd in fd for nd in needles)
        ]


def _scan_text_for_names(text: str, names: set[str], out: set[str]):
    """Add any function name that occurs as a substring of `text`."""
    for n in names:
        if n in text:
            out.add(n)


def _collect_func_refs(node, names: set[str], out: set[str]):
    """Generically walk an IR dataclass collecting referenced function names."""
    if not dataclasses.is_dataclass(node):
        return
    if isinstance(node, IRCall) and isinstance(node.callee, str) and node.callee in names:
        out.add(node.callee)
    if isinstance(node, IRSpawnThread) and node.fn_ptr:
        out.add(node.fn_ptr)
    if isinstance(node, IRVar) and node.name in names:
        out.add(node.name)
    for fld in dataclasses.fields(node):
        v = getattr(node, fld.name)
        if isinstance(v, str):
            # `callee`/`text`/literal strings may hold function-pointer exprs or
            # inline C that reference functions indirectly.
            if fld.name in ("callee", "text") or "(" in v:
                _scan_text_for_names(v, names, out)
        elif dataclasses.is_dataclass(v):
            _collect_func_refs(v, names, out)
        elif isinstance(v, list):
            for item in v:
                if dataclasses.is_dataclass(item):
                    _collect_func_refs(item, names, out)
                elif isinstance(item, str):
                    _scan_text_for_names(item, names, out)


def _eliminate_dead_helpers(module: IRModule):
    """Remove runtime helpers that are not referenced by any function body.

    Walks all function bodies to collect helper_ref strings from IRCall nodes,
    then removes IRHelperDecl entries not in the used set (preserving transitive
    category dependencies).
    """
    if not module.helper_decls:
        return

    # Collect all helper names referenced in function bodies
    used_helpers: set[str] = set()
    for func in module.function_defs:
        if func.body:
            _collect_helper_refs(func.body, used_helpers)

    # Also scan raw_sections and raw expressions for helper references
    all_helper_names = {h.name for h in module.helper_decls}
    for section in module.raw_sections:
        for name in all_helper_names:
            if name in section:
                used_helpers.add(name)

    # Scan all function bodies for IRRawExpr text containing helper names
    for func in module.function_defs:
        if func.body:
            _scan_raw_exprs(func.body, all_helper_names, used_helpers)

    if not used_helpers:
        # No helpers used — remove all
        module.helper_decls = []
        return

    # Build category dependency graph
    # category -> set of categories it depends on
    cat_deps: dict[str, set[str]] = {}
    # helper_name -> category
    helper_to_cat: dict[str, str] = {}
    for h in module.helper_decls:
        helper_to_cat[h.name] = h.category
        if h.category not in cat_deps:
            cat_deps[h.category] = set()
        for dep in h.depends_on:
            cat_deps[h.category].add(dep)

    # Find all categories that contain used helpers
    used_cats: set[str] = set()
    for name in used_helpers:
        if name in helper_to_cat:
            used_cats.add(helper_to_cat[name])

    # Transitively resolve category dependencies
    resolved = set()
    worklist = list(used_cats)
    while worklist:
        cat = worklist.pop()
        if cat in resolved:
            continue
        resolved.add(cat)
        for dep in cat_deps.get(cat, set()):
            if dep not in resolved:
                worklist.append(dep)

    # Keep helpers whose name is directly used OR whose category is needed
    module.helper_decls = [
        h for h in module.helper_decls
        if h.name in used_helpers or h.category in resolved
    ]


def _scan_raw_exprs(block: IRBlock, helper_names: set[str], used: set[str]):
    """Scan for helper names in IRRawExpr text within a block."""
    for stmt in block.stmts:
        _scan_raw_stmt(stmt, helper_names, used)


def _scan_raw_stmt(stmt, helper_names, used):
    """Scan statement for IRRawExpr/IRRawC references."""
    if isinstance(stmt, IRRawC):
        # IRRawC text may reference helper globals
        for name in helper_names:
            if name in stmt.text:
                used.add(name)
    elif isinstance(stmt, IRExprStmt):
        _scan_raw_expr(stmt.expr, helper_names, used)
    elif isinstance(stmt, IRVarDecl) and stmt.init:
        _scan_raw_expr(stmt.init, helper_names, used)
    elif isinstance(stmt, IRReturn) and stmt.value:
        _scan_raw_expr(stmt.value, helper_names, used)
    elif isinstance(stmt, IRIf):
        _scan_raw_expr(stmt.condition, helper_names, used)
        if stmt.then_block:
            _scan_raw_exprs(stmt.then_block, helper_names, used)
        if stmt.else_block:
            _scan_raw_exprs(stmt.else_block, helper_names, used)
    elif isinstance(stmt, IRAssign):
        if stmt.target:
            _scan_raw_expr(stmt.target, helper_names, used)
        if stmt.value:
            _scan_raw_expr(stmt.value, helper_names, used)
    elif isinstance(stmt, (IRWhile, IRDoWhile)):
        if stmt.condition:
            _scan_raw_expr(stmt.condition, helper_names, used)
        if stmt.body:
            _scan_raw_exprs(stmt.body, helper_names, used)
    elif isinstance(stmt, IRSwitch):
        if stmt.value:
            _scan_raw_expr(stmt.value, helper_names, used)
        for case in stmt.cases:
            for s in case.body:
                _scan_raw_stmt(s, helper_names, used)
    elif isinstance(stmt, IRFor):
        if stmt.init:
            _scan_raw_stmt(stmt.init, helper_names, used)
        if stmt.condition:
            _scan_raw_expr(stmt.condition, helper_names, used)
        if stmt.update:
            _scan_raw_expr(stmt.update, helper_names, used)
        if stmt.body:
            _scan_raw_exprs(stmt.body, helper_names, used)


def _scan_raw_expr(expr, helper_names, used):
    """Scan expression for IRRawExpr references."""
    from .nodes import IRRawExpr
    if expr is None:
        return
    if isinstance(expr, IRRawExpr):
        for name in helper_names:
            if name in expr.text:
                used.add(name)
    elif isinstance(expr, IRCall):
        if expr.callee in helper_names:
            used.add(expr.callee)
        for arg in expr.args:
            _scan_raw_expr(arg, helper_names, used)
    elif isinstance(expr, IRBinOp):
        _scan_raw_expr(expr.left, helper_names, used)
        _scan_raw_expr(expr.right, helper_names, used)
    elif isinstance(expr, IRTernary):
        _scan_raw_expr(expr.condition, helper_names, used)
        _scan_raw_expr(expr.true_expr, helper_names, used)
        _scan_raw_expr(expr.false_expr, helper_names, used)
    elif isinstance(expr, IRCast):
        _scan_raw_expr(expr.expr, helper_names, used)
    elif isinstance(expr, IRFieldAccess):
        _scan_raw_expr(expr.obj, helper_names, used)
    elif isinstance(expr, IRIndex):
        _scan_raw_expr(expr.obj, helper_names, used)
        _scan_raw_expr(expr.index, helper_names, used)
    elif isinstance(expr, (IRAddressOf, IRDeref)):
        _scan_raw_expr(expr.expr, helper_names, used)
    elif isinstance(expr, IRUnaryOp):
        _scan_raw_expr(expr.operand, helper_names, used)
    elif isinstance(expr, IRSpawnThread):
        used.add("__btrc_thread_spawn")
        if expr.capture_arg:
            _scan_raw_expr(expr.capture_arg, helper_names, used)
    elif isinstance(expr, IRStmtExpr):
        for s in expr.stmts:
            _scan_raw_stmt(s, helper_names, used)
        if expr.result:
            _scan_raw_expr(expr.result, helper_names, used)


def _collect_helper_refs(block: IRBlock, used: set[str]):
    """Recursively collect helper_ref strings from IRCall nodes in a block."""
    for stmt in block.stmts:
        _collect_from_stmt(stmt, used)


def _collect_from_stmt(stmt: IRStmt, used: set[str]):
    """Collect helper refs from a single statement."""
    if isinstance(stmt, IRExprStmt):
        _collect_from_expr(stmt.expr, used)
    elif isinstance(stmt, IRVarDecl):
        if stmt.init:
            _collect_from_expr(stmt.init, used)
    elif isinstance(stmt, IRAssign):
        if stmt.target:
            _collect_from_expr(stmt.target, used)
        if stmt.value:
            _collect_from_expr(stmt.value, used)
    elif isinstance(stmt, IRReturn):
        if stmt.value:
            _collect_from_expr(stmt.value, used)
    elif isinstance(stmt, IRIf):
        if stmt.condition:
            _collect_from_expr(stmt.condition, used)
        if stmt.then_block:
            _collect_helper_refs(stmt.then_block, used)
        if stmt.else_block:
            _collect_helper_refs(stmt.else_block, used)
    elif isinstance(stmt, IRWhile):
        if stmt.condition:
            _collect_from_expr(stmt.condition, used)
        if stmt.body:
            _collect_helper_refs(stmt.body, used)
    elif isinstance(stmt, IRDoWhile):
        if stmt.body:
            _collect_helper_refs(stmt.body, used)
        if stmt.condition:
            _collect_from_expr(stmt.condition, used)
    elif isinstance(stmt, IRFor):
        if stmt.init:
            _collect_from_stmt(stmt.init, used)
        if stmt.condition:
            _collect_from_expr(stmt.condition, used)
        if stmt.update:
            _collect_from_expr(stmt.update, used)
        if stmt.body:
            _collect_helper_refs(stmt.body, used)
    elif isinstance(stmt, IRSwitch):
        if stmt.value:
            _collect_from_expr(stmt.value, used)
        for case in stmt.cases:
            if case.value:
                _collect_from_expr(case.value, used)
            for s in case.body:
                _collect_from_stmt(s, used)
    elif isinstance(stmt, IRRawC):
        # Collect explicit helper_refs from tagged IRRawC nodes
        for ref in getattr(stmt, 'helper_refs', []):
            used.add(ref)


def _collect_from_expr(expr: IRExpr, used: set[str]):
    """Collect helper refs from an expression."""
    if expr is None:
        return
    if isinstance(expr, IRCall):
        if expr.helper_ref:
            used.add(expr.helper_ref)
        for arg in expr.args:
            _collect_from_expr(arg, used)
    elif isinstance(expr, IRBinOp):
        _collect_from_expr(expr.left, used)
        _collect_from_expr(expr.right, used)
    elif isinstance(expr, IRUnaryOp):
        _collect_from_expr(expr.operand, used)
    elif isinstance(expr, IRFieldAccess):
        _collect_from_expr(expr.obj, used)
    elif isinstance(expr, IRCast):
        _collect_from_expr(expr.expr, used)
    elif isinstance(expr, IRTernary):
        _collect_from_expr(expr.condition, used)
        _collect_from_expr(expr.true_expr, used)
        _collect_from_expr(expr.false_expr, used)
    elif isinstance(expr, IRIndex):
        _collect_from_expr(expr.obj, used)
        _collect_from_expr(expr.index, used)
    elif isinstance(expr, (IRAddressOf, IRDeref)):
        _collect_from_expr(expr.expr, used)
    elif isinstance(expr, IRSpawnThread):
        used.add("__btrc_thread_spawn")
        if expr.capture_arg:
            _collect_from_expr(expr.capture_arg, used)
    elif isinstance(expr, IRStmtExpr):
        for s in expr.stmts:
            _collect_from_stmt(s, used)
        if expr.result:
            _collect_from_expr(expr.result, used)
