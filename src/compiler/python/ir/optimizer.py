"""IR optimizer for the btrc compiler.

Currently implements:
- Dead helper elimination: removes runtime helpers not referenced by any function
"""

from __future__ import annotations
from .nodes import (
    IRModule,
    IRHelperDecl,
    IRFunctionDef,
    IRBlock,
    IRStmt,
    IRExpr,
    IRCall,
    IRVarDecl,
    IRAssign,
    IRReturn,
    IRIf,
    IRWhile,
    IRDoWhile,
    IRFor,
    IRSwitch,
    IRExprStmt,
    IRBinOp,
    IRUnaryOp,
    IRFieldAccess,
    IRCast,
    IRTernary,
    IRIndex,
    IRAddressOf,
    IRDeref,
    IRRawC,
    IRStmtExpr,
)


def optimize(module: IRModule) -> IRModule:
    """Run all optimization passes on an IR module."""
    _eliminate_dead_helpers(module)
    return module


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
    from .nodes import IRRawExpr
    for stmt in block.stmts:
        _scan_raw_stmt(stmt, helper_names, used)


def _scan_raw_stmt(stmt, helper_names, used):
    """Scan statement for IRRawExpr/IRRawC references."""
    from .nodes import IRRawExpr
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
    elif isinstance(expr, IRAddressOf):
        _scan_raw_expr(expr.expr, helper_names, used)
    elif isinstance(expr, IRDeref):
        _scan_raw_expr(expr.expr, helper_names, used)
    elif isinstance(expr, IRUnaryOp):
        _scan_raw_expr(expr.operand, helper_names, used)
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
    elif isinstance(expr, IRAddressOf):
        _collect_from_expr(expr.expr, used)
    elif isinstance(expr, IRDeref):
        _collect_from_expr(expr.expr, used)
    elif isinstance(expr, IRStmtExpr):
        for s in expr.stmts:
            _collect_from_stmt(s, used)
        if expr.result:
            _collect_from_expr(expr.result, used)
