"""Grammar-driven lexical analysis for the btrc language."""

from __future__ import annotations

import math
import struct
from types import MappingProxyType

from ..syntax.tokens import Token, TokenKind, TokenVocabulary


class LexerError(Exception):
    def __init__(self, message: str, line: int, col: int):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


class LiteralDecoder:
    """Own target-independent decoding and validation of literal token values."""

    _INTEGER_SUFFIXES = frozenset(
        {
            "u",
            "U",
            "l",
            "L",
            "ll",
            "LL",
            "ul",
            "uL",
            "ull",
            "uLL",
            "Ul",
            "UL",
            "Ull",
            "ULL",
            "lu",
            "lU",
            "Lu",
            "LU",
            "llu",
            "llU",
            "LLu",
            "LLU",
        }
    )
    _SIMPLE_ESCAPES = MappingProxyType(
        {
            "'": ord("'"),
            '"': ord('"'),
            "?": ord("?"),
            "\\": ord("\\"),
            "a": 7,
            "b": 8,
            "f": 12,
            "n": 10,
            "r": 13,
            "t": 9,
            "v": 11,
        }
    )
    _SIGNED_INTEGER_MAX = (1 << 63) - 1
    _UNSIGNED_INTEGER_MAX = (1 << 64) - 1

    @classmethod
    def valid_integer_suffix(cls, suffix: str) -> bool:
        return suffix in cls._INTEGER_SUFFIXES

    @classmethod
    def integer_parts(cls, raw: str) -> tuple[str, str]:
        split = len(raw)
        while split and raw[split - 1] in "uUlL":
            split -= 1
        suffix = raw[split:]
        if suffix and not cls.valid_integer_suffix(suffix):
            raise ValueError(f"invalid integer suffix '{suffix}'")
        return (raw[:split], suffix.lower())

    @classmethod
    def parse_integer_value(cls, raw: str) -> int:
        """Decode one lexically valid C-style integer token."""

        body, suffix = cls.integer_parts(raw)
        if not body:
            raise ValueError("empty integer literal")
        if len(body) > 1 and body[0] == "0" and (body[1] not in "xXbBoO"):
            value = int(body, 8)
        else:
            value = int(body, 0)
        decimal = not (
            body.startswith(("0x", "0X", "0b", "0B", "0o", "0O")) or (len(body) > 1 and body.startswith("0"))
        )
        maximum = cls._SIGNED_INTEGER_MAX if decimal and suffix in {"", "l", "ll"} else cls._UNSIGNED_INTEGER_MAX
        if value > maximum:
            raise ValueError(f"integer literal '{raw}' exceeds the portable C integer domain")
        return value

    @classmethod
    def float_problem(cls, raw: str, value: float) -> str | None:
        """Explain a floating token that cannot survive strict-C emission."""

        if not math.isfinite(value):
            return f"Floating literal '{raw}' is outside the finite double range"
        if value == 0.0 and cls._has_nonzero_significand(raw):
            return f"Floating literal '{raw}' underflows to zero"
        if not raw.endswith(("f", "F")):
            return None
        return cls.float32_problem(raw, value)

    @classmethod
    def float32_problem(cls, raw: str, value: float) -> str | None:
        """Explain a floating token that cannot retain a finite nonzero f32 value."""

        try:
            narrowed = struct.unpack("=f", struct.pack("=f", value))[0]
        except OverflowError:
            narrowed = math.inf
        if not math.isfinite(narrowed):
            return f"Floating literal '{raw}' is outside the finite float range"
        if narrowed == 0.0 and cls._has_nonzero_significand(raw):
            return f"Floating literal '{raw}' underflows to zero as float"
        return None

    @classmethod
    def decode_character(cls, raw: str) -> int | None:
        """Decode one narrow-character spelling accepted by the lexer."""

        if len(raw) < 3 or raw[0] != "'" or raw[-1] != "'":
            return None
        content = raw[1:-1]
        if len(content) == 1 and content != "\\":
            return ord(content) if " " <= content <= "~" else None
        if not content.startswith("\\") or len(content) < 2:
            return None
        escaped = content[1:]
        if len(escaped) == 1 and escaped in cls._SIMPLE_ESCAPES:
            return cls._SIMPLE_ESCAPES[escaped]
        if escaped.startswith("x") and len(escaped) > 1:
            try:
                value = int(escaped[1:], 16)
            except ValueError:
                return None
            return value if value <= 0xFF else None
        if 1 <= len(escaped) <= 3 and all(character in "01234567" for character in escaped):
            value = int(escaped, 8)
            return value if value <= 0xFF else None
        return None

    @classmethod
    def is_simple_escape(cls, character: str) -> bool:
        return character in cls._SIMPLE_ESCAPES

    @staticmethod
    def _has_nonzero_significand(raw: str) -> bool:
        significand = raw.split("e", 1)[0].split("E", 1)[0]
        return any(character in "123456789" for character in significand)


