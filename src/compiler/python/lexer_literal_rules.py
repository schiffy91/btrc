"""Shared lexical contracts for literals passed through to strict C11."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .lexer import Lexer

_SIMPLE_ESCAPES = frozenset("'\"?\\abfnrtv")
_UNSIGNED_SUFFIXES = ("u", "U")
_LONG_SUFFIXES = ("l", "L", "ll", "LL")
_INTEGER_SUFFIXES = frozenset(
    (
        *_UNSIGNED_SUFFIXES,
        *_LONG_SUFFIXES,
        *(unsigned + long for unsigned in _UNSIGNED_SUFFIXES for long in _LONG_SUFFIXES),
        *(long + unsigned for long in _LONG_SUFFIXES for unsigned in _UNSIGNED_SUFFIXES),
    )
)
_UCN_BASIC_EXCEPTIONS = frozenset((0x24, 0x40, 0x60))


def is_ascii_digit(char: str) -> bool:
    return "0" <= char <= "9"


def is_ascii_alpha(char: str) -> bool:
    return "a" <= char <= "z" or "A" <= char <= "Z"


def is_ascii_alnum(char: str) -> bool:
    return is_ascii_alpha(char) or is_ascii_digit(char)


def is_hex_digit(char: str) -> bool:
    return is_ascii_digit(char) or "a" <= char.lower() <= "f"


def is_narrow_char_hex_escape(content: str) -> bool:
    """Whether a greedy C hex escape denotes one narrow character."""
    if len(content) < 3 or content[0:2] != "\\x":
        return False
    value = 0
    for digit in content[2:]:
        if not is_hex_digit(digit):
            return False
        value = value * 16 + int(digit, 16)
        if value > 0xFF:
            return False
    return True


def consume_integer_suffix(lex: Lexer, line: int, col: int) -> None:
    """Consume one exact C11 integer suffix, rejecting partial prefixes."""
    from .lexer import LexerError

    start = lex.pos
    while lex._peek() in "uUlL":
        lex._advance()
    suffix = lex.source[start : lex.pos]
    if suffix and suffix not in _INTEGER_SUFFIXES:
        raise LexerError(f"Invalid integer suffix '{suffix}'", line, col)


def ensure_numeric_boundary(lex: Lexer, start: int, line: int, col: int) -> None:
    """Reject a pp-number tail instead of leaking it as another token."""
    from .lexer import LexerError

    if not _is_identifier_continue(lex._peek()):
        return
    end = lex.pos
    while end < len(lex.source) and _is_identifier_continue(lex.source[end]):
        end += 1
    raise LexerError(
        f"Invalid numeric literal '{lex.source[start:end]}'",
        line,
        col,
    )


def consume_c_escape(
    lex: Lexer,
    chars: list[str],
    line: int,
    col: int,
    *,
    literal_kind: str,
) -> None:
    """Validate and preserve one C11 escape, including line splices."""
    from .lexer import LexerError

    chars.append(lex._advance())
    if lex.pos >= len(lex.source):
        raise LexerError(f"Unterminated {literal_kind} literal", line, col)

    escaped = lex._peek()
    if escaped == "\n":
        chars.append(lex._advance())
        return
    if escaped == "\r" and lex._peek(1) == "\n":
        chars.append(lex._advance())
        chars.append(lex._advance())
        return
    if escaped == "\r":
        raise LexerError(f"Unterminated {literal_kind} literal", line, col)
    if escaped in _SIMPLE_ESCAPES:
        chars.append(lex._advance())
        return
    if "0" <= escaped <= "7":
        _consume_octal_escape(lex, chars, line, col, literal_kind)
        return
    if escaped == "x":
        _consume_hex_escape(lex, chars, line, col, literal_kind)
        return
    if escaped in "uU":
        _consume_universal_character(lex, chars, line, col, literal_kind)
        return
    if not " " <= escaped <= "~":
        raise LexerError(
            f"Invalid non-ASCII escape in {literal_kind} literal",
            line,
            col,
        )
    raise LexerError(
        f"Invalid escape sequence '\\{escaped}' in {literal_kind} literal",
        line,
        col,
    )


def _consume_octal_escape(
    lex: Lexer,
    chars: list[str],
    line: int,
    col: int,
    literal_kind: str,
) -> None:
    from .lexer import LexerError

    value = 0
    count = 0
    while count < 3 and "0" <= lex._peek() <= "7":
        digit = lex._advance()
        chars.append(digit)
        value = value * 8 + ord(digit) - ord("0")
        count += 1
    if value > 0xFF:
        raise LexerError(
            f"Octal escape sequence out of range in {literal_kind} literal",
            line,
            col,
        )


def _consume_hex_escape(
    lex: Lexer,
    chars: list[str],
    line: int,
    col: int,
    literal_kind: str,
) -> None:
    from .lexer import LexerError

    chars.append(lex._advance())
    if not is_hex_digit(lex._peek()):
        raise LexerError(
            f"Hex escape sequence requires digits in {literal_kind} literal",
            line,
            col,
        )
    value = 0
    out_of_range = False
    while is_hex_digit(lex._peek()):
        digit = lex._advance()
        chars.append(digit)
        if not out_of_range:
            value = value * 16 + int(digit, 16)
            out_of_range = value > 0xFF
    if out_of_range:
        raise LexerError(
            f"Hex escape sequence out of range in {literal_kind} literal",
            line,
            col,
        )


def _consume_universal_character(
    lex: Lexer,
    chars: list[str],
    line: int,
    col: int,
    literal_kind: str,
) -> None:
    from .lexer import LexerError

    prefix = lex._advance()
    chars.append(prefix)
    digits = 4 if prefix == "u" else 8
    value = 0
    for _ in range(digits):
        if not is_hex_digit(lex._peek()):
            raise LexerError(
                f"Invalid universal character escape in {literal_kind} literal",
                line,
                col,
            )
        digit = lex._advance()
        chars.append(digit)
        value = value * 16 + int(digit, 16)
    if not _is_valid_universal_character(value):
        raise LexerError(
            f"Invalid universal character escape in {literal_kind} literal",
            line,
            col,
        )


def _is_identifier_continue(char: str) -> bool:
    return char == "_" or is_ascii_alnum(char)


def _is_valid_universal_character(value: int) -> bool:
    return value in _UCN_BASIC_EXCEPTIONS or (0xA0 <= value <= 0x10FFFF and not 0xD800 <= value <= 0xDFFF)


__all__ = [
    "consume_c_escape",
    "consume_integer_suffix",
    "ensure_numeric_boundary",
    "is_ascii_alnum",
    "is_ascii_alpha",
    "is_ascii_digit",
    "is_hex_digit",
    "is_narrow_char_hex_escape",
]
