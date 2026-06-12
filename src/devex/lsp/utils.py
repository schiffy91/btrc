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
from src.devex.lsp.builtins import _MEMBER_TABLES, base_type_name, get_member
from src.devex.lsp.diagnostics import AnalysisResult

# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def type_repr(type_expr, class_table: dict[str, ClassInfo] | None = None) -> str:
    """Format a TypeExpr as a string."""
    if type_expr is None:
        return "void"

    base = getattr(type_expr, "base", None) or "void"
    result = base
    generic_args = getattr(type_expr, "generic_args", None) or []
    if generic_args:
        args = ", ".join(type_repr(arg, class_table) for arg in generic_args)
        result += f"<{args}>"
    pointer_depth = getattr(type_expr, "pointer_depth", 0)
    if class_table and base in class_table and pointer_depth == 1:
        pointer_depth = 0
    result += "*" * pointer_depth
    if getattr(type_expr, "is_array", False):
        result += "[]"
    if getattr(type_expr, "is_nullable", False):
        result += "?"
    if getattr(type_expr, "is_const", False):
        result = f"const {result}"
    return result


# ---------------------------------------------------------------------------
# Token lookup
# ---------------------------------------------------------------------------


def find_token_at_position(tokens: list[Token], position: lsp.Position) -> Token | None:
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


def nav_tokens(result: AnalysisResult) -> list[Token]:
    """Per-snapshot cached navigation tokens (f-string expressions expanded)."""
    cached = result._caches.get("nav_tokens")
    if cached is None:
        cached = navigation_tokens(result.tokens or [])
        result._caches["nav_tokens"] = cached
    return cached


def navigation_tokens(tokens: list[Token]) -> list[Token]:
    expanded: list[Token] = []
    for token in tokens:
        if token.type == TokenType.FSTRING_LIT:
            expanded.extend(_fstring_expression_tokens(token))
        expanded.append(token)
    return expanded


def _fstring_expression_tokens(token: Token) -> list[Token]:
    from src.compiler.python.lexer import Lexer, LexerError

    result: list[Token] = []
    content = token.value
    for start, end in _fstring_expression_spans(content):
        expression = content[start:end]
        line_offset = content[:start].count("\n")
        if line_offset == 0:
            base_col = token.col + 2 + start
        else:
            base_col = len(content[:start].rsplit("\n", 1)[-1]) + 1
        try:
            inner_tokens = Lexer(expression, "<fstring>").tokenize()
        except LexerError:
            continue
        for inner in inner_tokens:
            if inner.type == TokenType.EOF:
                continue
            result.append(
                Token(
                    inner.type,
                    inner.value,
                    token.line + line_offset + inner.line - 1,
                    base_col + inner.col - 1 if inner.line == 1 else inner.col,
                )
            )
    return result


def _fstring_expression_spans(content: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(content):
        if content[i] == "{" and not (i + 1 < len(content) and content[i + 1] == "{"):
            end = _fstring_expression_end(content, i + 1)
            if end is not None:
                spans.append((i + 1, end))
                i = end + 1
                continue
        if content[i] == "}" and i + 1 < len(content) and content[i + 1] == "}":
            i += 2
        else:
            i += 1
    return spans


def _fstring_expression_end(content: str, start: int) -> int | None:
    depth = 1
    i = start
    quote: str | None = None
    escaped = False
    while i < len(content):
        ch = content[i]
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def document_position_to_resolved(
    result: AnalysisResult,
    position: lsp.Position,
) -> lsp.Position:
    """Identity: all positions are native to their file in the v2 pipeline."""
    return position


def result_location(
    result: AnalysisResult,
    line: int,
    col: int,
    length: int = 0,
    file: str | None = None,
) -> lsp.Location:
    """Create a location; positions are native to *file* (default: the document)."""
    if file and file != result.path:
        uri = Path(file).resolve().as_uri()
    else:
        uri = result.uri
    start = lsp.Position(line=max(0, line - 1), character=max(0, col - 1))
    end = lsp.Position(line=start.line, character=start.character + length) if length else start
    return lsp.Location(uri=uri, range=lsp.Range(start=start, end=end))


def active_decls(result: AnalysisResult) -> list:
    """Top-level decls belonging to the active document.

    Decls without ``source_file`` provenance (tests parsing snippets directly)
    are treated as active.
    """
    cached = result._caches.get("active_decls")
    if cached is not None:
        return cached
    if not result.ast:
        return []
    decls = [
        d
        for d in result.ast.declarations
        if getattr(d, "source_file", None) in (None, result.path)
    ]
    result._caches["active_decls"] = decls
    return decls


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


def _decl_list(ast_or_decls) -> list:
    """Accept either a Program or a plain list of decls."""
    if ast_or_decls is None:
        return []
    if isinstance(ast_or_decls, Program):
        return ast_or_decls.declarations
    return ast_or_decls


def find_enclosing_class(ast: Program | list, line: int) -> str | None:
    """Find which class declaration encloses the given 1-based line number.

    Pass ``active_decls(result)`` rather than the composed program — line
    numbers are only meaningful within a single file.
    """
    decls = _decl_list(ast)
    if not decls:
        return None
    for decl in decls:
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
    ast: Program | list,
    source: str,
    cursor_line: int,
) -> str | None:
    """Find the class enclosing the given 0-based cursor line using brace scanning."""
    decls = _decl_list(ast)
    if not decls:
        return None
    source_lines = source.split("\n")
    for decl in decls:
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
_PRIMITIVE_TYPES = frozenset(
    {
        "int",
        "float",
        "double",
        "long",
        "short",
        "char",
        "bool",
        "void",
        "unsigned",
    }
)
BUILTIN_TYPES = _PRIMITIVE_TYPES | frozenset(_MEMBER_TABLES.keys())


