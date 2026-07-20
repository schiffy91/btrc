"""Lexer for the btrc language.

Grammar-driven: keyword and operator tables are built from src/language/grammar.ebnf
via the ebnf module. Literal parsing (numbers, strings, f-strings) is
hand-coded for robustness, with the grammar's @literals serving as the spec.
"""

from .ebnf import get_grammar_info
from .lexer_literal_rules import is_ascii_alnum, is_ascii_alpha, is_ascii_digit
from .lexer_literals import read_char, read_fstring, read_number, read_string
from .tokens import ANNOTATIONS, KEYWORDS, OPERATORS, Token, TokenType


class LexerError(Exception):
    def __init__(self, message: str, line: int, col: int):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


class Lexer:
    def __init__(self, source: str, filename: str = "<stdin>"):
        self.source = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens: list[Token] = []
        self._failure: LexerError | None = None
        self._complete = False

        # Build operator trie from grammar for longest-match tokenization
        gi = get_grammar_info()
        self._op_trie = _build_trie(gi.operators)

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
        self.tokens.append(Token(TokenType.EOF, "", self.line, self.col))
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
                self._read_string()
            # Char literal
            elif ch == "'":
                self._read_char()
            # Number
            elif is_ascii_digit(ch):
                self._read_number()
            # Identifier or keyword
            elif is_ascii_alpha(ch) or ch == "_":
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

    def _emit(self, token_type: TokenType, value: str, line: int, col: int):
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
        self._emit(TokenType.PREPROCESSOR, value, line, col)

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
        while self.pos < len(self.source) and (is_ascii_alnum(self._peek()) or self._peek() == "_"):
            self._advance()
        name = self.source[start : self.pos]
        token_type = ANNOTATIONS.get(name)
        if token_type is not None:
            self._emit(token_type, f"@{name}", line, col)
        else:
            raise LexerError(f"Unknown annotation '@{name}'", line, col)

    # --- Literals (delegated to lexer_literals.py) ---

    def _read_string(self):
        read_string(self)

    def _read_char(self):
        read_char(self)

    def _read_number(self):
        read_number(self)

    # --- Identifier / keyword ---

    def _read_identifier(self):
        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.source) and (is_ascii_alnum(self._peek()) or self._peek() == "_"):
            self._advance()
        value = self.source[start : self.pos]

        # Check for f-string: identifier 'f' followed immediately by '"'
        if value == "f" and self.pos < len(self.source) and self._peek() == '"':
            read_fstring(self, line, col)
            return

        token_type = KEYWORDS.get(value, TokenType.IDENT)
        self._emit(token_type, value, line, col)

        # Import path mode: after the `import` keyword, a relative/absolute path
        # (starting with '.', '/' or '~') is read as ONE raw PATH_SPEC token so
        # whitespace inside the path is preserved and never re-tokenized.
        if token_type is TokenType.IMPORT:
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
        self._emit(TokenType.PATH_SPEC, value, line, col)

    # --- Operators and punctuation (trie-based longest match) ---

    def _read_operator(self):
        line, col = self.line, self.col

        # Walk the operator trie for longest match
        node = self._op_trie
        best_match = None
        best_len = 0
        i = 0
        while self.pos + i < len(self.source):
            ch = self.source[self.pos + i]
            if ch not in node:
                break
            node = node[ch]
            i += 1
            if "" in node:  # terminal marker
                best_match = node[""]
                best_len = i

        if best_match is not None:
            value = self.source[self.pos : self.pos + best_len]
            for _ in range(best_len):
                self._advance()
            self._emit(best_match, value, line, col)
            return

        ch = self._peek()
        if ord(ch) > 0x7F:
            raise LexerError("Unexpected non-ASCII character", line, col)
        raise LexerError(f"Unexpected character '{ch}'", line, col)


def _build_trie(operators: list[str]) -> dict:
    """Build a trie from operator strings for longest-match tokenization.

    Each node is a dict mapping character -> child node.
    Terminal nodes have '' -> TokenType entry.
    """
    root: dict = {}
    for op in operators:
        token_type = OPERATORS[op]
        node = root
        for ch in op:
            if ch not in node:
                node[ch] = {}
            node = node[ch]
        node[""] = token_type  # terminal marker
    return root
