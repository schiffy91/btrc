"""Shared utility functions for the btrc LSP feature modules.

Centralises token lookup, type resolution, scope helpers, and formatting
that were previously duplicated across completion, hover, definition,
signature_help, and symbols.
"""

from __future__ import annotations

from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.ast_nodes import (
    Block,
    ClassDecl,
    ElseBlock,
    ElseIf,
    FieldDecl,
    ForInitVar,
    FunctionDecl,
    MethodDecl,
    VarDeclStmt,
    SwitchStmt,
    CallExpr,
    Identifier,
    NewExpr,
    Program,
)

from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.builtins import _MEMBER_TABLES, get_member


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
) -> Optional[Token]:
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


def find_token_index(tokens: list[Token], token: Token) -> Optional[int]:
    """Find the index of a token in the token list (by identity)."""
    for i, t in enumerate(tokens):
        if t is token:
            return i
    return None


def find_token_before_position(
    tokens: list[Token], position: lsp.Position
) -> Optional[Token]:
    """Find the last token before the given 0-based LSP position."""
    target_line = position.line + 1
    target_col = position.character + 1

    best: Optional[Token] = None
    for tok in tokens:
        if tok.type == TokenType.EOF:
            continue
        if tok.line < target_line or (tok.line == target_line and tok.col < target_col):
            best = tok
    return best


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def get_text_before_cursor(source: str, position: lsp.Position) -> str:
    """Get the text on the current line before the cursor."""
    lines = source.split("\n")
    if 0 <= position.line < len(lines):
        return lines[position.line][: position.character]
    return ""


def get_line_text(source: str, line: int) -> str:
    """Get the text of a specific 0-based line."""
    lines = source.split("\n")
    if 0 <= line < len(lines):
        return lines[line]
    return ""


# ---------------------------------------------------------------------------
# Scope / structure helpers
# ---------------------------------------------------------------------------


def find_closing_brace_line(source_lines: list[str], start_line: int) -> Optional[int]:
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


def body_range(body: Optional[Block], fallback_start: int) -> tuple[int, int]:
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


def find_enclosing_class(ast: Program, line: int) -> Optional[str]:
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
) -> Optional[str]:
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
) -> Optional[str]:
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
) -> Optional[str]:
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
) -> Optional[str]:
    """Walk backwards through a chained access (a.b.c) and resolve the base type."""
    idx = end_idx
    chain: list[str] = [tokens[idx].value]

    while idx >= 2:
        prev = tokens[idx - 1]
        if prev.value not in (".", "->", "?."):
            break
        idx -= 2
        chain.append(tokens[idx].value)

    chain.reverse()

    root = chain[0]
    current_type: Optional[str] = None

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


def resolve_member_type(
    owner_type: str,
    member_name: str,
    class_table: dict[str, ClassInfo],
) -> Optional[str]:
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
