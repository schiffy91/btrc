"""Lexer for the btrc language.

Grammar-driven: keyword and operator tables are built from src/language/grammar.ebnf
via the ebnf module. Literal parsing (numbers, strings, f-strings) is
hand-coded for robustness, with the grammar's @literals serving as the spec.
"""

from .ebnf import get_grammar_info
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

        # Build operator trie from grammar for longest-match tokenization
        gi = get_grammar_info()
        self._op_trie = _build_trie(gi.operators)

    def tokenize(self) -> list[Token]:
        while self.pos < len(self.source):
            self._skip_whitespace_and_comments()
            if self.pos >= len(self.source):
                break

            ch = self.source[self.pos]

            # Preprocessor directive
            if ch == '#' and self._at_line_start():
                self._read_preprocessor()
            # Annotation (@gpu)
            elif ch == '@':
                self._read_annotation()
            # String literal
            elif ch == '"':
                self._read_string()
            # Char literal
            elif ch == "'":
                self._read_char()
            # Number
            elif ch.isdigit():
                self._read_number()
            # Identifier or keyword
            elif ch.isalpha() or ch == '_':
                self._read_identifier()
            # Operators and punctuation (trie-based longest match)
            else:
                self._read_operator()

        self.tokens.append(Token(TokenType.EOF, "", self.line, self.col))
        return self.tokens

    # --- Character helpers ---

    def _peek(self, offset: int = 0) -> str:
        pos = self.pos + offset
        if pos < len(self.source):
            return self.source[pos]
        return '\0'

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == '\n':
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _at_line_start(self) -> bool:
        i = self.pos - 1
        while i >= 0 and self.source[i] in (' ', '\t'):
            i -= 1
        return i < 0 or self.source[i] == '\n'

    def _emit(self, token_type: TokenType, value: str, line: int, col: int):
        self.tokens.append(Token(token_type, value, line, col))

    # --- Whitespace and comments ---

    def _skip_whitespace_and_comments(self):
        while self.pos < len(self.source):
            ch = self._peek()
            if ch in (' ', '\t', '\n', '\r'):
                self._advance()
            elif ch == '/' and self._peek(1) == '/':
                self._skip_line_comment()
            elif ch == '/' and self._peek(1) == '*':
                self._skip_block_comment()
            else:
                break

    def _skip_line_comment(self):
        self._advance()  # /
        self._advance()  # /
        while self.pos < len(self.source) and self._peek() != '\n':
            self._advance()

    def _skip_block_comment(self):
        start_line = self.line
        start_col = self.col
        self._advance()  # /
        self._advance()  # *
        while self.pos < len(self.source):
            if self._peek() == '*' and self._peek(1) == '/':
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
            if self._peek() == '\\' and self._peek(1) == '\n':
                self._advance()
                self._advance()
            elif self._peek() == '\n':
                break
            else:
                self._advance()
        value = self.source[start:self.pos]
        self._emit(TokenType.PREPROCESSOR, value, line, col)

    # --- Annotation (grammar-driven via @annotations section) ---

    def _read_annotation(self):
        line, col = self.line, self.col
        self._advance()  # skip @
        start = self.pos
        while self.pos < len(self.source) and (self._peek().isalnum() or self._peek() == '_'):
            self._advance()
        name = self.source[start:self.pos]
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
        while self.pos < len(self.source) and (self._peek().isalnum() or self._peek() == '_'):
            self._advance()
        value = self.source[start:self.pos]

        # Check for f-string: identifier 'f' followed immediately by '"'
        if value == "f" and self.pos < len(self.source) and self._peek() == '"':
            read_fstring(self, line, col)
            return

        token_type = KEYWORDS.get(value, TokenType.IDENT)
        self._emit(token_type, value, line, col)

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
            if '' in node:  # terminal marker
                best_match = node['']
                best_len = i

        if best_match is not None:
            value = self.source[self.pos:self.pos + best_len]
            for _ in range(best_len):
                self._advance()
            self._emit(best_match, value, line, col)
            return

        ch = self._peek()
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
        node[''] = token_type  # terminal marker
    return root
