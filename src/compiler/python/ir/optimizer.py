"""IR optimizer for the btrc compiler.

Currently implements:
- Dead function elimination: keeps only functions *reachable* from the program
  roots, via a transitive walk of the call/reference graph. Roots are the entry
  points (`main`/`btrc_main`) and every function named in raw text the emitter
  emits verbatim (cycle-collector tables, vtables, global initializers).
  Reachability — rather than a flat "referenced anywhere" scan — is essential:
  clusters of mutually referencing dead code (e.g. the auto-included stdlib's
  monomorphized collections, whose methods call one another) keep each other
  alive under a flat scan but are correctly pruned when nothing reachable enters
  the cluster. This is what lets a one-line program emit a handful of functions
  instead of the entire stdlib.
- Dead helper elimination: removes runtime helpers not referenced by any function
"""

from __future__ import annotations

import dataclasses
import re

from .nodes import (
    CType,
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


def optimize(module: IRModule, *, dce: bool = True) -> IRModule:
    """Run all optimization passes on an IR module.

    ``dce=False`` disables every dead-code-elimination pass, so the emitted C is
    exactly the uneliminated codegen — used for byte-identical/reproducible
    output (``--no-dce``) and for archive-consumer compiles, where the archive
    (not this TU) is the optimization boundary and ``partition_for_archive``
    removes what the archive already provides.
    """
    if not dce:
        return module
    # The name-regex cache is keyed by set identity; ids can be recycled across
    # calls once a set is GC'd, so start each run with a clean cache.
    _NAME_RE_CACHE.clear()
    _eliminate_dead_functions(module)
    _eliminate_dead_structs(module)
    _eliminate_dead_externs(module)
    _eliminate_dead_helpers(module)
    return module


def _eliminate_dead_functions(module: IRModule):
    """Keep only functions reachable from the program roots.

    A function survives iff it is reachable, through the call/reference graph,
    from a root. Roots are:
      - the entry points `main` / `btrc_main`;
      - every function whose name appears in raw text the emitter emits verbatim
        (`raw_sections`, `vtable_defs`, `global_vars`) — e.g. inheritance vtables
        and the ARC cycle-collector dispatch text reference their target
        functions only by name from these blobs.

    Soundness: each kept function's body is scanned for the names it references
    (call targets, spawned-thread function pointers, variable references, and any
    function name embedded in `callee`/`text`/inline-C fragments — the same
    reference forms the emitter can produce), and those are enqueued. We never
    follow references *out of* dead functions, so a cluster of mutually
    referencing dead code is pruned as a whole. `forward_decls` is intentionally
    NOT treated as a root source (it lists every function's prototype).

    ARC note: per-class `*_destroy` lifecycle functions are NOT blanket roots.
    Every `*_destroy` that can run is referenced from *reachable* code — a scope-
    release / `delete` / field-release `IRCall(callee="X_destroy")`, or the cycle
    collector's `(__btrc_destroy_fn)X_destroy` raw expression embedded in phased
    scope-release — so reachability keeps exactly the ones a run can reach and
    prunes the rest. (`*_visit` functions are emitted into `raw_sections`, not
    `function_defs`, so they are never elimination candidates in the first place.)
    """
    funcs = module.function_defs
    if len(funcs) <= 1:
        return
    names = {f.name for f in funcs}
    by_name = {f.name: f for f in funcs}

    roots: set[str] = set()
    for n in names:
        if n in ("main", "btrc_main"):
            roots.add(n)
    for blob in (*module.raw_sections, *module.vtable_defs, *module.global_vars):
        if isinstance(blob, str) and not _is_prototype_block(blob):
            _scan_text_for_names(blob, names, roots)

    # Transitive reachability via worklist: each kept function is scanned exactly
    # once for the function names it references; newly discovered names are
    # enqueued until the reachable set stabilizes.
    keep: set[str] = set(roots)
    worklist = list(roots)
    while worklist:
        func = by_name.get(worklist.pop())
        if func is None or func.body is None:
            continue
        refs: set[str] = set()
        _collect_func_refs(func.body, names, refs)
        for r in refs:
            if r not in keep:
                keep.add(r)
                worklist.append(r)

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
        # Prototype-only raw sections (the monomorphized-collection forward
        # decls) are NOT roots, so their declared functions can be pruned. Strip
        # the prototypes of removed functions too; otherwise every generic
        # instance's full method set is declared `static` but never defined
        # (a warning, and dead weight that defeats the elimination).
        module.raw_sections = [
            _prune_prototype_block(s, names, keep)
            if isinstance(s, str) and _is_prototype_block(s) else s
            for s in module.raw_sections
        ]
        module.raw_sections = [
            s for s in module.raw_sections
            if not (isinstance(s, str) and not s.strip())
        ]


def _eliminate_dead_structs(module: IRModule):
    """Keep only struct definitions reachable from surviving code.

    Runs after dead-function elimination. A struct survives iff its name appears
    (as a whole identifier) in a surviving function's signature or body, in a
    runtime helper, or in any verbatim blob (raw sections, vtables, globals) —
    plus the embedding closure (a kept struct keeps the struct types of its
    fields). Everything else is unreachable: e.g. for a one-line program the
    auto-included stdlib defines structs like ``CompiledRegex`` (whose field
    type ``regex_t`` would otherwise force ``<regex.h>``) that nothing reaches.

    Conservative by construction — a struct mentioned anywhere live is kept, so
    a false prune cannot happen for code the emitter actually references; only
    genuinely unreferenced definitions are dropped."""
    structs = module.struct_defs
    if len(structs) <= 1:
        return
    struct_names = {s.name for s in structs}
    # Compile a dedicated regex here rather than via the id()-keyed _names_regex
    # cache: the function pass already cached a regex under a now-dead set's id,
    # and a fresh set can reuse that id within the same optimize() call — handing
    # back the WRONG (function-name) regex and pruning every struct.
    rx = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in struct_names) + r")\b")

    refs: set[str] = set()
    for func in module.function_defs:
        _collect_struct_refs(func, rx, refs)
    for helper in module.helper_decls:
        refs.update(rx.findall(helper.c_source))
    for blob in (*module.raw_sections, *module.vtable_defs, *module.global_vars):
        if isinstance(blob, str):
            refs.update(rx.findall(blob))

    # Embedding closure: a kept struct keeps the struct types of its fields.
    by_name = {s.name: s for s in structs}
    keep: set[str] = set(refs)
    worklist = list(refs)
    while worklist:
        s = by_name.get(worklist.pop())
        if s is None:
            continue
        for fld in s.fields:
            for nm in rx.findall(fld.c_type.text):
                if nm not in keep:
                    keep.add(nm)
                    worklist.append(nm)

    if len(keep) == len(struct_names):
        return
    module.struct_defs = [s for s in structs if s.name in keep]

    # Drop forward declarations that name a pruned struct (its `typedef struct X
    # X;` and `void X_destroy(X*);`), otherwise they reference an undefined type.
    removed = struct_names - keep
    rxr = re.compile(r"\b(?:" + "|".join(re.escape(r) for r in removed) + r")\b")
    module.forward_decls = [fd for fd in module.forward_decls if not rxr.search(fd)]


