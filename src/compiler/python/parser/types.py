"""Type expression and parameter parsing."""

from ..ast_nodes import Param, TypeExpr
from ..tokens import TYPE_KEYWORDS, TokenType


class TypesMixin:

    def _is_type_start(self, tok) -> bool:
        """Check if a token could start a type expression."""
        if tok.type == TokenType.VAR:
            return True
        if tok.type in TYPE_KEYWORDS:
            return True
        if tok.type == TokenType.IDENT:
            return True
        return tok.type == TokenType.LPAREN and self._is_tuple_type_start()

    def _parse_type_expr(self) -> TypeExpr:
        tok = self._peek()
        line, col = tok.line, tok.col

        # Handle const/static/extern/volatile qualifiers
        has_const = False
        while self._check(TokenType.CONST, TokenType.STATIC, TokenType.EXTERN, TokenType.VOLATILE):
            if self._peek().type == TokenType.CONST:
                has_const = True
            self._advance()

        # Handle unsigned/signed qualifiers
        if self._check(TokenType.UNSIGNED, TokenType.SIGNED):
            base = self._advance().value
            if self._check(TokenType.INT, TokenType.SHORT, TokenType.LONG, TokenType.CHAR):
                base += " " + self._advance().value
                if base.endswith("long") and self._check(TokenType.LONG):
                    base += " " + self._advance().value
        elif self._check(TokenType.LONG):
            base = self._advance().value
            if self._check(TokenType.LONG):
                base += " " + self._advance().value
            if self._check(TokenType.INT, TokenType.DOUBLE):
                base += " " + self._advance().value
        elif self._check(TokenType.SHORT):
            base = self._advance().value
            if self._check(TokenType.INT):
                base += " " + self._advance().value
        elif self._check(TokenType.STRUCT):
            self._advance()
            base = "struct " + self._expect(TokenType.IDENT, "struct name").value
        elif self._check(TokenType.ENUM):
            self._advance()
            base = "enum " + self._expect(TokenType.IDENT, "enum name").value
        elif self._check(TokenType.UNION):
            self._advance()
            base = "union " + self._expect(TokenType.IDENT, "union name").value
        elif self._check(TokenType.LPAREN):
            return self._parse_tuple_type(line, col)
        else:
            base_tok = self._advance()
            base = base_tok.value

        # Generic arguments
        generic_args = []
        if self._check(TokenType.LT) and self._is_generic_start():
            self._advance()
            generic_args.append(self._parse_type_expr())
            while self._match(TokenType.COMMA):
                generic_args.append(self._parse_type_expr())
            self._expect_gt()

        # Array suffix []
        is_array = False
        if self._check(TokenType.LBRACKET) and self._peek(1).type == TokenType.RBRACKET:
            self._advance()
            self._advance()
            is_array = True

        # Pointer
        pointer_depth = 0
        while self._match(TokenType.STAR):
            pointer_depth += 1

        # Nullable: T? is sugar for T* (adds one pointer level)
        is_nullable = False
        if self._match(TokenType.QUESTION):
            pointer_depth += 1
            is_nullable = True

        return TypeExpr(base=base, generic_args=generic_args,
                        pointer_depth=pointer_depth, is_array=is_array,
                        is_const=has_const, is_nullable=is_nullable,
                        line=line, col=col)

    def _is_tuple_type_start(self) -> bool:
        """Check if ( starts a tuple type like (int, int)."""
        save = self.pos
        self.pos += 1
        tok = self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]
        if tok.type not in TYPE_KEYWORDS and tok.type != TokenType.IDENT:
            self.pos = save
            return False
        depth = 1
        self.pos += 1
        found_comma = False
        while self.pos < len(self.tokens) and depth > 0:
            t = self.tokens[self.pos]
            if t.type == TokenType.LPAREN:
                depth += 1
            elif t.type == TokenType.RPAREN:
                depth -= 1
            elif t.type == TokenType.COMMA and depth == 1:
                found_comma = True
                break
            self.pos += 1
        self.pos = save
        return found_comma

    def _parse_tuple_type(self, line: int, col: int) -> TypeExpr:
        """Parse tuple type: (type, type, ...)"""
        self._expect(TokenType.LPAREN)
        types = [self._parse_type_expr()]
        while self._match(TokenType.COMMA):
            types.append(self._parse_type_expr())
        self._expect(TokenType.RPAREN)
        return TypeExpr(base="Tuple", generic_args=types, line=line, col=col)

    def _is_generic_start(self) -> bool:
        """Look ahead to determine if '<' starts generic args or is a comparison."""
        save = self.pos
        depth = 1
        self.pos += 1

        while self.pos < len(self.tokens) and depth > 0:
            tok = self.tokens[self.pos]
            if tok.type == TokenType.LT:
                depth += 1
            elif tok.type == TokenType.GT:
                depth -= 1
            elif tok.type == TokenType.GT_GT:
                depth -= 2
                if depth <= 0:
                    self.pos += 1
                    break
            elif tok.type in (TokenType.SEMICOLON, TokenType.LBRACE,
                              TokenType.RBRACE, TokenType.EOF):
                self.pos = save
                return False
            self.pos += 1

        if depth <= 0:
            tok = self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]
            self.pos = save
            return tok.type in (TokenType.IDENT, TokenType.STAR, TokenType.LPAREN,
                                TokenType.RPAREN, TokenType.LBRACKET, TokenType.COMMA,
                                TokenType.GT, TokenType.GT_GT, TokenType.SEMICOLON,
                                TokenType.LBRACE, TokenType.EQ)

        self.pos = save
        return False

    # ---- Parameters ----

    def _parse_param_list(self) -> list[Param]:
        params = []
        if self._check(TokenType.RPAREN):
            return params
        params.append(self._parse_param())
        while self._match(TokenType.COMMA):
            params.append(self._parse_param())
        return params

    def _parse_param(self) -> Param:
        tok = self._peek()
        has_keep = False
        if self._check(TokenType.KEEP):
            has_keep = True
            self._advance()
        type_expr = self._parse_type_expr()
        name = self._expect(TokenType.IDENT, "parameter name").value
        if self._check(TokenType.LBRACKET):
            self._advance()
            if self._check(TokenType.RBRACKET):
                self._advance()
                type_expr.is_array = True
            else:
                size_expr = self._parse_expr()
                self._expect(TokenType.RBRACKET)
                type_expr.is_array = True
                type_expr.array_size = size_expr
        default = None
        if self._match(TokenType.EQ):
            default = self._parse_expr()
        return Param(type=type_expr, name=name, default=default,
                     keep=has_keep, line=tok.line, col=tok.col)
