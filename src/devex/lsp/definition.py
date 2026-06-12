"""Go-to-definition provider for btrc.

Supports jumping to definitions for:
- Class names (in declarations, constructor calls, type annotations, extends clauses)
- Method calls (obj.method() -> method definition in the class)
- Function calls (myFunction() -> function declaration)
- Field access (obj.field -> field declaration in the class)
- Local variables (x -> its VarDeclStmt or for-loop header)
- Function/method parameters (param -> its Param node)
- Enum names, struct names, typedef aliases
- Properties on classes
"""

from __future__ import annotations

from dataclasses import dataclass

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    Block,
    CaseClause,
    CForStmt,
    ClassDecl,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    EnumDecl,
    FieldDecl,
    ForInitVar,
    ForInStmt,
    FunctionDecl,
    IfStmt,
    MethodDecl,
    ParallelForStmt,
    Param,
    PropertyDecl,
    RichEnumDecl,
    StructDecl,
    SwitchStmt,
    TryCatchStmt,
    TypedefDecl,
    VarDeclStmt,
    WhileStmt,
)
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import (
    active_decls,
    body_range,
    find_enclosing_class,
    find_token_at_position,
    find_token_index,
    nav_tokens,
    resolve_chain_type,
    resolve_variable_type,
    result_location,
)

# ---------------------------------------------------------------------------
# Variable definition entry (scope-aware)
# ---------------------------------------------------------------------------


@dataclass
class VarDef:
    """A single variable-like definition with its scope context."""

    name: str
    line: int
    col: int
    scope_start: int  # 1-based line
    scope_end: int  # 1-based line (inclusive)


# ---------------------------------------------------------------------------
# Definition map building
# ---------------------------------------------------------------------------


def _resolve_name_pos(
    tokens: list[Token] | None, line: int, col: int, name: str
) -> tuple[int, int]:
    """Position of the *name* identifier token at or after (line, col).

    A declaration node records the position of its leading keyword or type
    (e.g. ``class``/``int``), but editors expect go-to-definition and find-
    references to operate on the *name*. Scan forward to the first token that
    spells *name*; fall back to the node position when tokens are unavailable.
    """
    if not tokens:
        return (line, col)
    for tok in tokens:
        if (tok.line, tok.col) < (line, col):
            continue
        if tok.value == name:
            return (tok.line, tok.col)
    return (line, col)


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
        name_positions = result.name_positions
        tokens = result.tokens

        def named(node, name: str, file: str | None) -> tuple[str | None, int, int]:
            pos = name_positions.get(id(node))
            if pos is not None:
                return pos
            # No precomputed position (test snippets): scan the document tokens.
            line, col = _resolve_name_pos(tokens, node.line, node.col, name)
            return (file, line, col)

        for decl in result.ast.declarations:
            file = getattr(decl, "source_file", None)
            is_active = file is None or file == result.path
            if isinstance(decl, ClassDecl):
                self.class_defs[decl.name] = named(decl, decl.name, file)
                _collect_class_members(self, decl, file, named, collect_vars=is_active)
            elif isinstance(decl, FunctionDecl):
                self.function_defs[decl.name] = named(decl, decl.name, file)
                if is_active:
                    scope_start, scope_end = body_range(decl.body, decl.line)
                    _collect_params(self, decl.params, scope_start, scope_end)
                    if decl.body:
                        _collect_vars_in_block(self, decl.body, scope_start, scope_end)
            elif isinstance(decl, EnumDecl):
                name_pos = named(decl, decl.name, file)
                self.enum_defs[decl.name] = name_pos
                # Map each value name too, so cmd-clicking a use of a value
                # (e.g. RED) jumps to the enum declaration.
                for v in decl.values:
                    self.enum_defs.setdefault(v.name, name_pos)
            elif isinstance(decl, RichEnumDecl):
                name_pos = named(decl, decl.name, file)
                self.enum_defs[decl.name] = name_pos
                for variant in decl.variants:
                    self.enum_defs.setdefault(variant.name, name_pos)
            elif isinstance(decl, StructDecl):
                self.struct_defs[decl.name] = named(decl, decl.name, file)
            elif isinstance(decl, TypedefDecl):
                self.typedef_defs[decl.alias] = named(decl, decl.alias, file)

    def find_var(self, name: str, cursor_line: int) -> tuple[int, int] | None:
        """Find the closest variable definition for *name* visible at *cursor_line*."""
        best: VarDef | None = None
        for vd in self.var_defs:
            if vd.name != name:
                continue
            if not (vd.scope_start <= cursor_line <= vd.scope_end):
                continue
            if vd.line > cursor_line:
                continue
            if best is None or vd.line > best.line:
                best = vd
        if best:
            return (best.line, best.col)
        return None


def _collect_class_members(
    dmap: DefinitionMap, cls: ClassDecl, file: str | None, named, collect_vars: bool
):
    """Collect all member definitions from a class declaration."""
    for member in cls.members:
        if isinstance(member, FieldDecl):
            dmap.field_defs[(cls.name, member.name)] = named(member, member.name, file)
        elif isinstance(member, MethodDecl):
            dmap.method_defs[(cls.name, member.name)] = named(member, member.name, file)
            if collect_vars:
                scope_start, scope_end = body_range(member.body, member.line)
                _collect_params(dmap, member.params, scope_start, scope_end)
                if member.body:
                    _collect_vars_in_block(dmap, member.body, scope_start, scope_end)
        elif isinstance(member, PropertyDecl):
            dmap.property_defs[(cls.name, member.name)] = named(member, member.name, file)