def resolve_variable_type(
    name: str,
    ast: Program | list,
    class_table: dict[str, ClassInfo],
    cursor_line: int | None = None,
) -> str | None:
    """Determine the class/type name for a variable by scanning the AST.

    Pass ``active_decls(result)`` — line filtering is only meaningful within
    one file. Looks at VarDeclStmt nodes to find declarations like:
        var x = ClassName(...)          -> ClassName
        var x = new ClassName(...)      -> ClassName
        ClassName x = ...               -> ClassName
    """
    candidates: list[tuple[int, str]] = []
    for decl in _decl_list(ast):
        _scan_for_var_types(name, decl, class_table, candidates)
    if cursor_line is not None:
        candidates = [(line, type_name) for line, type_name in candidates if line <= cursor_line]
    if not candidates:
        return None
    return max(candidates, key=lambda candidate: candidate[0])[1]


def _scan_for_var_types(
    var_name: str,
    node,
    class_table: dict[str, ClassInfo],
    candidates: list[tuple[int, str]],
) -> None:
    """Recursively scan AST nodes for a VarDeclStmt that declares var_name."""
    if isinstance(node, VarDeclStmt):
        if node.name == var_name:
            type_name = _var_decl_type(node, class_table)
            if type_name:
                candidates.append((node.line, type_name))
        return

    if isinstance(node, ClassDecl):
        for member in node.members:
            _scan_for_var_types(var_name, member, class_table, candidates)
    elif isinstance(node, (FunctionDecl, MethodDecl)):
        for p in node.params:
            if p.name == var_name and p.type:
                if p.type.base in class_table or p.type.base in BUILTIN_TYPES:
                    candidates.append((p.line, p.type.base))
        if node.body:
            for stmt in node.body.statements:
                _scan_for_var_types(var_name, stmt, class_table, candidates)
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
                _scan_for_var_types(var_name, child.if_stmt, class_table, candidates)
                continue
            if hasattr(child, "statements"):
                for stmt in child.statements:
                    _scan_for_var_types(var_name, stmt, class_table, candidates)


def _var_decl_type(node: VarDeclStmt, class_table: dict[str, ClassInfo]) -> str | None:
    if node.type and (node.type.base in class_table or node.type.base in BUILTIN_TYPES):
        return node.type.base
    if isinstance(node.initializer, CallExpr):
        callee = node.initializer.callee
        if isinstance(callee, Identifier) and callee.name in class_table:
            return callee.name
    if isinstance(node.initializer, NewExpr):
        if node.initializer.type and (
            node.initializer.type.base in class_table or node.initializer.type.base in BUILTIN_TYPES
        ):
            return node.initializer.type.base
    return None


def resolve_chain_type(
    result: AnalysisResult,
    tokens: list[Token],
    end_idx: int,
    class_table: dict[str, ClassInfo],
    decls: list | None = None,
) -> str | None:
    """Walk backwards through a chained access and resolve the base type.

    ``end_idx`` may point at either an identifier (``obj.field``) or the closing
    paren of a call segment (``obj.method().field``).
    """
    idx, was_call = _chain_segment(tokens, end_idx)
    if idx is None or not _is_chain_identifier(tokens[idx]):
        return None
    chain: list[tuple[str, bool]] = [(tokens[idx].value, was_call)]

    while idx >= 2:
        prev = tokens[idx - 1]
        if prev.value not in (".", "->", "?."):
            break
        idx -= 2
        skipped, was_call = _chain_segment(tokens, idx)
        if skipped is None or not _is_chain_identifier(tokens[skipped]):
            return None
        idx = skipped
        chain.append((tokens[idx].value, was_call))

    chain.reverse()

    root = chain[0][0]
    current_type: str | None = None
    scope_decls = decls if decls is not None else active_decls(result)

    if root in class_table:
        current_type = root
    elif root == "self" and scope_decls:
        current_type = find_enclosing_class(scope_decls, tokens[idx].line)
    elif scope_decls:
        current_type = resolve_variable_type(root, scope_decls, class_table, tokens[idx].line)

    if current_type is None:
        return None

    for member, called in chain[1:]:
        resolved = resolve_member_type(
            current_type,
            member,
            class_table,
            prefer_method=called,
        )
        if resolved is None:
            return None
        current_type = resolved

    return current_type


def _is_chain_identifier(token: Token) -> bool:
    return token.type in (TokenType.IDENT, TokenType.SELF)


def _chain_segment(tokens: list[Token], idx: int) -> tuple[int | None, bool]:
    if idx < 0 or idx >= len(tokens):
        return None, False
    if tokens[idx].value != ")":
        return idx, False
    return _skip_call_to_callee(tokens, idx), True


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
    *,
    prefer_method: bool = False,
) -> str | None:
    """Resolve the base type of a member access on a given type."""
    cname = owner_type
    while cname and cname in class_table:
        cinfo = class_table[cname]
        if prefer_method and member_name in cinfo.methods:
            mdecl = cinfo.methods[member_name]
            if isinstance(mdecl, MethodDecl) and mdecl.return_type:
                return mdecl.return_type.base
        if member_name in cinfo.fields:
            fdecl = cinfo.fields[member_name]
            if isinstance(fdecl, FieldDecl) and fdecl.type:
                return fdecl.type.base
        if not prefer_method and member_name in cinfo.methods:
            mdecl = cinfo.methods[member_name]
            if isinstance(mdecl, MethodDecl) and mdecl.return_type:
                return mdecl.return_type.base
        cname = cinfo.parent

    # Check built-in type members (string, List, Map, Set, Array, etc.)
    m = get_member(owner_type, member_name)
    if m:
        return base_type_name(m.return_type)
    return None
