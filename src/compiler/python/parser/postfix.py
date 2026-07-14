"""Postfix operators, cast detection, and sizeof parsing."""

from ..ast_nodes import (
    CallExpr,
    CastExpr,
    FieldAccessExpr,
    IndexExpr,
    SizeofExpr,
    SizeofExprOp,
    SizeofType,
    UnaryExpr,
)
from ..tokens import TokenType
from .type_lookahead import scan_type_expr


class PostfixMixin:
    _CAST_FOLLOW_TOKENS = (
        TokenType.IDENT,
        TokenType.INT_LIT,
        TokenType.FLOAT_LIT,
        TokenType.STRING_LIT,
        TokenType.CHAR_LIT,
        TokenType.FSTRING_LIT,
        TokenType.LPAREN,
        TokenType.SIZEOF,
        TokenType.STAR,
        TokenType.AMP,
        TokenType.BANG,
        TokenType.TILDE,
        TokenType.PLUS,
        TokenType.MINUS,
        TokenType.PLUS_PLUS,
        TokenType.MINUS_MINUS,
        TokenType.SELF,
        TokenType.TRUE,
        TokenType.FALSE,
        TokenType.NULL,
        TokenType.NEW,
        TokenType.SPAWN,
    )

    # For a parenthesized bare identifier `(a)` the follow tokens PLUS, MINUS,
    # STAR, and AMP are ambiguous: `(a) - 1` / `(a) + 1` is far more likely a
    # grouped expression and a binary operator than a cast of `-1` / `+1` to
    # type `a`. Only unambiguous follows (tokens that cannot continue a binary
    # expression) make a bare-identifier paren a cast. Explicit type syntax
    # ((int), (Foo*), (Vector<int>), (Foo?)) keeps the full follow set.
    _BARE_IDENT_CAST_FOLLOW = tuple(
        t for t in _CAST_FOLLOW_TOKENS if t not in (TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.AMP)
    )

    def _is_cast(self) -> bool:
        """Check if '(' starts a cast expression."""
        type_start = self.pos + 1
        type_end = scan_type_expr(self.tokens, type_start)
        if type_end is None or type_end >= len(self.tokens) or self.tokens[type_end].type != TokenType.RPAREN:
            return False
        follow_pos = type_end + 1
        if follow_pos >= len(self.tokens):
            return False
        bare_ident = self.tokens[type_start].type == TokenType.IDENT and type_end == type_start + 1
        follow = self._BARE_IDENT_CAST_FOLLOW if bare_ident else self._CAST_FOLLOW_TOKENS
        return self.tokens[follow_pos].type in follow

    def _parse_cast(self) -> CastExpr:
        tok = self._expect(TokenType.LPAREN)
        target_type = self._parse_type_expr()
        self._expect(TokenType.RPAREN)
        expr = self._parse_unary()
        return CastExpr(target_type=target_type, expr=expr, line=tok.line, col=tok.col)

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
        type_end = scan_type_expr(self.tokens, self.pos)
        return type_end is not None and type_end < len(self.tokens) and self.tokens[type_end].type == TokenType.RPAREN

    def _parse_postfix(self):
        expr = self._parse_primary()

        while True:
            tok = self._peek()

            if tok.type == TokenType.LPAREN:
                self._advance()
                args, arg_names = self._parse_arg_list()
                self._expect(TokenType.RPAREN)
                expr = CallExpr(callee=expr, args=args, arg_names=arg_names, line=expr.line, col=expr.col)

            elif tok.type == TokenType.LBRACKET:
                self._advance()
                index = self._parse_expr()
                self._expect(TokenType.RBRACKET)
                expr = IndexExpr(obj=expr, index=index, line=expr.line, col=expr.col)

            elif tok.type == TokenType.DOT:
                self._advance()
                if self._check(TokenType.INT_LIT):
                    idx_tok = self._advance()
                    field_name = f"_{idx_tok.value}"
                else:
                    field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=False, line=expr.line, col=expr.col)

            elif tok.type == TokenType.QUESTION_DOT:
                self._advance()
                field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(
                    obj=expr, field=field_name, arrow=True, optional=True, line=expr.line, col=expr.col
                )

            elif tok.type == TokenType.ARROW:
                self._advance()
                field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=True, line=expr.line, col=expr.col)

            elif tok.type == TokenType.PLUS_PLUS:
                self._advance()
                expr = UnaryExpr(op="++", operand=expr, prefix=False, line=expr.line, col=expr.col)

            elif tok.type == TokenType.MINUS_MINUS:
                self._advance()
                expr = UnaryExpr(op="--", operand=expr, prefix=False, line=expr.line, col=expr.col)

            else:
                break

        return expr
