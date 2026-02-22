"""Lexer for the btrc language. Tokenizes source code into a stream of tokens."""

from .tokens import Token, TokenType, KEYWORDS


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
            # Operators and punctuation
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
        # Check if we're at the start of a line (only whitespace before # on this line)
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
        # Skip //
        self._advance()
        self._advance()
        while self.pos < len(self.source) and self._peek() != '\n':
            self._advance()

    def _skip_block_comment(self):
        start_line = self.line
        start_col = self.col
        # Skip /*
        self._advance()
        self._advance()
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
        # Consume everything until newline (handling line continuations with \)
        while self.pos < len(self.source):
            if self._peek() == '\\' and self._peek(1) == '\n':
                self._advance()  # skip backslash
                self._advance()  # skip newline
            elif self._peek() == '\n':
                break
            else:
                self._advance()
        value = self.source[start:self.pos]
        self._emit(TokenType.PREPROCESSOR, value, line, col)

    # --- Annotation ---

    def _read_annotation(self):
        line, col = self.line, self.col
        self._advance()  # skip @
        # Read the annotation name
        start = self.pos
        while self.pos < len(self.source) and (self._peek().isalnum() or self._peek() == '_'):
            self._advance()
        name = self.source[start:self.pos]
        if name == "gpu":
            self._emit(TokenType.AT_GPU, "@gpu", line, col)
        else:
            raise LexerError(f"Unknown annotation '@{name}'", line, col)

    # --- String literal ---

    def _read_string(self):
        line, col = self.line, self.col
        self._advance()  # skip opening "
        chars: list[str] = []
        while self.pos < len(self.source):
            ch = self._peek()
            if ch == '"':
                self._advance()  # skip closing "
                value = '"' + ''.join(chars) + '"'
                self._emit(TokenType.STRING_LIT, value, line, col)
                return
            elif ch == '\\':
                chars.append(self._advance())  # backslash
                if self.pos < len(self.source):
                    chars.append(self._advance())  # escaped char
            elif ch == '\n':
                raise LexerError("Unterminated string literal", line, col)
            else:
                chars.append(self._advance())
        raise LexerError("Unterminated string literal", line, col)

    # --- Char literal ---

    def _read_char(self):
        line, col = self.line, self.col
        self._advance()  # skip opening '
        chars: list[str] = []
        while self.pos < len(self.source):
            ch = self._peek()
            if ch == "'":
                self._advance()  # skip closing '
                value = "'" + ''.join(chars) + "'"
                self._emit(TokenType.CHAR_LIT, value, line, col)
                return
            elif ch == '\\':
                chars.append(self._advance())  # backslash
                if self.pos < len(self.source):
                    chars.append(self._advance())  # escaped char
            else:
                chars.append(self._advance())
        raise LexerError("Unterminated character literal", line, col)

    # --- Number literal ---

    def _read_number(self):
        line, col = self.line, self.col
        start = self.pos
        is_float = False

        # Check for hex/binary prefix
        if self._peek() == '0' and self._peek(1) in ('x', 'X'):
            self._advance()  # 0
            self._advance()  # x
            while self.pos < len(self.source) and self._is_hex_digit(self._peek()):
                self._advance()
            self._emit(TokenType.INT_LIT, self.source[start:self.pos], line, col)
            return

        if self._peek() == '0' and self._peek(1) in ('b', 'B'):
            self._advance()  # 0
            self._advance()  # b
            while self.pos < len(self.source) and self._peek() in ('0', '1'):
                self._advance()
            self._emit(TokenType.INT_LIT, self.source[start:self.pos], line, col)
            return

        if self._peek() == '0' and self._peek(1) in ('o', 'O'):
            self._advance()  # 0
            self._advance()  # o
            while self.pos < len(self.source) and self._peek() in '01234567':
                self._advance()
            self._emit(TokenType.INT_LIT, self.source[start:self.pos], line, col)
            return

        # Decimal digits
        while self.pos < len(self.source) and self._peek().isdigit():
            self._advance()

        # Decimal point
        if self._peek() == '.' and self._peek(1).isdigit():
            is_float = True
            self._advance()  # .
            while self.pos < len(self.source) and self._peek().isdigit():
                self._advance()

        # Exponent
        if self._peek() in ('e', 'E'):
            is_float = True
            self._advance()
            if self._peek() in ('+', '-'):
                self._advance()
            while self.pos < len(self.source) and self._peek().isdigit():
                self._advance()

        # Float suffix
        if self._peek() in ('f', 'F'):
            is_float = True
            self._advance()

        # Long suffix (for ints)
        if not is_float and self._peek() in ('l', 'L'):
            self._advance()
            if self._peek() in ('l', 'L'):
                self._advance()  # LL

        # Unsigned suffix
        if not is_float and self._peek() in ('u', 'U'):
            self._advance()

        value = self.source[start:self.pos]
        token_type = TokenType.FLOAT_LIT if is_float else TokenType.INT_LIT
        self._emit(token_type, value, line, col)

    def _is_hex_digit(self, ch: str) -> bool:
        return ch.isdigit() or ch.lower() in ('a', 'b', 'c', 'd', 'e', 'f')

    # --- Identifier / keyword ---

    def _read_identifier(self):
        line, col = self.line, self.col
        start = self.pos
        while self.pos < len(self.source) and (self._peek().isalnum() or self._peek() == '_'):
            self._advance()
        value = self.source[start:self.pos]
        # Check for f-string: identifier 'f' followed immediately by '"'
        if value == "f" and self.pos < len(self.source) and self._peek() == '"':
            self._read_fstring(line, col)
            return
        token_type = KEYWORDS.get(value, TokenType.IDENT)
        self._emit(token_type, value, line, col)

    def _read_fstring(self, line: int, col: int):
        """Read an f-string literal: f"text {expr} text" """
        self._advance()  # skip opening "
        chars: list[str] = []
        brace_depth = 0
        while self.pos < len(self.source):
            ch = self._peek()
            if brace_depth == 0 and ch == '"':
                self._advance()  # skip closing "
                value = ''.join(chars)
                self._emit(TokenType.FSTRING_LIT, value, line, col)
                return
            elif ch == '{':
                if brace_depth == 0 and self._peek(1) == '{':
                    # Escaped {{ → store as {{ (literal brace)
                    chars.append(self._advance())
                    chars.append(self._advance())
                else:
                    brace_depth += 1
                    chars.append(self._advance())
            elif ch == '}':
                if brace_depth == 0 and self._peek(1) == '}':
                    # Escaped }} → store as }} (literal brace)
                    chars.append(self._advance())
                    chars.append(self._advance())
                else:
                    brace_depth -= 1
                    chars.append(self._advance())
            elif ch == '\\':
                chars.append(self._advance())  # backslash
                if self.pos < len(self.source):
                    chars.append(self._advance())  # escaped char
            elif ch == '\n':
                raise LexerError("Unterminated f-string literal", line, col)
            else:
                chars.append(self._advance())
        raise LexerError("Unterminated f-string literal", line, col)

    # --- Operators and punctuation ---

    def _read_operator(self):
        line, col = self.line, self.col
        ch = self._peek()
        ch2 = self._peek(1)
        ch3 = self._peek(2)

        # Three-character operators
        if ch == '<' and ch2 == '<' and ch3 == '=':
            self._advance()
            self._advance()
            self._advance()
            self._emit(TokenType.LT_LT_EQ, "<<=", line, col)
            return
        if ch == '>' and ch2 == '>' and ch3 == '=':
            self._advance()
            self._advance()
            self._advance()
            self._emit(TokenType.GT_GT_EQ, ">>=", line, col)
            return

        # Two-character operators
        two_char = ch + ch2
        two_char_map = {
            '==': TokenType.EQ_EQ,
            '!=': TokenType.BANG_EQ,
            '<=': TokenType.LT_EQ,
            '>=': TokenType.GT_EQ,
            '&&': TokenType.AMP_AMP,
            '||': TokenType.PIPE_PIPE,
            '<<': TokenType.LT_LT,
            '>>': TokenType.GT_GT,
            '+=': TokenType.PLUS_EQ,
            '-=': TokenType.MINUS_EQ,
            '*=': TokenType.STAR_EQ,
            '/=': TokenType.SLASH_EQ,
            '%=': TokenType.PERCENT_EQ,
            '&=': TokenType.AMP_EQ,
            '|=': TokenType.PIPE_EQ,
            '^=': TokenType.CARET_EQ,
            '++': TokenType.PLUS_PLUS,
            '--': TokenType.MINUS_MINUS,
            '->': TokenType.ARROW,
            '=>': TokenType.FAT_ARROW,
            '?.': TokenType.QUESTION_DOT,
            '??': TokenType.QUESTION_QUESTION,
        }
        if two_char in two_char_map:
            self._advance()
            self._advance()
            self._emit(two_char_map[two_char], two_char, line, col)
            return

        # Single-character operators and punctuation
        single_char_map = {
            '+': TokenType.PLUS,
            '-': TokenType.MINUS,
            '*': TokenType.STAR,
            '/': TokenType.SLASH,
            '%': TokenType.PERCENT,
            '=': TokenType.EQ,
            '<': TokenType.LT,
            '>': TokenType.GT,
            '!': TokenType.BANG,
            '&': TokenType.AMP,
            '|': TokenType.PIPE,
            '^': TokenType.CARET,
            '~': TokenType.TILDE,
            '.': TokenType.DOT,
            '?': TokenType.QUESTION,
            ':': TokenType.COLON,
            ',': TokenType.COMMA,
            ';': TokenType.SEMICOLON,
            '(': TokenType.LPAREN,
            ')': TokenType.RPAREN,
            '[': TokenType.LBRACKET,
            ']': TokenType.RBRACKET,
            '{': TokenType.LBRACE,
            '}': TokenType.RBRACE,
        }
        if ch in single_char_map:
            self._advance()
            self._emit(single_char_map[ch], ch, line, col)
            return

        raise LexerError(f"Unexpected character '{ch}'", line, col)
