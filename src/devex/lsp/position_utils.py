"""Formatting, token navigation, and document-position helpers for the LSP."""

from __future__ import annotations

from pathlib import Path

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.text_coordinates import protocol_range, source_position


def type_repr(type_expr, class_table: dict[str, ClassInfo] | None = None) -> str:
    """Format a TypeExpr as source-like text."""
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


def _is_wordish(token: Token) -> bool:
    first = token.value[:1]
    return first.isalpha() or first == "_"


def find_token_at_position(
    tokens: list[Token],
    position: lsp.Position,
    source: str | None = None,
) -> Token | None:
    """Find a token at a 0-based LSP position, including a trailing caret."""
    if source is not None:
        position = source_position(source, position)
    target_line = position.line + 1
    target_col = position.character + 1
    containing: Token | None = None
    ending: Token | None = None
    for token in tokens:
        if token.type == TokenType.EOF or token.line != target_line:
            continue
        end_col = token.col + len(token.value)
        if containing is None and token.col <= target_col < end_col:
            containing = token
        if ending is None and end_col == target_col:
            ending = token

    if containing is not None and _is_wordish(containing):
        return containing
    if ending is not None and _is_wordish(ending):
        return ending
    return containing if containing is not None else ending


def nav_tokens(result: AnalysisResult) -> list[Token]:
    """Return cached navigation tokens with f-string expressions expanded."""
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
        base_col = token.col + 2 + start if line_offset == 0 else len(content[:start].rsplit("\n", 1)[-1]) + 1
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
    index = 0
    while index < len(content):
        if content[index] == "{" and not (index + 1 < len(content) and content[index + 1] == "{"):
            end = _fstring_expression_end(content, index + 1)
            if end is not None:
                spans.append((index + 1, end))
                index = end + 1
                continue
        index += 2 if (content[index] == "}" and index + 1 < len(content) and content[index + 1] == "}") else 1
    return spans


def _fstring_expression_end(content: str, start: int) -> int | None:
    depth = 1
    index = start
    quote: str | None = None
    escaped = False
    while index < len(content):
        char = content[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in ('"', "'"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
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
    """Create a location in the active document or an explicitly named file."""
    uri = Path(file).absolute().as_uri() if file and file != result.path else result.uri
    source = source_for_file(result, file)
    return lsp.Location(uri=uri, range=protocol_range(source, line, col, length))


def source_for_file(result: AnalysisResult, file: str | None = None) -> str:
    """Return the analyzed source text for an active or imported location."""
    target = file or result.path
    for unit in result.units:
        if unit.path == target and unit.source:
            return unit.source
    if target == result.path:
        return result.snapshot_source or result.source
    if target:
        try:
            with open(target, encoding="utf-8") as source_file:
                return source_file.read()
        except OSError:
            pass
    return ""


def active_decls(result: AnalysisResult) -> list:
    """Return top-level declarations belonging to the active document."""
    cached = result._caches.get("active_decls")
    if cached is not None:
        return cached
    if not result.ast:
        return []
    decls = [decl for decl in result.ast.declarations if getattr(decl, "source_file", None) in (None, result.path)]
    result._caches["active_decls"] = decls
    return decls


def find_token_index(tokens: list[Token], token: Token) -> int | None:
    for index, candidate in enumerate(tokens):
        if candidate is token:
            return index
    return None


def get_text_before_cursor(source: str, position: lsp.Position) -> str:
    """Return text on the current line before the cursor."""
    lines = source.split("\n")
    if 0 <= position.line < len(lines):
        return lines[position.line][: position.character]
    return ""
