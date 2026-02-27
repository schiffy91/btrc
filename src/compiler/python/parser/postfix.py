"""Postfix operators, cast detection, and sizeof parsing."""

from ..tokens import TokenType, TYPE_KEYWORDS
from ..ast_nodes import (
    CallExpr, CastExpr, FieldAccessExpr, IndexExpr,
    SizeofExpr, SizeofExprOp, SizeofType, UnaryExpr,
)


class PostfixMixin:

    _CAST_FOLLOW_TOKENS = (
        TokenType.IDENT, TokenType.INT_LIT, TokenType.FLOAT_LIT,
        TokenType.STRING_LIT, TokenType.CHAR_LIT, TokenType.LPAREN,
        TokenType.STAR, TokenType.AMP, TokenType.BANG, TokenType.TILDE,
        TokenType.MINUS, TokenType.PLUS_PLUS, TokenType.MINUS_MINUS,
        TokenType.SELF, TokenType.TRUE, TokenType.FALSE, TokenType.NULL,
        TokenType.NEW,
    )

    def _is_cast(self) -> bool:
        """Check if '(' starts a cast expression."""
        save = self.pos
        self.pos += 1
        tok = self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]

        if tok.type in TYPE_KEYWORDS:
            depth = 1
            self.pos += 1
            while self.pos < len(self.tokens) and depth > 0:
                t = self.tokens[self.pos]
                if t.type == TokenType.LPAREN:
                    depth += 1
                elif t.type == TokenType.RPAREN:
                    depth -= 1
                self.pos += 1
            if self.pos < len(self.tokens):
                next_tok = self.tokens[self.pos]
                self.pos = save
                return next_tok.type in self._CAST_FOLLOW_TOKENS
            self.pos = save
            return False

        if tok.type == TokenType.IDENT:
            self.pos += 1
            if self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.LT:
                depth = 1
                self.pos += 1
                while self.pos < len(self.tokens) and depth > 0:
                    t = self.tokens[self.pos]
                    if t.type == TokenType.LT:
                        depth += 1
                    elif t.type == TokenType.GT:
                        depth -= 1
                    self.pos += 1
            while self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.STAR:
                self.pos += 1
            if self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.QUESTION:
                self.pos += 1
            if self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.RPAREN:
                self.pos += 1
                if self.pos < len(self.tokens):
                    next_tok = self.tokens[self.pos]
                    self.pos = save
                    return next_tok.type in self._CAST_FOLLOW_TOKENS
            self.pos = save
            return False

        self.pos = save
        return False

    def _parse_cast(self) -> CastExpr:
        tok = self._expect(TokenType.LPAREN)
        target_type = self._parse_type_expr()
        self._expect(TokenType.RPAREN)
        expr = self._parse_unary()
        return CastExpr(target_type=target_type, expr=expr,
                        line=tok.line, col=tok.col)

    def _parse_sizeof(self) -> SizeofExpr:
        tok = self._expect(TokenType.SIZEOF)
        self._expect(TokenType.LPAREN)
        if self._is_type_start(self._peek()) and self._is_sizeof_type():
            operand = SizeofType(type=self._parse_type_expr())
        else:
            operand = SizeofExprOp(expr=self._parse_expr())
        self._expect(TokenType.RPAREN)
        return SizeofExpr(operand=operand, line=tok.line, col=tok.col)

    def _is_sizeof_type(self) -> bool:
        """Lookahead to check if sizeof contains a type."""
        save = self.pos
        tok = self.tokens[self.pos]
        if tok.type in TYPE_KEYWORDS and tok.type != TokenType.IDENT:
            self.pos = save
            return True
        if tok.type in TYPE_KEYWORDS:
            self.pos = save
            return True
        if tok.type == TokenType.IDENT:
            next_pos = self.pos + 1
            if next_pos < len(self.tokens):
                next_tok = self.tokens[next_pos]
                if next_tok.type in (TokenType.RPAREN, TokenType.STAR, TokenType.LT):
                    self.pos = save
                    return True
        self.pos = save
        return False

    def _parse_postfix(self):
        expr = self._parse_primary()

        while True:
            tok = self._peek()

            if tok.type == TokenType.LPAREN:
                self._advance()
                args = []
                if not self._check(TokenType.RPAREN):
                    args.append(self._parse_expr())
                    while self._match(TokenType.COMMA):
                        args.append(self._parse_expr())
                self._expect(TokenType.RPAREN)
                expr = CallExpr(callee=expr, args=args,
                                line=expr.line, col=expr.col)

            elif tok.type == TokenType.LBRACKET:
                self._advance()
                index = self._parse_expr()
                self._expect(TokenType.RBRACKET)
                expr = IndexExpr(obj=expr, index=index,
                                 line=expr.line, col=expr.col)

            elif tok.type == TokenType.DOT:
                self._advance()
                if self._check(TokenType.INT_LIT):
                    idx_tok = self._advance()
                    field_name = f"_{idx_tok.value}"
                else:
                    field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=False,
                                       line=expr.line, col=expr.col)

            elif tok.type == TokenType.QUESTION_DOT:
                self._advance()
                field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=True,
                                       optional=True, line=expr.line, col=expr.col)

            elif tok.type == TokenType.ARROW:
                self._advance()
                field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=True,
                                       line=expr.line, col=expr.col)

            elif tok.type == TokenType.PLUS_PLUS:
                self._advance()
                expr = UnaryExpr(op="++", operand=expr, prefix=False,
                                 line=expr.line, col=expr.col)

            elif tok.type == TokenType.MINUS_MINUS:
                self._advance()
                expr = UnaryExpr(op="--", operand=expr, prefix=False,
                                 line=expr.line, col=expr.col)

            else:
                break

        return expr
