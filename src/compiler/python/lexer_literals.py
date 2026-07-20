"""Literal tokenization: strings, chars, numbers, f-strings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .lexer_literal_rules import (
    consume_c_escape,
    consume_integer_suffix,
    ensure_numeric_boundary,
    is_ascii_digit,
    is_hex_digit,
    is_narrow_char_hex_escape,
)
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
                value = '"' + "".join(chars) + '"'
                lex._emit(TokenType.STRING_LIT, value, line, col)
                return
            ch = lex._peek()
            if ch == "\n":
                lex._advance()
                chars.append("\\")
                chars.append("n")
            elif ch == "\r":
                lex._advance()
                chars.append("\\")
                chars.append("n")
                if lex._peek() == "\n":
                    lex._advance()
            elif ch == "\\":
                consume_c_escape(
                    lex,
                    chars,
                    line,
                    col,
                    literal_kind="string",
                )
            else:
                chars.append(lex._advance())
        raise LexerError("Unterminated triple-quoted string", line, col)

    # Regular single-line string
    chars: list[str] = []
    while lex.pos < len(lex.source):
        ch = lex._peek()
        if ch == '"':
            lex._advance()
            value = '"' + "".join(chars) + '"'
            lex._emit(TokenType.STRING_LIT, value, line, col)
            return
        elif ch == "\\":
            consume_c_escape(
                lex,
                chars,
                line,
                col,
                literal_kind="string",
            )
        elif ch in "\r\n":
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
            content = "".join(chars)
            if not _is_valid_char_content(content):
                raise LexerError(
                    "Character literal must contain exactly one character",
                    line,
                    col,
                )
            value = "'" + content + "'"
            lex._emit(TokenType.CHAR_LIT, value, line, col)
            return
        elif ch == "\\":
            chars.append(lex._advance())
            if lex.pos < len(lex.source):
                chars.append(lex._advance())
        elif ch in "\r\n":
            raise LexerError("Unterminated character literal", line, col)
        else:
            chars.append(lex._advance())
    raise LexerError("Unterminated character literal", line, col)


def _is_valid_char_content(content: str) -> bool:
    """Whether raw content denotes exactly one portable C character token."""
    if not content:
        return False
    if not content.startswith("\\"):
        return len(content) == 1 and " " <= content <= "~"
    if len(content) == 2 and content[1] in "'\"?\\abfnrtv":
        return True
    escaped = content[1:]
    if 1 <= len(escaped) <= 3 and all(ch in "01234567" for ch in escaped):
        return int(escaped, 8) <= 0xFF
    return is_narrow_char_hex_escape(content)


def read_number(lex: Lexer):
    """Read an integer or float literal (decimal, hex, binary, octal)."""
    from .lexer import LexerError

    line, col = lex.line, lex.col
    start = lex.pos
    is_float = False

    # Hex prefix: 0x...
    if lex._peek() == "0" and lex._peek(1) in ("x", "X"):
        lex._advance()  # 0
        lex._advance()  # x
        if not is_hex_digit(lex._peek()):
            raise LexerError("Invalid hex literal: no digits after '0x'", line, col)
        while lex.pos < len(lex.source) and is_hex_digit(lex._peek()):
            lex._advance()
        consume_integer_suffix(lex, line, col)
        ensure_numeric_boundary(lex, start, line, col)
        lex._emit(TokenType.INT_LIT, lex.source[start : lex.pos], line, col)
        return

    # Binary prefix: 0b...
    if lex._peek() == "0" and lex._peek(1) in ("b", "B"):
        lex._advance()  # 0
        lex._advance()  # b
        if is_ascii_digit(lex._peek()) and lex._peek() not in ("0", "1"):
            raise LexerError(
                f"Invalid digit '{lex._peek()}' in binary literal",
                line,
                col,
            )
        if lex._peek() not in ("0", "1"):
            raise LexerError("Invalid binary literal: no digits after '0b'", line, col)
        while lex.pos < len(lex.source) and lex._peek() in ("0", "1"):
            lex._advance()
        if is_ascii_digit(lex._peek()):
            raise LexerError(
                f"Invalid digit '{lex._peek()}' in binary literal",
                line,
                col,
            )
        consume_integer_suffix(lex, line, col)
        ensure_numeric_boundary(lex, start, line, col)
        lex._emit(TokenType.INT_LIT, lex.source[start : lex.pos], line, col)
        return

    # Octal prefix: 0o...
    if lex._peek() == "0" and lex._peek(1) in ("o", "O"):
        lex._advance()  # 0
        lex._advance()  # o
        if is_ascii_digit(lex._peek()) and lex._peek() not in "01234567":
            raise LexerError(
                f"Invalid digit '{lex._peek()}' in octal literal",
                line,
                col,
            )
        if lex._peek() not in "01234567":
            raise LexerError("Invalid octal literal: no digits after '0o'", line, col)
        while lex.pos < len(lex.source) and lex._peek() in "01234567":
            lex._advance()
        if is_ascii_digit(lex._peek()):
            raise LexerError(
                f"Invalid digit '{lex._peek()}' in octal literal",
                line,
                col,
            )
        consume_integer_suffix(lex, line, col)
        ensure_numeric_boundary(lex, start, line, col)
        lex._emit(TokenType.INT_LIT, lex.source[start : lex.pos], line, col)
        return

    # Decimal digits
    while lex.pos < len(lex.source) and is_ascii_digit(lex._peek()):
        lex._advance()
    integer_end = lex.pos

    # Decimal point
    if lex._peek() == "." and is_ascii_digit(lex._peek(1)):
        is_float = True
        lex._advance()  # .
        while lex.pos < len(lex.source) and is_ascii_digit(lex._peek()):
            lex._advance()

    # Exponent
    if lex._peek() in ("e", "E"):
        is_float = True
        lex._advance()
        if lex._peek() in ("+", "-"):
            lex._advance()
        if not is_ascii_digit(lex._peek()):
            raise LexerError("Invalid float literal: no digits in exponent", line, col)
        while lex.pos < len(lex.source) and is_ascii_digit(lex._peek()):
            lex._advance()

    # Float suffix
    if is_float and lex._peek() in ("f", "F"):
        lex._advance()

    # Integer suffixes
    if not is_float:
        invalid_octal = next(
            (char for char in lex.source[start:integer_end] if char in "89"),
            None,
        )
        if integer_end - start > 1 and lex.source[start] == "0" and invalid_octal:
            raise LexerError(
                f"Invalid digit '{invalid_octal}' in octal literal",
                line,
                col,
            )
        consume_integer_suffix(lex, line, col)

    ensure_numeric_boundary(lex, start, line, col)

    value = lex.source[start : lex.pos]
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
            value = "".join(chars)
            lex._emit(TokenType.FSTRING_LIT, value, line, col)
            return
        elif ch == "{":
            if brace_depth == 0 and lex._peek(1) == "{":
                chars.append(lex._advance())
                chars.append(lex._advance())
            else:
                brace_depth += 1
                chars.append(lex._advance())
        elif ch == "}":
            if brace_depth == 0 and lex._peek(1) == "}":
                chars.append(lex._advance())
                chars.append(lex._advance())
            else:
                brace_depth -= 1
                chars.append(lex._advance())
        elif ch == "\\":
            consume_c_escape(
                lex,
                chars,
                line,
                col,
                literal_kind="f-string",
            )
        elif ch in "\r\n":
            raise LexerError("Unterminated f-string literal", line, col)
        else:
            chars.append(lex._advance())
    raise LexerError("Unterminated f-string literal", line, col)
