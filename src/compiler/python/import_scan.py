"""Locate import / btrc-include directives in a source file via the lexer.

Tokenizing first is what kills comment-blindness: ``/* import std.x; */``
produces no tokens, and ``int import`` is a syntax error rather than a silent
include. The front-end (and the stdlib composer) use ``scan_directives`` to
decide which line ranges to replace with imported declarations, instead of the
old raw-line regex that matched imports inside comments and strings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .lexer import Lexer
from .tokens import Token, TokenType

# A C-preprocessor `#include "X.btrc"` is the deprecated alias for a relative
# btrc import. `#include <...>` and `#include "....h"` are real C includes and
# pass through untouched. This regex only inspects the text of a PREPROCESSOR
# token (already isolated by the lexer), never raw source lines, so it can
# never fire inside a comment or string.
CINCLUDE_BTRC_RE = re.compile(r'^\s*#include\s+[<"]([^>"]+\.btrc)[>"]\s*$')


@dataclass
class Directive:
    """An import/include directive located in a source file by the lexer.

    ``kind`` is "import" (``payload`` is an ImportDecl spec node) or
    "btrc_include" (``payload`` is the quoted-include path string). ``start``
    and ``end`` are the 1-based line range the directive occupies; those lines
    are removed from the resolved output and replaced by the imported content.
    """

    kind: str
    payload: object
    start: int
    end: int


def scan_directives(source: str) -> list[Directive]:
    """Find import / btrc-include directives via the lexer (comment-aware).

    Each ``import`` keyword token is followed by its spec (parsed with the real
    grammar) and an optional ``;``; a ``#include "X.btrc"`` preprocessor token is
    recorded as a relative import.

    Only directives that own their whole line(s) — the keyword first on its
    start line, the terminator last on its end line — are treated as directives;
    anything sharing a line with other code is left for the main parse to reject.
    """
    from .parser.parser import Parser

    try:
        tokens = Lexer(source).tokenize()
    except Exception:
        return []  # malformed source: let the main lex/parse report it

    # Per line, the first and last token, so we can require directives to own
    # their whole line(s).
    first_on_line: dict[int, Token] = {}
    last_on_line: dict[int, Token] = {}
    for tok in tokens:
        if tok.type == TokenType.EOF:
            continue
        first_on_line.setdefault(tok.line, tok)
        last_on_line[tok.line] = tok

    directives: list[Directive] = []
    i, n = 0, len(tokens)
    while i < n:
        tok = tokens[i]
        if tok.type == TokenType.IMPORT and first_on_line.get(tok.line) is tok:
            spec, j = _parse_spec_tokens(tokens, i + 1, Parser)
            if spec is None:
                i += 1
                continue
            end_tok = tokens[j - 1]
            if last_on_line.get(end_tok.line) is end_tok:
                directives.append(Directive("import", spec, tok.line, end_tok.line))
            i = j
            continue
        if tok.type == TokenType.PREPROCESSOR and first_on_line.get(tok.line) is tok:
            m = CINCLUDE_BTRC_RE.match(tok.value)
            if m and last_on_line.get(tok.line) is tok:
                directives.append(Directive("btrc_include", m.group(1), tok.line, tok.line))
        i += 1
    return directives


def _parse_spec_tokens(tokens: list[Token], start: int, parser_cls):
    """Parse an import spec beginning at ``tokens[start]``; return (spec, next).

    Returns ``(None, start)`` if the spec is malformed (the main parse will then
    surface the real error). ``next`` is the index just past the spec and its
    optional trailing ``;``.
    """
    sub = list(tokens[start:])
    sub.append(Token(TokenType.EOF, "", 0, 0))
    parser = parser_cls(sub)
    try:
        spec = parser._parse_import_spec()
    except Exception:
        return None, start
    parser._match(TokenType.SEMICOLON)  # optional terminator
    return spec, start + parser.pos
