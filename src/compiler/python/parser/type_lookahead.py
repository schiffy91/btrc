"""Non-mutating lookahead for parser type-expression disambiguation."""

from __future__ import annotations

from collections.abc import Sequence

from ..tokens import Token, TokenType

_QUALIFIERS = frozenset(
    {
        TokenType.CONST,
        TokenType.STATIC,
        TokenType.EXTERN,
        TokenType.VOLATILE,
    }
)

_SIMPLE_BASES = frozenset(
    {
        TokenType.VOID,
        TokenType.INT,
        TokenType.FLOAT,
        TokenType.DOUBLE,
        TokenType.CHAR,
        TokenType.BOOL,
        TokenType.STRING,
        TokenType.IDENT,
    }
)

_GENERIC_FOLLOWS = frozenset(
    {
        TokenType.IDENT,
        TokenType.STAR,
        TokenType.LPAREN,
        TokenType.RPAREN,
        TokenType.LBRACKET,
        TokenType.RBRACKET,
        TokenType.COMMA,
        TokenType.GT,
        TokenType.GT_GT,
        TokenType.SEMICOLON,
        TokenType.LBRACE,
        TokenType.EQ,
        TokenType.QUESTION,
        TokenType.FUNCTION,
        TokenType.EOF,
    }
)


def _type(tokens: Sequence[Token], pos: int) -> TokenType:
    if pos < len(tokens):
        return tokens[pos].type
    return TokenType.EOF


def _scan_angle_group(tokens: Sequence[Token], pos: int) -> int | None:
    """Return the position after a balanced ``<...>`` group."""
    if _type(tokens, pos) != TokenType.LT:
        return None
    depth = 1
    pos += 1
    while pos < len(tokens):
        token_type = _type(tokens, pos)
        if token_type == TokenType.LT:
            depth += 1
        elif token_type == TokenType.GT:
            depth -= 1
        elif token_type == TokenType.GT_GT:
            depth -= 2
        elif token_type in (
            TokenType.SEMICOLON,
            TokenType.LBRACE,
            TokenType.RBRACE,
            TokenType.EOF,
        ):
            return None
        pos += 1
        if depth <= 0:
            return pos
    return None


def is_generic_start(tokens: Sequence[Token], pos: int) -> bool:
    """Whether the ``<`` at *pos* is a generic argument list."""
    end = _scan_angle_group(tokens, pos)
    return end is not None and _type(tokens, end) in _GENERIC_FOLLOWS


def _scan_integer_base(tokens: Sequence[Token], pos: int) -> int | None:
    token_type = _type(tokens, pos)
    if token_type in (TokenType.UNSIGNED, TokenType.SIGNED):
        pos += 1
        token_type = _type(tokens, pos)
        if token_type in (TokenType.INT, TokenType.CHAR):
            return pos + 1
        if token_type == TokenType.SHORT:
            pos += 1
            return pos + 1 if _type(tokens, pos) == TokenType.INT else pos
        if token_type == TokenType.LONG:
            pos += 1
            if _type(tokens, pos) == TokenType.LONG:
                pos += 1
            return pos + 1 if _type(tokens, pos) == TokenType.INT else pos
        return pos
    if token_type == TokenType.SHORT:
        pos += 1
        return pos + 1 if _type(tokens, pos) == TokenType.INT else pos
    if token_type == TokenType.LONG:
        pos += 1
        if _type(tokens, pos) == TokenType.DOUBLE:
            return pos + 1
        if _type(tokens, pos) == TokenType.LONG:
            pos += 1
        return pos + 1 if _type(tokens, pos) == TokenType.INT else pos
    return None


def _scan_tuple_type(tokens: Sequence[Token], pos: int) -> int | None:
    if _type(tokens, pos) != TokenType.LPAREN:
        return None
    pos = scan_type_expr(tokens, pos + 1)
    if pos is None or _type(tokens, pos) != TokenType.COMMA:
        return None
    while _type(tokens, pos) == TokenType.COMMA:
        pos = scan_type_expr(tokens, pos + 1)
        if pos is None:
            return None
    if _type(tokens, pos) != TokenType.RPAREN:
        return None
    return pos + 1


def scan_type_expr(tokens: Sequence[Token], pos: int) -> int | None:
    """Return the first token after a type expression, or ``None``.

    This is deliberately a recognizer, not a second parser: declaration, cast,
    lambda, and generic disambiguation all use the same bounded lookahead, while
    :class:`TypesMixin` remains the sole producer of ``TypeExpr`` nodes.
    """
    while _type(tokens, pos) in _QUALIFIERS:
        pos += 1

    base_end = _scan_integer_base(tokens, pos)
    if base_end is not None:
        pos = base_end
    elif _type(tokens, pos) in (TokenType.STRUCT, TokenType.ENUM, TokenType.UNION):
        if _type(tokens, pos + 1) != TokenType.IDENT:
            return None
        pos += 2
    elif _type(tokens, pos) in _SIMPLE_BASES:
        pos += 1
    elif _type(tokens, pos) == TokenType.LPAREN:
        tuple_end = _scan_tuple_type(tokens, pos)
        if tuple_end is None:
            return None
        pos = tuple_end
    else:
        return None

    if _type(tokens, pos) == TokenType.LT and is_generic_start(tokens, pos):
        pos = _scan_angle_group(tokens, pos)
        assert pos is not None
    if _type(tokens, pos) == TokenType.LBRACKET and _type(tokens, pos + 1) == TokenType.RBRACKET:
        pos += 2
    while _type(tokens, pos) == TokenType.STAR:
        pos += 1
    if _type(tokens, pos) == TokenType.QUESTION:
        pos += 1
    return pos


def is_tuple_type_start(tokens: Sequence[Token], pos: int) -> bool:
    """Whether *pos* begins a comma-bearing tuple type."""
    return _scan_tuple_type(tokens, pos) is not None
