"""Primary expression parsing: literals, identifiers, new, list, map, brace."""

from ..tokens import TokenType
from ..ast_nodes import (
    BoolLiteral, BraceInitializer, CharLiteral, FloatLiteral,
    Identifier, IntLiteral, ListLiteral, MapEntry, MapLiteral,
    NewExpr, NullLiteral, SelfExpr, SpawnExpr, StringLiteral,
    SuperExpr, TupleLiteral,
)


class PrimaryMixin:

    def _parse_primary(self):
        tok = self._peek()

        if tok.type == TokenType.INT_LIT:
            self._advance()
            return IntLiteral(value=int(tok.value, 0), raw=tok.value,
                              line=tok.line, col=tok.col)

        if tok.type == TokenType.FLOAT_LIT:
            self._advance()
            raw = tok.value
            fval = raw.rstrip('fF')
            return FloatLiteral(value=float(fval), raw=raw,
                                line=tok.line, col=tok.col)

        if tok.type == TokenType.STRING_LIT:
            self._advance()
            return StringLiteral(value=tok.value, line=tok.line, col=tok.col)

        if tok.type == TokenType.CHAR_LIT:
            self._advance()
            return CharLiteral(value=tok.value, line=tok.line, col=tok.col)

        if tok.type == TokenType.FSTRING_LIT:
            self._advance()
            return self._parse_fstring(tok)

        if tok.type == TokenType.TRUE:
            self._advance()
            return BoolLiteral(value=True, line=tok.line, col=tok.col)
        if tok.type == TokenType.FALSE:
            self._advance()
            return BoolLiteral(value=False, line=tok.line, col=tok.col)

        if tok.type == TokenType.NULL:
            self._advance()
            return NullLiteral(line=tok.line, col=tok.col)

        if tok.type == TokenType.SELF:
            self._advance()
            return SelfExpr(line=tok.line, col=tok.col)

        if tok.type == TokenType.SUPER:
            self._advance()
            return SuperExpr(line=tok.line, col=tok.col)

        if tok.type == TokenType.NEW:
            return self._parse_new_expr()

        if tok.type == TokenType.SPAWN:
            return self._parse_spawn_expr()

        # Verbose lambda: type function(params) { body }
        if self._is_type_start(tok) and self._is_verbose_lambda():
            return self._parse_verbose_lambda()

        # Parenthesized expression, tuple literal, or arrow lambda
        if tok.type == TokenType.LPAREN:
            if self._is_arrow_lambda():
                return self._parse_arrow_lambda()
            self._advance()
            expr = self._parse_expr()
            if self._match(TokenType.COMMA):
                elements = [expr]
                elements.append(self._parse_expr())
                while self._match(TokenType.COMMA):
                    elements.append(self._parse_expr())
                self._expect(TokenType.RPAREN)
                return TupleLiteral(elements=elements, line=tok.line, col=tok.col)
            self._expect(TokenType.RPAREN)
            return expr

        if tok.type == TokenType.LBRACKET:
            return self._parse_list_literal()

        if tok.type == TokenType.LBRACE and self._is_map_literal():
            return self._parse_map_literal()

        if tok.type == TokenType.LBRACE:
            return self._parse_brace_initializer()

        if tok.type == TokenType.IDENT:
            self._advance()
            return Identifier(name=tok.value, line=tok.line, col=tok.col)

        raise self._error(f"Unexpected token '{tok.value}' in expression")

    # ---- Compound literals ----

    def _parse_new_expr(self) -> NewExpr:
        tok = self._expect(TokenType.NEW)
        type_expr = self._parse_type_expr()
        self._expect(TokenType.LPAREN)
        args = []
        if not self._check(TokenType.RPAREN):
            args.append(self._parse_expr())
            while self._match(TokenType.COMMA):
                args.append(self._parse_expr())
        self._expect(TokenType.RPAREN)
        return NewExpr(type=type_expr, args=args, line=tok.line, col=tok.col)

    def _parse_spawn_expr(self) -> SpawnExpr:
        tok = self._expect(TokenType.SPAWN)
        self._expect(TokenType.LPAREN)
        fn = self._parse_expr()
        self._expect(TokenType.RPAREN)
        return SpawnExpr(fn=fn, line=tok.line, col=tok.col)

    def _parse_list_literal(self) -> ListLiteral:
        tok = self._expect(TokenType.LBRACKET)
        elements = []
        if not self._check(TokenType.RBRACKET):
            elements.append(self._parse_expr())
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACKET):
                    break
                elements.append(self._parse_expr())
        self._expect(TokenType.RBRACKET)
        return ListLiteral(elements=elements, line=tok.line, col=tok.col)

    def _is_map_literal(self) -> bool:
        """Check if { starts a map literal (has expr : expr pattern)."""
        if self._peek(1).type == TokenType.RBRACE:
            return False
        save = self.pos
        self.pos += 1
        depth = 0
        while self.pos < len(self.tokens):
            t = self.tokens[self.pos]
            if t.type == TokenType.COLON and depth == 0:
                self.pos = save
                return True
            if t.type in (TokenType.LPAREN, TokenType.LBRACKET, TokenType.LBRACE):
                depth += 1
            elif t.type in (TokenType.RPAREN, TokenType.RBRACKET, TokenType.RBRACE):
                if depth == 0:
                    break
                depth -= 1
            elif t.type == TokenType.SEMICOLON:
                break
            self.pos += 1
        self.pos = save
        return False

    def _parse_map_literal(self) -> MapLiteral:
        tok = self._expect(TokenType.LBRACE)
        entries = []
        if not self._check(TokenType.RBRACE):
            key = self._parse_expr()
            self._expect(TokenType.COLON)
            value = self._parse_expr()
            entries.append(MapEntry(key=key, value=value))
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACE):
                    break
                key = self._parse_expr()
                self._expect(TokenType.COLON)
                value = self._parse_expr()
                entries.append(MapEntry(key=key, value=value))
        self._expect(TokenType.RBRACE)
        return MapLiteral(entries=entries, line=tok.line, col=tok.col)

    def _parse_brace_initializer(self) -> BraceInitializer:
        """Parse C-style brace initializer: {expr, expr, ...}"""
        tok = self._expect(TokenType.LBRACE)
        elements = []
        if not self._check(TokenType.RBRACE):
            elements.append(self._parse_expr())
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACE):
                    break
                elements.append(self._parse_expr())
        self._expect(TokenType.RBRACE)
        return BraceInitializer(elements=elements, line=tok.line, col=tok.col)
