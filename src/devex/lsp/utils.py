"""Shared utility functions for the btrc LSP feature modules.

Centralises token lookup, type resolution, scope helpers, and formatting
that were previously duplicated across completion, hover, definition,
signature_help, and symbols.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    Block,
    CallExpr,
    ClassDecl,
    ElseBlock,
    ElseIf,
    FieldDecl,
    FunctionDecl,
    Identifier,
    MethodDecl,
    NewExpr,
    Program,
    SwitchStmt,
    VarDeclStmt,
)
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.builtins import _MEMBER_TABLES, get_member
from src.devex.lsp.diagnostics import AnalysisResult

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def type_repr(type_expr) -> str:
    """Format a TypeExpr as a string."""
    if type_expr is None:
        return "void"
    return repr(type_expr)


# ---------------------------------------------------------------------------
# Token lookup
# ---------------------------------------------------------------------------


def find_token_at_position(
    tokens: list[Token], position: lsp.Position
) -> Token | None:
    """Find the token that covers the given 0-based LSP position."""
    target_line = position.line + 1
    target_col = position.character + 1

    for tok in tokens:
        if tok.type == TokenType.EOF:
            continue
        if tok.line != target_line:
            continue
        tok_end_col = tok.col + len(tok.value)
        if tok.col <= target_col < tok_end_col:
            return tok
    return None


def document_position_to_resolved(
    result: AnalysisResult,
    position: lsp.Position,
) -> lsp.Position:
    """Map an editor position in the open document to resolved-source space."""
    if not result.source_positions:
        return position

    document_path = _uri_path(result.uri)
    target_line = position.line + 1
    for resolved_index, (source_file, source_line) in enumerate(
        result.source_positions,
        start=1,
    ):
        if source_file == document_path and source_line == target_line:
            return lsp.Position(
                line=resolved_index - 1,
                character=position.character,
            )
    return position


def result_location(
    result: AnalysisResult,
    line: int,
    col: int,
    length: int = 0,
) -> lsp.Location:
    """Create a location, mapping resolved compiler lines to source files."""
    uri = result.uri
    source_line = line
    if result.source_positions and 1 <= line <= len(result.source_positions):
        source_file, original_line = result.source_positions[line - 1]
        uri = Path(source_file).resolve().as_uri()
        source_line = original_line

    start = lsp.Position(line=max(0, source_line - 1), character=max(0, col - 1))
    end = (
        lsp.Position(line=start.line, character=start.character + length)
        if length
        else start
    )
    return lsp.Location(uri=uri, range=lsp.Range(start=start, end=end))


def _uri_path(uri: str) -> str:
    return unquote(urlparse(uri).path)


def find_token_index(tokens: list[Token], token: Token) -> int | None:
    """Find the index of a token in the token list (by identity)."""
    for i, t in enumerate(tokens):
        if t is token:
            return i
    return None


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def get_text_before_cursor(source: str, position: lsp.Position) -> str:
    """Get the text on the current line before the cursor."""
    lines = source.split("\n")
    if 0 <= position.line < len(lines):
        return lines[position.line][: position.character]
    return ""


# ---------------------------------------------------------------------------
# Scope / structure helpers
# ---------------------------------------------------------------------------


def find_closing_brace_line(source_lines: list[str], start_line: int) -> int | None:
    """Find the line of the closing brace matching the first opening brace."""
    depth = 0
    found_open = False
    for i in range(start_line, len(source_lines)):
        for ch in source_lines[i]:
            if ch == "{":
                depth += 1
                found_open = True
            elif ch == "}":
                depth -= 1
                if found_open and depth == 0:
                    return i
    return None


def body_range(body: Block | None, fallback_start: int) -> tuple[int, int]:
    """Compute the line range [start, end] of a Block node."""
    if not body or not body.statements:
        return (fallback_start, fallback_start + 1000)
    start = body.line if body.line else fallback_start
    end = start
    for stmt in body.statements:
        line = _deepest_line(stmt)
        if line > end:
            end = line
    return (start, end + 50)


def _deepest_line(node) -> int:
    """Find the deepest (highest line number) reachable from a node."""
    best = getattr(node, "line", 0)
    for attr in (
        "body",
        "then_block",
        "else_block",
        "try_block",
        "catch_block",
        "getter_body",
        "setter_body",
    ):
        child = getattr(node, attr, None)
        if child is not None:
            # Unwrap ASDL wrapper types for else_block
            if isinstance(child, ElseBlock) and child.body:
                child = child.body
            elif isinstance(child, ElseIf) and child.if_stmt:
                child = child.if_stmt
            child_line = _deepest_line(child)
            if child_line > best:
                best = child_line
    if isinstance(node, Block):
        for stmt in node.statements:
            child_line = _deepest_line(stmt)
            if child_line > best:
                best = child_line
    if isinstance(node, SwitchStmt):
        for case in node.cases:
            for stmt in case.body:
                child_line = _deepest_line(stmt)
                if child_line > best:
                    best = child_line
    return best


def find_enclosing_class(ast: Program, line: int) -> str | None:
    """Find which class declaration encloses the given 1-based line number."""
    if not ast:
        return None
    for decl in ast.declarations:
        if isinstance(decl, ClassDecl):
            if decl.line <= line:
                max_line = decl.line
                for member in decl.members:
                    if hasattr(member, "line") and member.line > max_line:
                        max_line = member.line
                    if isinstance(member, MethodDecl) and member.body:
                        for stmt in member.body.statements:
                            if hasattr(stmt, "line") and stmt.line > max_line:
                                max_line = stmt.line
                if line <= max_line:
                    return decl.name
    return None


def find_enclosing_class_from_source(
    ast: Program,
    source: str,
    cursor_line: int,
) -> str | None:
    """Find the class enclosing the given 0-based cursor line using brace scanning."""
    if not ast:
        return None
    source_lines = source.split("\n")
    for decl in ast.declarations:
        if isinstance(decl, ClassDecl):
            class_start = decl.line - 1  # to 0-based
            class_end = find_closing_brace_line(source_lines, class_start)
            if class_end is not None and class_start <= cursor_line <= class_end:
                return decl.name
    return None


# ---------------------------------------------------------------------------
# Variable type resolution
# ---------------------------------------------------------------------------

# Primitive types + auto-discovered types from _MEMBER_TABLES
_PRIMITIVE_TYPES = frozenset({
    "int", "float", "double", "long", "short",
    "char", "bool", "void", "unsigned",
})
BUILTIN_TYPES = _PRIMITIVE_TYPES | frozenset(_MEMBER_TABLES.keys())


def resolve_variable_type(
    name: str,
    ast: Program,
    class_table: dict[str, ClassInfo],
) -> str | None:
    """Determine the class/type name for a variable by scanning the AST.

    Looks at VarDeclStmt nodes to find declarations like:
        var x = ClassName(...)          -> ClassName
        var x = new ClassName(...)      -> ClassName
        ClassName x = ...               -> ClassName
    """
    for decl in ast.declarations:
        result = _scan_for_var_type(name, decl, class_table)
        if result:
            return result
    return None


def _scan_for_var_type(
    var_name: str,
    node,
    class_table: dict[str, ClassInfo],
) -> str | None:
    """Recursively scan AST nodes for a VarDeclStmt that declares var_name."""
    if isinstance(node, VarDeclStmt):
        if node.name == var_name:
            if node.type and (
                node.type.base in class_table or node.type.base in BUILTIN_TYPES
            ):
                return node.type.base
            if isinstance(node.initializer, CallExpr):
                callee = node.initializer.callee
                if isinstance(callee, Identifier) and callee.name in class_table:
                    return callee.name
            if isinstance(node.initializer, NewExpr):
                if node.initializer.type and (
                    node.initializer.type.base in class_table
                    or node.initializer.type.base in BUILTIN_TYPES
                ):
                    return node.initializer.type.base
        return None

    if isinstance(node, ClassDecl):
        for member in node.members:
            result = _scan_for_var_type(var_name, member, class_table)
            if result:
                return result
    elif isinstance(node, (FunctionDecl, MethodDecl)):
        for p in node.params:
            if p.name == var_name and p.type:
                if p.type.base in class_table or p.type.base in BUILTIN_TYPES:
                    return p.type.base
        if node.body:
            for stmt in node.body.statements:
                result = _scan_for_var_type(var_name, stmt, class_table)
                if result:
                    return result
    elif hasattr(node, "then_block") or hasattr(node, "body"):
        for attr_name in (
            "then_block",
            "else_block",
            "body",
            "try_block",
            "catch_block",
        ):
            child = getattr(node, attr_name, None)
            if child is None:
                continue
            # Unwrap ASDL wrapper types for else_block
            if isinstance(child, ElseBlock) and child.body:
                child = child.body
            elif isinstance(child, ElseIf) and child.if_stmt:
                result = _scan_for_var_type(var_name, child.if_stmt, class_table)
                if result:
                    return result
                continue
            if hasattr(child, "statements"):
                for stmt in child.statements:
                    result = _scan_for_var_type(var_name, stmt, class_table)
                    if result:
                        return result

    return None


def resolve_chain_type(
    result: AnalysisResult,
    tokens: list[Token],
    end_idx: int,
    class_table: dict[str, ClassInfo],
) -> str | None:
    """Walk backwards through a chained access and resolve the base type.

    ``end_idx`` may point at either an identifier (``obj.field``) or the closing
    paren of a call segment (``obj.method().field``).
    """
    idx = _skip_call_to_callee(tokens, end_idx)
    if idx is None or tokens[idx].type != TokenType.IDENT:
        return None
    chain: list[str] = [tokens[idx].value]

    while idx >= 2:
        prev = tokens[idx - 1]
        if prev.value not in (".", "->", "?."):
            break
        idx -= 2
        skipped = _skip_call_to_callee(tokens, idx)
        if skipped is None or tokens[skipped].type != TokenType.IDENT:
            return None
        idx = skipped
        chain.append(tokens[idx].value)

    chain.reverse()

    root = chain[0]
    current_type: str | None = None

    if root in class_table:
        current_type = root
    elif root == "self" and result.ast:
        current_type = find_enclosing_class(result.ast, tokens[idx].line)
    elif result.ast:
        current_type = resolve_variable_type(root, result.ast, class_table)

    if current_type is None:
        return None

    for member in chain[1:]:
        resolved = resolve_member_type(current_type, member, class_table)
        if resolved is None:
            return None
        current_type = resolved

    return current_type


def _skip_call_to_callee(tokens: list[Token], idx: int) -> int | None:
    """Return the callee token index when *idx* is a call's closing paren."""
    if idx < 0 or idx >= len(tokens):
        return None
    if tokens[idx].value != ")":
        return idx

    depth = 1
    idx -= 1
    while idx >= 0:
        if tokens[idx].value == ")":
            depth += 1
        elif tokens[idx].value == "(":
            depth -= 1
            if depth == 0:
                return idx - 1 if idx > 0 else None
        idx -= 1
    return None


def resolve_member_type(
    owner_type: str,
    member_name: str,
    class_table: dict[str, ClassInfo],
) -> str | None:
    """Resolve the base type of a member access on a given type."""
    cname = owner_type
    while cname and cname in class_table:
        cinfo = class_table[cname]
        if member_name in cinfo.fields:
            fdecl = cinfo.fields[member_name]
            if isinstance(fdecl, FieldDecl) and fdecl.type:
                return fdecl.type.base
        if member_name in cinfo.methods:
            mdecl = cinfo.methods[member_name]
            if isinstance(mdecl, MethodDecl) and mdecl.return_type:
                return mdecl.return_type.base
        cname = cinfo.parent

    # Check built-in type members (string, List, Map, Set, Array, etc.)
    m = get_member(owner_type, member_name)
    if m:
        return m.return_type
    return None