def _collect_struct_refs(node, rx, out: set[str]):
    """Collect struct-type names referenced anywhere in an IR node.

    Walks the dataclass generically: a ``CType`` contributes its text (covering
    function signatures, var-decl types, casts, sizeof operands), and every
    string field is scanned (covering inline-C / raw fragments). ``rx`` is the
    precompiled struct-name regex."""
    if isinstance(node, CType):
        out.update(rx.findall(node.text))
        return
    if not dataclasses.is_dataclass(node):
        return
    for fld in dataclasses.fields(node):
        v = getattr(node, fld.name)
        if isinstance(v, str):
            out.update(rx.findall(v))
        elif dataclasses.is_dataclass(v):
            _collect_struct_refs(v, rx, out)
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, str):
                    out.update(rx.findall(item))
                elif dataclasses.is_dataclass(item):
                    _collect_struct_refs(item, rx, out)


def _eliminate_dead_externs(module: IRModule):
    """Drop extern prototypes (`RET name(params);` in forward_decls with no
    definition in this module) that no surviving code calls.

    The auto-composed stdlib declares libc functions it *might* use (popen,
    forkpty, ...); when the using stdlib code is itself eliminated, the extern is
    dead — pure bloat in hosted builds, and in freestanding builds it drags in
    libc types (FILE, ...) that aren't available. Conservative: an extern named
    anywhere in surviving code is kept."""
    defined = {f.name for f in module.function_defs}
    extern_of = {}   # extern function name -> its forward-decl string
    for fd in module.forward_decls:
        if "typedef" in fd or "(" not in fd:
            continue
        m = re.search(r"\b(\w+)\s*\(", fd)
        if m and m.group(1) not in defined:
            extern_of[m.group(1)] = fd
    if not extern_of:
        return
    rx = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in extern_of) + r")\b")
    referenced: set[str] = set()
    for func in module.function_defs:
        _collect_struct_refs(func, rx, referenced)   # generic: scans text + callees
    for blob in (*module.raw_sections, *module.vtable_defs, *module.global_vars):
        if isinstance(blob, str):
            referenced.update(rx.findall(blob))
    for helper in module.helper_decls:
        referenced.update(rx.findall(helper.c_source))

    dead = {n for n in extern_of if n not in referenced}
    if not dead:
        return
    dead_lines = {extern_of[n] for n in dead}
    module.forward_decls = [fd for fd in module.forward_decls if fd not in dead_lines]


