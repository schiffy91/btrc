"""Literal tokenization: strings, chars, numbers, f-strings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .tokens import TokenType

if TYPE_CHECKING:
    from .lexer import Lexer


def read_string(lex: Lexer):
    """Read a double-quoted or triple-quoted string literal."""
    from .lexer import LexerError
    line, col = lex.line, lex.col
    lex._advance()  # skip opening "

    # Triple-quoted string: """..."""
    if lex._peek() == '"' and lex._peek(1) == '"':
        lex._advance()  # skip second "
        lex._advance()  # skip third "
        chars: list[str] = []
        while lex.pos < len(lex.source):
            if lex._peek() == '"' and lex._peek(1) == '"' and lex._peek(2) == '"':
                lex._advance()
                lex._advance()
                lex._advance()
                value = '"' + ''.join(chars) + '"'
                lex._emit(TokenType.STRING_LIT, value, line, col)
                return
            ch = lex._advance()
            if ch == '\n':
                chars.append('\\')
                chars.append('n')
            elif ch == '\r':
                chars.append('\\')
                chars.append('n')
                if lex._peek() == '\n':
                    lex._advance()
            elif ch == '\\':
                chars.append(ch)
                if lex.pos < len(lex.source):
                    chars.append(lex._advance())
            else:
                chars.append(ch)
        raise LexerError("Unterminated triple-quoted string", line, col)

    # Regular single-line string
    chars: list[str] = []
    while lex.pos < len(lex.source):
        ch = lex._peek()
        if ch == '"':
            lex._advance()
            value = '"' + ''.join(chars) + '"'
            lex._emit(TokenType.STRING_LIT, value, line, col)
            return
        elif ch == '\\':
            chars.append(lex._advance())
            if lex.pos < len(lex.source):
                chars.append(lex._advance())
        elif ch == '\n':
            raise LexerError("Unterminated string literal", line, col)
        else:
            chars.append(lex._advance())
    raise LexerError("Unterminated string literal", line, col)


def read_char(lex: Lexer):
    """Read a single-quoted char literal."""
    from .lexer import LexerError
    line, col = lex.line, lex.col
    lex._advance()  # skip opening '
    chars: list[str] = []
    while lex.pos < len(lex.source):
        ch = lex._peek()
        if ch == "'":
            lex._advance()
            value = "'" + ''.join(chars) + "'"
            lex._emit(TokenType.CHAR_LIT, value, line, col)
            return
        elif ch == '\\':
            chars.append(lex._advance())
            if lex.pos < len(lex.source):
                chars.append(lex._advance())
        else:
            chars.append(lex._advance())
    raise LexerError("Unterminated character literal", line, col)


def read_number(lex: Lexer):
    """Read an integer or float literal (decimal, hex, binary, octal)."""
    from .lexer import LexerError
    line, col = lex.line, lex.col
    start = lex.pos
    is_float = False

    # Hex prefix: 0x...
    if lex._peek() == '0' and lex._peek(1) in ('x', 'X'):
        lex._advance()  # 0
        lex._advance()  # x
        if not _is_hex_digit(lex._peek()):
            raise LexerError("Invalid hex literal: no digits after '0x'",
                             line, col)
        while lex.pos < len(lex.source) and _is_hex_digit(lex._peek()):
            lex._advance()
        _consume_int_suffix(lex)
        lex._emit(TokenType.INT_LIT, lex.source[start:lex.pos], line, col)
        return

    # Binary prefix: 0b...
    if lex._peek() == '0' and lex._peek(1) in ('b', 'B'):
        lex._advance()  # 0
        lex._advance()  # b
        if lex._peek() not in ('0', '1'):
            raise LexerError("Invalid binary literal: no digits after '0b'",
                             line, col)
        while lex.pos < len(lex.source) and lex._peek() in ('0', '1'):
            lex._advance()
        _consume_int_suffix(lex)
        lex._emit(TokenType.INT_LIT, lex.source[start:lex.pos], line, col)
        return

    # Octal prefix: 0o...
    if lex._peek() == '0' and lex._peek(1) in ('o', 'O'):
        lex._advance()  # 0
        lex._advance()  # o
        if lex._peek() not in '01234567':
            raise LexerError("Invalid octal literal: no digits after '0o'",
                             line, col)
        while lex.pos < len(lex.source) and lex._peek() in '01234567':
            lex._advance()
        _consume_int_suffix(lex)
        lex._emit(TokenType.INT_LIT, lex.source[start:lex.pos], line, col)
        return

    # Decimal digits
    while lex.pos < len(lex.source) and lex._peek().isdigit():
        lex._advance()

    # Decimal point
    if lex._peek() == '.' and lex._peek(1).isdigit():
        is_float = True
        lex._advance()  # .
        while lex.pos < len(lex.source) and lex._peek().isdigit():
            lex._advance()

    # Exponent
    if lex._peek() in ('e', 'E'):
        is_float = True
        lex._advance()
        if lex._peek() in ('+', '-'):
            lex._advance()
        if not lex._peek().isdigit():
            raise LexerError("Invalid float literal: no digits in exponent",
                             line, col)
        while lex.pos < len(lex.source) and lex._peek().isdigit():
            lex._advance()

    # Float suffix
    if lex._peek() in ('f', 'F'):
        is_float = True
        lex._advance()

    # Integer suffixes
    if not is_float:
        _consume_int_suffix(lex)

    value = lex.source[start:lex.pos]
    token_type = TokenType.FLOAT_LIT if is_float else TokenType.INT_LIT
    lex._emit(token_type, value, line, col)


def read_fstring(lex: Lexer, line: int, col: int):
    """Read an f-string literal: f"text {expr} text"."""
    from .lexer import LexerError
    lex._advance()  # skip opening "
    chars: list[str] = []
    brace_depth = 0
    while lex.pos < len(lex.source):
        ch = lex._peek()
        if brace_depth == 0 and ch == '"':
            lex._advance()
            value = ''.join(chars)
            lex._emit(TokenType.FSTRING_LIT, value, line, col)
            return
        elif ch == '{':
            if brace_depth == 0 and lex._peek(1) == '{':
                chars.append(lex._advance())
                chars.append(lex._advance())
            else:
                brace_depth += 1
                chars.append(lex._advance())
        elif ch == '}':
            if brace_depth == 0 and lex._peek(1) == '}':
                chars.append(lex._advance())
                chars.append(lex._advance())
            else:
                brace_depth -= 1
                chars.append(lex._advance())
        elif ch == '\\':
            chars.append(lex._advance())
            if lex.pos < len(lex.source):
                chars.append(lex._advance())
        elif ch == '\n':
            raise LexerError("Unterminated f-string literal", line, col)
        else:
            chars.append(lex._advance())
    raise LexerError("Unterminated f-string literal", line, col)


def _consume_int_suffix(lex: Lexer):
    """Consume optional integer suffixes: u, l, ll, ul, ull, lu, llu."""
    if lex._peek() in ('u', 'U'):
        lex._advance()
        # After u: optional l or ll
        if lex._peek() in ('l', 'L'):
            lex._advance()
            if lex._peek() in ('l', 'L'):
                lex._advance()
    elif lex._peek() in ('l', 'L'):
        lex._advance()
        if lex._peek() in ('l', 'L'):
            lex._advance()
            # After ll: optional u
            if lex._peek() in ('u', 'U'):
                lex._advance()
        elif lex._peek() in ('u', 'U'):
            # After l: optional u
            lex._advance()


def _is_hex_digit(ch: str) -> bool:
    return ch.isdigit() or ch.lower() in ('a', 'b', 'c', 'd', 'e', 'f')
