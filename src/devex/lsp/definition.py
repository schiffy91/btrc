"""Go-to-definition provider for btrc.

Supports jumping to definitions for:
- Class names (in declarations, constructor calls, type annotations, extends clauses)
- Method calls (obj.method() -> method definition in the class)
- Function calls (myFunction() -> function declaration)
- Field access (obj.field -> field declaration in the class)
- Local variables (x -> its VarDeclStmt or for-loop header), scope-aware
- Function/method parameters (param -> its Param node)
- Enum names, struct names, typedef aliases
- Properties on classes

Variable definitions are collected with REAL block-granular scopes
(src/devex/lsp/var_scopes.py); ``find_var_def`` picks the innermost
definition visible at the cursor, so same-named locals in sibling
functions or shadowed blocks never leak.
"""

from __future__ import annotations

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    ClassDecl,
    EnumDecl,
    FieldDecl,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
)
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.occurrences import occurrence_at
from src.devex.lsp.utils import (
    find_token_at_position,
    find_token_index,
    nav_tokens,
    resolve_chain_type,
    result_location,
)
from src.devex.lsp.var_scopes import VarDef, collect_callable_vars

# ---------------------------------------------------------------------------
# Definition map building
# ---------------------------------------------------------------------------


def _name_pos(node, file: str | None) -> tuple[str | None, int, int]:
    """File-qualified position of *node*'s NAME token.

    Named decls/members carry ``name_line``/``name_col`` pointing at their name
    token (populated by the parser). Read them directly. ``name_line == 0``
    means the field was never populated (a synthetic node), so fall back to the
    node's own ``line``/``col``.
    """
    nl = getattr(node, "name_line", 0)
    if nl:
        return (file, nl, getattr(node, "name_col", 0))
    return (file, getattr(node, "line", 0), getattr(node, "col", 0))


class DefinitionMap:
    """Maps symbol names to their definition locations.

    Entries are file-qualified ``(file, line, col)``; positions are native to
    that file. ``file`` is None for decls without provenance (test snippets).
    Variable definitions are collected from the active document only — line
    ranges are meaningless across files.
    """

    def __init__(self):
        self.class_defs: dict[str, tuple[str | None, int, int]] = {}
        self.function_defs: dict[str, tuple[str | None, int, int]] = {}
        self.method_defs: dict[tuple[str, str], tuple[str | None, int, int]] = {}
        self.field_defs: dict[tuple[str, str], tuple[str | None, int, int]] = {}
        self.property_defs: dict[tuple[str, str], tuple[str | None, int, int]] = {}
        self.enum_defs: dict[str, tuple[str | None, int, int]] = {}
        self.struct_defs: dict[str, tuple[str | None, int, int]] = {}
        self.typedef_defs: dict[str, tuple[str | None, int, int]] = {}
        self.var_defs: list[VarDef] = []

    @classmethod
    def from_result(cls, result: AnalysisResult) -> DefinitionMap:
        """Build (or return the cached) definition map for a snapshot."""
        cached = result._caches.get("dmap")
        if cached is not None:
            return cached
        dmap = cls()
        if result.ast:
            dmap._build(result)
        result._caches["dmap"] = dmap
        return dmap

    def _build(self, result: AnalysisResult):
        tokens = result.tokens

        for decl in result.ast.declarations:
            file = getattr(decl, "source_file", None)
            is_active = file is None or file == result.path
            if isinstance(decl, ClassDecl):
                self.class_defs[decl.name] = _name_pos(decl, file)
                self._collect_class_members(decl, file, tokens, is_active)
            elif isinstance(decl, InterfaceDecl):
                # Interface name navigates like a class; its MethodSig members
                # now carry correct name spans (the span used to be wrong).
                self.class_defs[decl.name] = _name_pos(decl, file)
                for sig in decl.methods:
                    self.method_defs[(decl.name, sig.name)] = _name_pos(sig, file)
            elif isinstance(decl, FunctionDecl):
                self.function_defs[decl.name] = _name_pos(decl, file)
                if is_active:
                    collect_callable_vars(self.var_defs, decl, tokens)
            elif isinstance(decl, EnumDecl):
                self.enum_defs[decl.name] = _name_pos(decl, file)
                # Map each value name to the value's own position, so cmd-
                # clicking a use of a value (e.g. RED) jumps to that variant.
                for v in decl.values:
                    self.enum_defs.setdefault(v.name, _name_pos(v, file))
            elif isinstance(decl, RichEnumDecl):
                self.enum_defs[decl.name] = _name_pos(decl, file)
                for variant in decl.variants:
                    self.enum_defs.setdefault(variant.name, _name_pos(variant, file))
            elif isinstance(decl, StructDecl):
                self.struct_defs[decl.name] = _name_pos(decl, file)
            elif isinstance(decl, TypedefDecl):
                self.typedef_defs[decl.alias] = _name_pos(decl, file)

    def _collect_class_members(
        self, cls: ClassDecl, file: str | None, tokens, collect_vars: bool
    ):
        """Collect all member definitions from a class declaration."""
        for member in cls.members:
            if isinstance(member, FieldDecl):
                self.field_defs[(cls.name, member.name)] = _name_pos(member, file)
            elif isinstance(member, MethodDecl):
                self.method_defs[(cls.name, member.name)] = _name_pos(member, file)
                if collect_vars:
                    collect_callable_vars(self.var_defs, member, tokens, cls.name)
            elif isinstance(member, PropertyDecl):
                self.property_defs[(cls.name, member.name)] = _name_pos(member, file)

    def find_var_def(self, name: str, line: int, col: int) -> VarDef | None:
        """Innermost definition of *name* visible at 1-based (line, col).

        A definition is a candidate when the position is inside its scope and
        at/after the definition site; the definition's own name token always
        matches (so params declared before the body's `{` resolve too).
        Innermost = max scope_start, then latest definition line.
        """
        best: VarDef | None = None
        for vd in self.var_defs:
            if vd.name != name:
                continue
            at_def_site = (vd.line, vd.col) == (line, col)
            in_scope = (
                vd.scope_start <= line <= vd.scope_end
                and (vd.line, vd.col) <= (line, col)
            )
            if not (at_def_site or in_scope):
                continue
            if best is None or (vd.scope_start, vd.line) > (best.scope_start, best.line):
                best = vd
        return best

    def find_var(self, name: str, cursor_line: int) -> tuple[int, int] | None:
        """Thin wrapper over :meth:`find_var_def` returning (line, col)."""
        vd = self.find_var_def(name, cursor_line, 10**9)
        if vd is not None:
            return (vd.line, vd.col)
        return None