def _is_prototype_block(section: str) -> bool:
    """True for a raw section that is purely forward declarations.

    Such a block declares functions (``static RET name(params);`` ...) but uses
    none — like ``forward_decls``, naming a function here must NOT keep it alive.
    A block with a body (``{``) or an initializer (``=``, e.g. a function-pointer
    table) genuinely references its targets and is scanned for roots as before.
    The generic-collection prototype blocks (Vector_int, Map_string_bool, ...)
    are exactly this shape, and pinning them kept the entire stdlib for even a
    one-line program."""
    return "{" not in section and "=" not in section and "(" in section and ";" in section


def _prune_prototype_block(section: str, names: set[str], keep: set[str]) -> str:
    """Drop the prototypes of eliminated functions from a forward-decl block."""
    import re as _re
    out: list[str] = []
    for part in section.split(";"):
        if not part.strip():
            continue
        m = _re.search(r"(\w+)\s*\(", part)
        if m and m.group(1) in names and m.group(1) not in keep:
            continue
        out.append(part)
    return (";".join(out) + ";") if out else ""


# Cache one compiled word-boundary regex per name set (keyed by object id), so
# the same set is compiled once and reused across every blob/field scan instead
# of re-walking ~1300 names per piece of text.
_NAME_RE_CACHE: dict[int, re.Pattern[str] | None] = {}


def _names_regex(names: set[str]) -> re.Pattern[str] | None:
    """Compile/return a `\\b(?:n1|n2|...)\\b` regex matching whole identifiers."""
    key = id(names)
    cached = _NAME_RE_CACHE.get(key, False)
    if cached is not False:
        return cached
    if not names:
        _NAME_RE_CACHE[key] = None
        return None
    pattern = r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b"
    compiled = re.compile(pattern)
    _NAME_RE_CACHE[key] = compiled
    return compiled


def _scan_text_for_names(text: str, names: set[str], out: set[str]):
    """Add every function name that occurs as a *whole identifier* in `text`.

    Whole-identifier (word-boundary) matching, not substring: `foo` must not
    match inside `foobar`. A substring scan was both unsound in the wrong
    direction (it kept dead code whose name merely appeared inside a live
    identifier) and O(names x text). One precompiled alternation regex makes
    the scan a single pass per text while keeping the conservative guarantee:
    a name referenced as a real identifier is still matched and kept.
    """
    rx = _names_regex(names)
    if rx is None:
        return
    out.update(rx.findall(text))


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

    # Keep helpers whose name is directly used OR whose category is needed.
    keep = {h.name for h in module.helper_decls
            if h.name in used_helpers or h.category in resolved}

    # Transitive closure over helper -> helper references in C source: a kept
    # helper's body often calls other helpers (e.g. __btrc_strcat -> __btrc_strdup),
    # including helpers kept via category resolution rather than direct use. Follow
    # those references so the set is sound no matter how a helper became live and
    # regardless of whether a `depends_on` edge was declared.
    helper_src = {h.name: h.c_source for h in module.helper_decls}
    ref_rx = re.compile(r"\b(?:" + "|".join(re.escape(n) for n in all_helper_names) + r")\b")
    work = list(keep)
    while work:
        for ref in ref_rx.findall(helper_src.get(work.pop(), "")):
            if ref not in keep:
                keep.add(ref)
                work.append(ref)

    module.helper_decls = [h for h in module.helper_decls if h.name in keep]


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
