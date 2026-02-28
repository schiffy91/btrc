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
from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    Block,
    ClassDecl,
    ElseBlock,
    ElseIf,
    FunctionDecl,
    FieldDecl,
    ForInitVar,
    MethodDecl,
    PropertyDecl,
    StructDecl,
    EnumDecl,
    TypedefDecl,
    Param,
    VarDeclStmt,
    ForInStmt,
    CForStmt,
    ParallelForStmt,
    TryCatchStmt,
    IfStmt,
    WhileStmt,
    DoWhileStmt,
    SwitchStmt,
    CaseClause,
    Program,
)

from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import (
    find_token_at_position,
    find_token_index,
    body_range,
    find_enclosing_class,
    resolve_variable_type,
    resolve_chain_type,
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


class DefinitionMap:
    """Maps symbol names to their definition locations."""

    def __init__(self):
        self.class_defs: dict[str, tuple[int, int]] = {}
        self.function_defs: dict[str, tuple[int, int]] = {}
        self.method_defs: dict[tuple[str, str], tuple[int, int]] = {}
        self.field_defs: dict[tuple[str, str], tuple[int, int]] = {}
        self.property_defs: dict[tuple[str, str], tuple[int, int]] = {}
        self.enum_defs: dict[str, tuple[int, int]] = {}
        self.struct_defs: dict[str, tuple[int, int]] = {}
        self.typedef_defs: dict[str, tuple[int, int]] = {}
        self.var_defs: list[VarDef] = []

    @classmethod
    def from_ast(cls, ast: Program) -> DefinitionMap:
        """Walk the AST to build a definition map."""
        dmap = cls()
        for decl in ast.declarations:
            if isinstance(decl, ClassDecl):
                dmap.class_defs[decl.name] = (decl.line, decl.col)
                _collect_class_members(dmap, decl)
            elif isinstance(decl, FunctionDecl):
                dmap.function_defs[decl.name] = (decl.line, decl.col)
                scope_start, scope_end = body_range(decl.body, decl.line)
                _collect_params(dmap, decl.params, scope_start, scope_end)
                if decl.body:
                    _collect_vars_in_block(dmap, decl.body, scope_start, scope_end)
            elif isinstance(decl, EnumDecl):
                dmap.enum_defs[decl.name] = (decl.line, decl.col)
            elif isinstance(decl, StructDecl):
                dmap.struct_defs[decl.name] = (decl.line, decl.col)
            elif isinstance(decl, TypedefDecl):
                dmap.typedef_defs[decl.alias] = (decl.line, decl.col)
        return dmap

    def find_var(self, name: str, cursor_line: int) -> Optional[tuple[int, int]]:
        """Find the closest variable definition for *name* visible at *cursor_line*."""
        best: Optional[VarDef] = None
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


def _collect_class_members(dmap: DefinitionMap, cls: ClassDecl):
    """Collect all member definitions from a class declaration."""
    for member in cls.members:
        if isinstance(member, FieldDecl):
            dmap.field_defs[(cls.name, member.name)] = (member.line, member.col)
        elif isinstance(member, MethodDecl):
            dmap.method_defs[(cls.name, member.name)] = (member.line, member.col)
            scope_start, scope_end = body_range(member.body, member.line)
            _collect_params(dmap, member.params, scope_start, scope_end)
            if member.body:
                _collect_vars_in_block(dmap, member.body, scope_start, scope_end)
        elif isinstance(member, PropertyDecl):
            dmap.property_defs[(cls.name, member.name)] = (member.line, member.col)


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


def _btrc_to_lsp_position(line: int, col: int) -> lsp.Position:
    """Convert 1-based btrc line/col to 0-based LSP position."""
    return lsp.Position(line=max(0, line - 1), character=max(0, col - 1))


def get_definition(
    result: AnalysisResult,
    position: lsp.Position,
) -> Optional[lsp.Location]:
    """Return the definition location for the symbol at the given position."""
    if not result.tokens or not result.ast:
        return None

    token = find_token_at_position(result.tokens, position)
    if token is None or token.type != TokenType.IDENT:
        return None

    class_table = result.analyzed.class_table if result.analyzed else {}
    dmap = DefinitionMap.from_ast(result.ast)
    cursor_line = token.line  # 1-based

    # 1. Member access: obj.member / obj->member / obj?.member
    loc = _try_member_definition(result, token, class_table, dmap)
    if loc:
        return loc

    # 2. Class name reference
    if token.value in dmap.class_defs:
        def_line, def_col = dmap.class_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 3. Function name reference
    if token.value in dmap.function_defs:
        def_line, def_col = dmap.function_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 4. Enum name reference
    if token.value in dmap.enum_defs:
        def_line, def_col = dmap.enum_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 5. Struct name reference
    if token.value in dmap.struct_defs:
        def_line, def_col = dmap.struct_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 6. Typedef alias reference
    if token.value in dmap.typedef_defs:
        def_line, def_col = dmap.typedef_defs[token.value]
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    # 7. Local variable / parameter / loop variable / catch variable
    var_loc = dmap.find_var(token.value, cursor_line)
    if var_loc:
        def_line, def_col = var_loc
        if token.line != def_line or token.col != def_col:
            return _make_location(result.uri, def_line, def_col, len(token.value))

    return None


def _make_location(uri: str, line: int, col: int, length: int = 0) -> lsp.Location:
    """Create an LSP Location from a btrc 1-based line/col."""
    start = _btrc_to_lsp_position(line, col)
    end = (
        lsp.Position(line=start.line, character=start.character + length)
        if length
        else start
    )
    return lsp.Location(
        uri=uri,
        range=lsp.Range(start=start, end=end),
    )


def _try_member_definition(
    result: AnalysisResult,
    token: Token,
    class_table: dict[str, ClassInfo],
    dmap: DefinitionMap,
) -> Optional[lsp.Location]:
    """Try to resolve a go-to-definition for a member access."""
    if not result.tokens:
        return None

    token_idx = find_token_index(result.tokens, token)
    if token_idx is None or token_idx < 2:
        return None

    prev = result.tokens[token_idx - 1]
    if prev.value not in (".", "->", "?."):
        return None

    member_name = token.value

    target_class = resolve_chain_type(result, result.tokens, token_idx - 2, class_table)

    if target_class is None:
        for cname, cinfo in class_table.items():
            if member_name in cinfo.methods or member_name in cinfo.fields:
                target_class = cname
                break

    if target_class is None:
        return None

    name_len = len(member_name)

    current_class = target_class
    while current_class:
        key = (current_class, member_name)
        if key in dmap.method_defs:
            def_line, def_col = dmap.method_defs[key]
            return _make_location(result.uri, def_line, def_col, name_len)
        if key in dmap.field_defs:
            def_line, def_col = dmap.field_defs[key]
            return _make_location(result.uri, def_line, def_col, name_len)
        if key in dmap.property_defs:
            def_line, def_col = dmap.property_defs[key]
            return _make_location(result.uri, def_line, def_col, name_len)

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
) -> Optional[str]:
    """Determine the class name of the object referenced by obj_token."""
    if obj_token.value in class_table:
        return obj_token.value
    if obj_token.value == "self":
        return find_enclosing_class(result.ast, obj_token.line)
    if result.ast:
        return resolve_variable_type(obj_token.value, result.ast, class_table)
    return None