def _collect_params(
    dmap: DefinitionMap, params: list[Param], scope_start: int, scope_end: int
):
    """Register function/method parameters as variable definitions."""
    for p in params:
        if p.name and p.line:
            dmap.var_defs.append(
                VarDef(
                    name=p.name,
                    line=p.line,
                    col=p.col,
                    scope_start=scope_start,
                    scope_end=scope_end,
                )
            )


def _collect_vars_in_block(
    dmap: DefinitionMap, block: Block, scope_start: int, scope_end: int
):
    """Recursively collect variable declarations within a block."""
    for stmt in block.statements:
        _collect_vars_in_stmt(dmap, stmt, scope_start, scope_end)


def _collect_vars_in_stmt(dmap: DefinitionMap, stmt, scope_start: int, scope_end: int):
    """Collect variable definitions from a single statement."""
    if isinstance(stmt, VarDeclStmt):
        if stmt.name and stmt.line:
            dmap.var_defs.append(
                VarDef(
                    name=stmt.name,
                    line=stmt.line,
                    col=stmt.col,
                    scope_start=scope_start,
                    scope_end=scope_end,
                )
            )
    elif isinstance(stmt, Block):
        # a bare nested block, e.g. a `case` body wrapped in `{ ... }`
        _collect_vars_in_block(dmap, stmt, scope_start, scope_end)
    elif isinstance(stmt, ForInStmt):
        if stmt.var_name and stmt.line:
            dmap.var_defs.append(
                VarDef(
                    name=stmt.var_name,
                    line=stmt.line,
                    col=stmt.col,
                    scope_start=scope_start,
                    scope_end=scope_end,
                )
            )
        if stmt.var_name2 and stmt.line:
            dmap.var_defs.append(
                VarDef(
                    name=stmt.var_name2,
                    line=stmt.line,
                    col=stmt.col,
                    scope_start=scope_start,
                    scope_end=scope_end,
                )
            )
        if stmt.body:
            _collect_vars_in_block(dmap, stmt.body, scope_start, scope_end)
    elif isinstance(stmt, ParallelForStmt):
        if stmt.var_name and stmt.line:
            dmap.var_defs.append(
                VarDef(
                    name=stmt.var_name,
                    line=stmt.line,
                    col=stmt.col,
                    scope_start=scope_start,
                    scope_end=scope_end,
                )
            )
        if stmt.body:
            _collect_vars_in_block(dmap, stmt.body, scope_start, scope_end)
    elif isinstance(stmt, CForStmt):
        if isinstance(stmt.init, ForInitVar):
            var_decl = stmt.init.var_decl
            if isinstance(var_decl, VarDeclStmt) and var_decl.name and var_decl.line:
                dmap.var_defs.append(
                    VarDef(
                        name=var_decl.name,
                        line=var_decl.line,
                        col=var_decl.col,
                        scope_start=scope_start,
                        scope_end=scope_end,
                    )
                )
        if stmt.body:
            _collect_vars_in_block(dmap, stmt.body, scope_start, scope_end)
    elif isinstance(stmt, TryCatchStmt):
        if stmt.catch_var and stmt.line:
            dmap.var_defs.append(
                VarDef(
                    name=stmt.catch_var,
                    line=stmt.line,
                    col=stmt.col,
                    scope_start=scope_start,
                    scope_end=scope_end,
                )
            )
        if stmt.try_block:
            _collect_vars_in_block(dmap, stmt.try_block, scope_start, scope_end)
        if stmt.catch_block:
            _collect_vars_in_block(dmap, stmt.catch_block, scope_start, scope_end)
    elif isinstance(stmt, IfStmt):
        if stmt.then_block:
            _collect_vars_in_block(dmap, stmt.then_block, scope_start, scope_end)
        if isinstance(stmt.else_block, ElseBlock) and stmt.else_block.body:
            _collect_vars_in_block(dmap, stmt.else_block.body, scope_start, scope_end)
        elif isinstance(stmt.else_block, ElseIf) and stmt.else_block.if_stmt:
            _collect_vars_in_stmt(dmap, stmt.else_block.if_stmt, scope_start, scope_end)
    elif isinstance(stmt, (WhileStmt, DoWhileStmt)):
        if stmt.body:
            _collect_vars_in_block(dmap, stmt.body, scope_start, scope_end)
    elif isinstance(stmt, SwitchStmt):
        for case in stmt.cases:
            if isinstance(case, CaseClause):
                for s in case.body:
                    _collect_vars_in_stmt(dmap, s, scope_start, scope_end)


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
    cursor_line = token.line  # 1-based

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

    # 7. Local variable / parameter / loop variable / catch variable
    var_loc = dmap.find_var(token.value, cursor_line)
    if var_loc:
        def_line, def_col = var_loc
        if token.line != def_line or token.col != def_col:
            return result_location(result, def_line, def_col, len(token.value))

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


def _resolve_object_class(
    obj_token: Token,
    result: AnalysisResult,
    class_table: dict[str, ClassInfo],
) -> str | None:
    """Determine the class name of the object referenced by obj_token."""
    if obj_token.value in class_table:
        return obj_token.value
    if obj_token.value == "self":
        return find_enclosing_class(active_decls(result), obj_token.line)
    if result.ast:
        return resolve_variable_type(
            obj_token.value, active_decls(result), class_table, obj_token.line
        )
    return None
