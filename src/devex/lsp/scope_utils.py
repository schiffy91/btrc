"""AST and token based scope-boundary helpers for the btrc LSP."""

from __future__ import annotations

from src.compiler.python.ast_nodes import (
    Block,
    ClassDecl,
    ElseBlock,
    ElseIf,
    Program,
    SwitchStmt,
)
from src.compiler.python.tokens import Token, TokenType


def find_closing_brace_line(source_lines: list[str], start_line: int) -> int | None:
    """Find a matching closing brace without counting literals or comments."""
    from src.compiler.python.lexer import Lexer, LexerError

    fragment = "\n".join(source_lines[start_line:])
    try:
        tokens = Lexer(fragment, "<lsp-braces>").tokenize()
    except LexerError:
        return _find_closing_brace_line_raw(source_lines, start_line)
    matched = find_matching_brace_line(tokens, 1, 1)
    return start_line + matched - 1 if matched is not None else None


def _find_closing_brace_line_raw(
    source_lines: list[str],
    start_line: int,
) -> int | None:
    """Best-effort fallback for lexically incomplete live text."""
    depth = 0
    found_open = False
    for line_index in range(start_line, len(source_lines)):
        for char in source_lines[line_index]:
            if char == "{":
                depth += 1
                found_open = True
            elif char == "}":
                depth -= 1
                if found_open and depth == 0:
                    return line_index
    return None


def find_matching_brace_line(tokens: list[Token], line: int, col: int) -> int | None:
    """Find the brace-token match at/after a 1-based source position."""
    depth = 0
    opened = False
    for token in tokens:
        if token.line < line or (token.line == line and token.col < col):
            continue
        if token.type == TokenType.LBRACE:
            depth += 1
            opened = True
        elif token.type == TokenType.RBRACE and opened:
            depth -= 1
            if depth == 0:
                return token.line
    return None


def body_range(
    body: Block | None,
    fallback_start: int,
    tokens: list[Token] | None = None,
) -> tuple[int, int]:
    """Compute the inclusive source-line range of a block."""
    start = body.line if body is not None and body.line else fallback_start
    if tokens and body is not None and body.line:
        end = find_matching_brace_line(tokens, body.line, body.col)
        if end is not None:
            return (start, end)
    if not body or not body.statements:
        return (fallback_start, fallback_start + 1000)
    end = max((deepest_line(stmt) for stmt in body.statements), default=start)
    return (start, end + 50)


def deepest_line(node) -> int:
    """Return the greatest source line reachable through control-flow children."""
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
        if child is None:
            continue
        if isinstance(child, ElseBlock) and child.body:
            child = child.body
        elif isinstance(child, ElseIf) and child.if_stmt:
            child = child.if_stmt
        best = max(best, deepest_line(child))
    if isinstance(node, Block):
        best = max((deepest_line(stmt) for stmt in node.statements), default=best)
    if isinstance(node, SwitchStmt):
        for case in node.cases:
            best = max((deepest_line(stmt) for stmt in case.body), default=best)
    return best


def decl_list(ast_or_decls) -> list:
    if ast_or_decls is None:
        return []
    if isinstance(ast_or_decls, Program):
        return ast_or_decls.declarations
    return ast_or_decls


def find_enclosing_class(ast: Program | list, line: int) -> str | None:
    """Find the class whose AST extent contains a 1-based source line."""
    for decl in decl_list(ast):
        if not isinstance(decl, ClassDecl) or decl.line > line:
            continue
        max_line = max((deepest_line(member) for member in decl.members), default=decl.line)
        if line <= max_line:
            return decl.name
    return None


def find_enclosing_class_from_source(
    ast: Program | list,
    source: str,
    cursor_line: int,
) -> str | None:
    """Find an enclosing class using lexical braces, never string braces."""
    declarations = decl_list(ast)
    if not declarations:
        return None

    from src.compiler.python.lexer import Lexer, LexerError

    try:
        tokens = Lexer(source, "<lsp-scope>").tokenize()
    except LexerError:
        tokens = None

    source_lines = source.split("\n")
    for decl in declarations:
        if not isinstance(decl, ClassDecl):
            continue
        class_start = decl.line - 1
        if tokens is not None:
            matched = find_matching_brace_line(tokens, decl.line, decl.col)
            class_end = matched - 1 if matched is not None else None
        else:
            class_end = find_closing_brace_line(source_lines, class_start)
        if class_end is not None and class_start <= cursor_line <= class_end:
            return decl.name
    return None
