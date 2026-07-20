"""Token and degraded-text context detection for signature help."""

from __future__ import annotations

import re

from lsprotocol import types as lsp

from src.compiler.python.lexer import Lexer, LexerError
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.diagnostics import AnalysisResult, line_changed_since_snapshot
from src.devex.lsp.position_utils import nav_tokens, navigation_tokens

_CALLEE_RE = re.compile(r"((?:new\s+)?[A-Za-z_]\w*(?:(?:\.|->|\?\.)[A-Za-z_]\w*)*)\s*$")


def _source_prefix(source: str, position: lsp.Position) -> str | None:
    lines = source.split("\n")
    if position.line < 0 or position.line >= len(lines):
        return None
    return "\n".join(lines[: position.line] + [lines[position.line][: position.character]])


def _mask_literals_and_comments(text: str) -> str:
    """Replace non-code characters with spaces while retaining offsets."""
    chars = list(text)
    index = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    while index < len(chars):
        char = chars[index]
        next_char = chars[index + 1] if index + 1 < len(chars) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
            else:
                chars[index] = " "
            index += 1
            continue
        if block_comment:
            chars[index] = "\n" if char == "\n" else " "
            if char == "*" and next_char == "/":
                chars[index + 1] = " "
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            chars[index] = "\n" if char == "\n" else " "
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and next_char == "/":
            chars[index] = chars[index + 1] = " "
            line_comment = True
            index += 2
        elif char == "/" and next_char == "*":
            chars[index] = chars[index + 1] = " "
            block_comment = True
            index += 2
        elif char in ('"', "'"):
            chars[index] = " "
            quote = char
            index += 1
        else:
            index += 1
    return "".join(chars)


def _unmatched_open_parens(text: str) -> list[int]:
    stack: list[int] = []
    for index, char in enumerate(text):
        if char == "(":
            stack.append(index)
        elif char == ")" and stack:
            stack.pop()
    return stack


def _raw_call(text: str) -> tuple[str, int] | None:
    for open_index in reversed(_unmatched_open_parens(text)):
        match = _CALLEE_RE.search(text[:open_index])
        if match:
            return match.group(1).strip(), open_index
    return None


def _find_call_context(source: str, position: lsp.Position) -> str | None:
    prefix = _source_prefix(source, position)
    if prefix is None:
        return None
    call = _raw_call(_mask_literals_and_comments(prefix))
    return call[0] if call else None


def _count_active_parameter(source: str, position: lsp.Position) -> int:
    """Count argument separators, excluding nested collections and calls."""
    prefix = _source_prefix(source, position)
    if prefix is None:
        return 0
    masked = _mask_literals_and_comments(prefix)
    call = _raw_call(masked)
    if call:
        start = call[1] + 1
    else:
        opens = _unmatched_open_parens(masked)
        start = opens[-1] + 1 if opens else 0

    paren = bracket = brace = commas = 0
    for char in masked[start:]:
        if char == "(":
            paren += 1
        elif char == ")" and paren:
            paren -= 1
        elif char == "[":
            bracket += 1
        elif char == "]" and bracket:
            bracket -= 1
        elif char == "{":
            brace += 1
        elif char == "}" and brace:
            brace -= 1
        elif char == "," and paren == bracket == brace == 0:
            commas += 1
    return commas


def _before_cursor(token: Token, position: lsp.Position) -> bool:
    token_line = token.line - 1
    token_col = token.col - 1
    return token_line < position.line or (token_line == position.line and token_col < position.character)


def _call_site(
    tokens: list[Token] | None,
    position: lsp.Position,
) -> tuple[int, int] | None:
    """Return the innermost unmatched callable (open-paren, callee) indices."""
    if not tokens:
        return None
    stack: list[int] = []
    for index, token in enumerate(tokens):
        if not _before_cursor(token, position):
            continue
        if token.value == "(":
            stack.append(index)
        elif token.value == ")" and stack:
            stack.pop()
    for open_index in reversed(stack):
        callee_index = open_index - 1
        if callee_index >= 0 and tokens[callee_index].type in (
            TokenType.IDENT,
            TokenType.SELF,
        ):
            return open_index, callee_index
    return None


def _active_call_callee_index(
    tokens: list[Token] | None,
    position: lsp.Position,
) -> int | None:
    site = _call_site(tokens, position)
    return site[1] if site else None


def _active_parameter_from_tokens(
    tokens: list[Token],
    open_index: int,
    position: lsp.Position,
) -> int:
    paren = bracket = brace = commas = 0
    for token in tokens[open_index + 1 :]:
        if not _before_cursor(token, position):
            continue
        value = token.value
        if value == "(":
            paren += 1
        elif value == ")" and paren:
            paren -= 1
        elif value == "[":
            bracket += 1
        elif value == "]" and bracket:
            bracket -= 1
        elif value == "{":
            brace += 1
        elif value == "}" and brace:
            brace -= 1
        elif value == "," and paren == bracket == brace == 0:
            commas += 1
    return commas


def _tokens_for_position(
    result: AnalysisResult,
    position: lsp.Position,
) -> list[Token] | None:
    """Use snapshot navigation tokens or re-lex a changed live line."""
    if not line_changed_since_snapshot(result, position.line):
        return nav_tokens(result) if result.tokens is not None else None
    lines = result.source.split("\n")
    if not 0 <= position.line < len(lines):
        return None
    try:
        line_tokens = Lexer(lines[position.line], "<live-line>").tokenize()
    except LexerError:
        return None
    expanded = navigation_tokens([token for token in line_tokens if token.type != TokenType.EOF])
    return [Token(token.type, token.value, position.line + token.line, token.col) for token in expanded]
