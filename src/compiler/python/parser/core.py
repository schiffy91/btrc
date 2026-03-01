"""Parser core: token manipulation, error handling, and parse() entry point."""


from ..tokens import Token, TokenType


class ParseError(Exception):
    def __init__(self, message: str, line: int, col: int):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


class ParserBase:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self):
        from ..ast_nodes import Program
        decls = []
        while not self._at_end():
            decls.append(self._parse_top_level_item())
        return Program(declarations=decls)

    # ---- Token helpers ----

    def _peek(self, offset: int = 0) -> Token:
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]  # EOF

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _check(self, *types: TokenType) -> bool:
        return self._peek().type in types

    def _match(self, *types: TokenType) -> Token | None:
        if self._peek().type in types:
            return self._advance()
        return None

    def _expect(self, token_type: TokenType, msg: str = "") -> Token:
        tok = self._peek()
        if tok.type == token_type:
            return self._advance()
        expected = msg or token_type.name
        raise ParseError(
            f"Expected {expected}, got {tok.type.name} '{tok.value}'",
            tok.line, tok.col
        )

    def _error(self, msg: str) -> ParseError:
        tok = self._peek()
        return ParseError(msg, tok.line, tok.col)

    # ---- Helpers for >> splitting in generic context ----

    def _expect_gt(self) -> Token:
        """Expect a '>' — handles splitting '>>' and '>>=' tokens."""
        tok = self._peek()
        if tok.type == TokenType.GT:
            return self._advance()
        if tok.type == TokenType.GT_GT:
            self._advance()
            synthetic = Token(TokenType.GT, ">", tok.line, tok.col + 1)
            self.tokens.insert(self.pos, synthetic)
            return Token(TokenType.GT, ">", tok.line, tok.col)
        if tok.type == TokenType.GT_GT_EQ:
            self._advance()
            synthetic = Token(TokenType.GT_EQ, ">=", tok.line, tok.col + 1)
            self.tokens.insert(self.pos, synthetic)
            return Token(TokenType.GT, ">", tok.line, tok.col)
        raise ParseError(
            f"Expected '>', got {tok.type.name} '{tok.value}'",
            tok.line, tok.col
        )