# ---------------------------------------------------------------------------
# Main go-to-definition logic
# ---------------------------------------------------------------------------


def get_definition(
    result: AnalysisResult,
    position: lsp.Position,
) -> lsp.Location | None:
    """Return the definition location for the symbol at the given position."""
    if not result.tokens or not result.ast:
        return None

    tokens = nav_tokens(result)
    token = find_token_at_position(tokens, position)
    if token is None or token.type != TokenType.IDENT:
        return None

    class_table = result.analyzed.class_table if result.analyzed else {}
    dmap = DefinitionMap.from_result(result)

    # 0. Exact resolution from the analyzer's occurrence table. When the
    # cursor identifier was resolved by the analyzer, jump straight to its
    # recorded definition site — no token-walking heuristics. Skip when the
    # cursor IS the definition site (resolve-to-self is the heuristic's job).
    occ = occurrence_at(result, position)
    if occ is not None and (occ.def_line or occ.def_file):
        if not _at_def_site(result, token, occ.def_file, occ.def_line, occ.def_col):
            return result_location(
                result, occ.def_line, occ.def_col, len(token.value), file=occ.def_file
            )

    # 1. Member access: obj.member / obj->member / obj?.member
    loc = _try_member_definition(result, tokens, token, class_table, dmap)
    if loc:
        return loc

    # 2-6. Named declarations: class, function, enum, struct, typedef
    for table in (
        dmap.class_defs,
        dmap.function_defs,
        dmap.enum_defs,
        dmap.struct_defs,
        dmap.typedef_defs,
    ):
        if token.value in table:
            def_file, def_line, def_col = table[token.value]
            if not _at_def_site(result, token, def_file, def_line, def_col):
                return result_location(
                    result, def_line, def_col, len(token.value), file=def_file
                )

    # 7. Local variable / parameter / loop variable / catch variable.
    # The definition site resolves to itself (standard editor behavior).
    vd = dmap.find_var_def(token.value, token.line, token.col)
    if vd is not None:
        return result_location(result, vd.line, vd.col, len(token.value))

    return None


def _at_def_site(
    result: AnalysisResult,
    token: Token,
    def_file: str | None,
    def_line: int,
    def_col: int,
) -> bool:
    """True when the cursor token *is* the definition's name token."""
    if def_file is not None and def_file != result.path:
        return False
    return token.line == def_line and token.col == def_col


def _try_member_definition(
    result: AnalysisResult,
    tokens: list[Token],
    token: Token,
    class_table: dict[str, ClassInfo],
    dmap: DefinitionMap,
) -> lsp.Location | None:
    """Try to resolve a go-to-definition for a member access."""
    if not tokens:
        return None

    token_idx = find_token_index(tokens, token)
    if token_idx is None or token_idx < 2:
        return None

    prev = tokens[token_idx - 1]
    if prev.value not in (".", "->", "?."):
        return None

    member_name = token.value

    target_class = resolve_chain_type(result, tokens, token_idx - 2, class_table)
    if target_class is None:
        return None

    name_len = len(member_name)

    current_class = target_class
    while current_class:
        key = (current_class, member_name)
        for table in (dmap.method_defs, dmap.field_defs, dmap.property_defs):
            if key in table:
                def_file, def_line, def_col = table[key]
                return result_location(result, def_line, def_col, name_len, file=def_file)

        cinfo = class_table.get(current_class)
        if cinfo and cinfo.parent and cinfo.parent in class_table:
            current_class = cinfo.parent
        else:
            break

    return None