class LiteralScanner:
    """Own literal recognition for one lexer invocation."""

    def __init__(self, lexer: Lexer) -> None:
        self._lexer = lexer

    _UCN_BASIC_EXCEPTIONS = frozenset((0x24, 0x40, 0x60))

    def is_ascii_digit(self, char: str) -> bool:
        return "0" <= char <= "9"

    def is_ascii_alpha(self, char: str) -> bool:
        return "a" <= char <= "z" or "A" <= char <= "Z"

    def is_ascii_alnum(self, char: str) -> bool:
        return self.is_ascii_alpha(char) or self.is_ascii_digit(char)

    def is_hex_digit(self, char: str) -> bool:
        return self.is_ascii_digit(char) or "a" <= char.lower() <= "f"

    def _is_identifier_continue(self, char: str) -> bool:
        return char == "_" or self.is_ascii_alnum(char)

    def _is_valid_universal_character(self, value: int) -> bool:
        return value in self._UCN_BASIC_EXCEPTIONS or (0xA0 <= value <= 0x10FFFF and not 0xD800 <= value <= 0xDFFF)

    def _is_valid_char_content(self, content: str) -> bool:
        """Whether raw content denotes exactly one portable C character token."""
        return LiteralDecoder.decode_character(f"'{content}'") is not None

    def _consume_integer_suffix(self, line: int, col: int) -> None:
        """Consume one exact C11 integer suffix, rejecting partial prefixes."""
        lex = self._lexer

        start = lex.pos
        while lex._peek() in "uUlL":
            lex._advance()
        suffix = lex.source[start : lex.pos]
        if suffix and not LiteralDecoder.valid_integer_suffix(suffix):
            raise LexerError(f"Invalid integer suffix '{suffix}'", line, col)

    def _ensure_numeric_boundary(self, start: int, line: int, col: int) -> None:
        """Reject a pp-number tail instead of leaking it as another token."""
        lex = self._lexer

        if not self._is_identifier_continue(lex._peek()):
            return
        end = lex.pos
        while end < len(lex.source) and self._is_identifier_continue(lex.source[end]):
            end += 1
        raise LexerError(
            f"Invalid numeric literal '{lex.source[start:end]}'",
            line,
            col,
        )

    def _consume_c_escape(
        self,
        chars: list[str],
        line: int,
        col: int,
        *,
        literal_kind: str,
    ) -> None:
        """Validate and preserve one C11 escape, including line splices."""
        lex = self._lexer

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
        if LiteralDecoder.is_simple_escape(escaped):
            chars.append(lex._advance())
            return
        if "0" <= escaped <= "7":
            self._consume_octal_escape(chars, line, col, literal_kind)
            return
        if escaped == "x":
            self._consume_hex_escape(chars, line, col, literal_kind)
            return
        if escaped in "uU":
            self._consume_universal_character(chars, line, col, literal_kind)
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
        self,
        chars: list[str],
        line: int,
        col: int,
        literal_kind: str,
    ) -> None:
        lex = self._lexer

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
        self,
        chars: list[str],
        line: int,
        col: int,
        literal_kind: str,
    ) -> None:
        lex = self._lexer

        chars.append(lex._advance())
        if not self.is_hex_digit(lex._peek()):
            raise LexerError(
                f"Hex escape sequence requires digits in {literal_kind} literal",
                line,
                col,
            )
        value = 0
        out_of_range = False
        while self.is_hex_digit(lex._peek()):
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
        self,
        chars: list[str],
        line: int,
        col: int,
        literal_kind: str,
    ) -> None:
        lex = self._lexer

        prefix = lex._advance()
        chars.append(prefix)
        digits = 4 if prefix == "u" else 8
        value = 0
        for _ in range(digits):
            if not self.is_hex_digit(lex._peek()):
                raise LexerError(
                    f"Invalid universal character escape in {literal_kind} literal",
                    line,
                    col,
                )
            digit = lex._advance()
            chars.append(digit)
            value = value * 16 + int(digit, 16)
        if not self._is_valid_universal_character(value):
            raise LexerError(
                f"Invalid universal character escape in {literal_kind} literal",
                line,
                col,
            )

    def read_string(self):
        """Read a double-quoted or triple-quoted string literal."""
        lex = self._lexer

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
                    lex._emit(TokenKind.STRING_LIT, value, line, col)
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
                    self._consume_c_escape(
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
                lex._emit(TokenKind.STRING_LIT, value, line, col)
                return
            elif ch == "\\":
                self._consume_c_escape(
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

    def read_char(self):
        """Read a single-quoted char literal."""
        lex = self._lexer

        line, col = lex.line, lex.col
        lex._advance()  # skip opening '
        chars: list[str] = []
        while lex.pos < len(lex.source):
            ch = lex._peek()
            if ch == "'":
                lex._advance()
                content = "".join(chars)
                if not self._is_valid_char_content(content):
                    raise LexerError(
                        "Character literal must contain exactly one character",
                        line,
                        col,
                    )
                value = "'" + content + "'"
                lex._emit(TokenKind.CHAR_LIT, value, line, col)
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

    def read_number(self):
        """Read an integer or float literal (decimal, hex, binary, octal)."""
        lex = self._lexer

        line, col = lex.line, lex.col
        start = lex.pos
        is_float = False

        # Hex prefix: 0x...
        if lex._peek() == "0" and lex._peek(1) in ("x", "X"):
            lex._advance()  # 0
            lex._advance()  # x
            if not self.is_hex_digit(lex._peek()):
                raise LexerError("Invalid hex literal: no digits after '0x'", line, col)
            while lex.pos < len(lex.source) and self.is_hex_digit(lex._peek()):
                lex._advance()
            self._consume_integer_suffix(line, col)
            self._ensure_numeric_boundary(start, line, col)
            lex._emit(TokenKind.INT_LIT, lex.source[start : lex.pos], line, col)
            return

        # Binary prefix: 0b...
        if lex._peek() == "0" and lex._peek(1) in ("b", "B"):
            lex._advance()  # 0
            lex._advance()  # b
            if self.is_ascii_digit(lex._peek()) and lex._peek() not in ("0", "1"):
                raise LexerError(
                    f"Invalid digit '{lex._peek()}' in binary literal",
                    line,
                    col,
                )
            if lex._peek() not in ("0", "1"):
                raise LexerError("Invalid binary literal: no digits after '0b'", line, col)
            while lex.pos < len(lex.source) and lex._peek() in ("0", "1"):
                lex._advance()
            if self.is_ascii_digit(lex._peek()):
                raise LexerError(
                    f"Invalid digit '{lex._peek()}' in binary literal",
                    line,
                    col,
                )
            self._consume_integer_suffix(line, col)
            self._ensure_numeric_boundary(start, line, col)
            lex._emit(TokenKind.INT_LIT, lex.source[start : lex.pos], line, col)
            return

        # Octal prefix: 0o...
        if lex._peek() == "0" and lex._peek(1) in ("o", "O"):
            lex._advance()  # 0
            lex._advance()  # o
            if self.is_ascii_digit(lex._peek()) and lex._peek() not in "01234567":
                raise LexerError(
                    f"Invalid digit '{lex._peek()}' in octal literal",
                    line,
                    col,
                )
            if lex._peek() not in "01234567":
                raise LexerError("Invalid octal literal: no digits after '0o'", line, col)
            while lex.pos < len(lex.source) and lex._peek() in "01234567":
                lex._advance()
            if self.is_ascii_digit(lex._peek()):
                raise LexerError(
                    f"Invalid digit '{lex._peek()}' in octal literal",
                    line,
                    col,
                )
            self._consume_integer_suffix(line, col)
            self._ensure_numeric_boundary(start, line, col)
            lex._emit(TokenKind.INT_LIT, lex.source[start : lex.pos], line, col)
            return

        # Decimal digits
        while lex.pos < len(lex.source) and self.is_ascii_digit(lex._peek()):
            lex._advance()
        integer_end = lex.pos

        # Decimal point
        if lex._peek() == "." and self.is_ascii_digit(lex._peek(1)):
            is_float = True
            lex._advance()  # .
            while lex.pos < len(lex.source) and self.is_ascii_digit(lex._peek()):
                lex._advance()

        # Exponent
        if lex._peek() in ("e", "E"):
            is_float = True
            lex._advance()
            if lex._peek() in ("+", "-"):
                lex._advance()
            if not self.is_ascii_digit(lex._peek()):
                raise LexerError("Invalid float literal: no digits in exponent", line, col)
            while lex.pos < len(lex.source) and self.is_ascii_digit(lex._peek()):
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
            self._consume_integer_suffix(line, col)

        self._ensure_numeric_boundary(start, line, col)

        value = lex.source[start : lex.pos]
        token_type = TokenKind.FLOAT_LIT if is_float else TokenKind.INT_LIT
        lex._emit(token_type, value, line, col)

    def read_fstring(self, line: int, col: int):
        """Read an f-string literal: f"text {expr} text"."""
        lex = self._lexer

        lex._advance()  # skip opening "
        chars: list[str] = []
        brace_depth = 0
        while lex.pos < len(lex.source):
            ch = lex._peek()
            if brace_depth == 0 and ch == '"':
                lex._advance()
                value = "".join(chars)
                lex._emit(TokenKind.FSTRING_LIT, value, line, col)
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
                self._consume_c_escape(
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


class Lexer:
    def __init__(
        self,
        source: str,
        filename: str = "<stdin>",
        vocabulary: TokenVocabulary | None = None,
    ):
        self.source = source
        self.filename = filename
        self._vocabulary = vocabulary or TokenVocabulary.canonical()
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []
        self._failure: LexerError | None = None
        self._literal_scanner = LiteralScanner(self)
        self._complete = False

    def tokenize(self) -> list[Token]:
        if self._failure is not None:
            raise self._failure
        if self._complete:
            return self.tokens
        try:
            self._scan_tokens()
        except LexerError as error:
            self.tokens.clear()
            self._failure = error
            raise
        self.tokens.append(Token(TokenKind.EOF, "", self.line, self.col))
        self._complete = True
        return self.tokens

    def _scan_tokens(self) -> None:
        while self.pos < len(self.source):
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.source):
                break

            ch = self.source[self.pos]

            # Preprocessor directive
            if ch == "#" and self._at_line_start():
                self._read_preprocessor()
            # Annotation (@gpu)
            elif ch == "@":
                self._read_annotation()
            # String literal
            elif ch == '"':
                self._literal_scanner.read_string()
            # Char literal
            elif ch == "'":
                self._literal_scanner.read_char()
            # Number
            elif self._literal_scanner.is_ascii_digit(ch):
                self._literal_scanner.read_number()
            # Identifier or keyword
            elif self._literal_scanner.is_ascii_alpha(ch) or ch == "_":
                self._read_identifier()
            # Operators and punctuation (trie-based longest match)
            else:
                self._read_operator()

    # --- Character helpers ---

    def _peek(self, offset: int = 0) -> str:
        pos = self.pos + offset
        if pos < len(self.source):
            return self.source[pos]
        return "\0"

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _at_line_start(self) -> bool:
        i = self.pos - 1
        while i >= 0 and self.source[i] in (" ", "\t", "\f", "\v", "\r"):
            i -= 1
        return i < 0 or self.source[i] == "\n"

    def _emit(self, token_type: TokenKind, value: str, line: int, col: int):
        self.tokens.append(Token(token_type, value, line, col))

    # --- Whitespace and comments ---

    def _skip_whitespace_and_comments(self):
        while self.pos < len(self.source):
            ch = self._peek()
            if ch in (" ", "\t", "\n", "\r", "\f", "\v"):
                self._advance()
            elif ch == "/" and self._peek(1) == "/":
                self._skip_line_comment()
            elif ch == "/" and self._peek(1) == "*":
                self._skip_block_comment()
            else:
                break

    def _skip_line_comment(self):
        self._advance()  # /
        self._advance()  # /
        while self.pos < len(self.source) and self._peek() != "\n":
            self._advance()

    def _skip_block_comment(self):
        start_line = self.line
        start_col = self.col
        self._advance()  # /
        self._advance()  # *
        while self.pos < len(self.source):
            if self._peek() == "*" and self._peek(1) == "/":
                self._advance()
                self._advance()
                return
            self._advance()
        raise LexerError("Unterminated block comment", start_line, start_col)

    # --- Preprocessor ---

    def _read_preprocessor(self):
        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.source):
            splice_width = self._preprocessor_splice_width()
            if splice_width:
                for _ in range(splice_width):
                    self._advance()
            elif self._peek() == "\n":
                break
            else:
                self._advance()
        value = self.source[start : self.pos]
        self._emit(TokenKind.PREPROCESSOR, value, line, col)

    def _preprocessor_splice_width(self) -> int:
        marker_width = 1 if self._peek() == "\\" else 3 if self.source.startswith("??/", self.pos) else 0
        if marker_width and self._peek(marker_width) == "\n":
            return marker_width + 1
        if marker_width and self._peek(marker_width) == "\r" and self._peek(marker_width + 1) == "\n":
            return marker_width + 2
        return 0

    # --- Annotation (grammar-driven via @annotations section) ---

    def _read_annotation(self):
        line, col = self.line, self.col
        self._advance()  # skip @
        start = self.pos
        while self.pos < len(self.source) and (
            self._literal_scanner.is_ascii_alnum(self._peek()) or self._peek() == "_"
        ):
            self._advance()
        name = self.source[start : self.pos]
        token_type = self._vocabulary.annotations.get(name)
        if token_type is not None:
            self._emit(token_type, f"@{name}", line, col)
        else:
            raise LexerError(f"Unknown annotation '@{name}'", line, col)

    # --- Identifier / keyword ---

    def _read_identifier(self):
        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.source) and (
            self._literal_scanner.is_ascii_alnum(self._peek()) or self._peek() == "_"
        ):
            self._advance()
        value = self.source[start : self.pos]

        # Check for f-string: identifier 'f' followed immediately by '"'
        if value == "f" and self.pos < len(self.source) and self._peek() == '"':
            self._literal_scanner.read_fstring(line, col)
            return

        token_type = self._vocabulary.keywords.get(value, TokenKind.IDENT)
        self._emit(token_type, value, line, col)

        # Import path mode: after the `import` keyword, a relative/absolute path
        # (starting with '.', '/' or '~') is read as ONE raw PATH_SPEC token so
        # whitespace inside the path is preserved and never re-tokenized.
        if token_type is TokenKind.IMPORT:
            self._maybe_read_import_path()

    # --- Import path (single raw token after `import`) ---

    def _maybe_read_import_path(self):
        """If the token after `import` begins a filesystem path, read it raw.

        Only '.', '/' and '~' trigger path mode (covers ./x, ../y, /abs, ~/home).
        std.x / std.{a,b} / std.* / "quoted" / bare packages (mathx.vec) begin
        with an identifier or '"' and lex normally for the parser to assemble.
        """
        save_pos, save_line, save_col = self.pos, self.line, self.col
        # Skip inline spaces/tabs (but NOT newlines: a bare `import` on its own
        # line is a parse error, not a path read across lines).
        while self.pos < len(self.source) and self._peek() in (" ", "\t"):
            self._advance()
        if self.pos >= len(self.source) or self._peek() not in (".", "/", "~"):
            self.pos, self.line, self.col = save_pos, save_line, save_col
            return
        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.source) and self._peek() not in (";", "\n"):
            self._advance()
        value = self.source[start : self.pos].rstrip()
        self._emit(TokenKind.PATH_SPEC, value, line, col)

    # --- Operators and punctuation (trie-based longest match) ---

    def _read_operator(self):
        line, col = self.line, self.col

        match = self._vocabulary.match_operator(self.source, self.pos)
        if match is not None:
            token_type, width = match
            value = self.source[self.pos : self.pos + width]
            for _ in range(width):
                self._advance()
            self._emit(token_type, value, line, col)
            return

        ch = self._peek()
        if ord(ch) > 0x7F:
            raise LexerError("Unexpected non-ASCII character", line, col)
        raise LexerError(f"Unexpected character '{ch}'", line, col)
