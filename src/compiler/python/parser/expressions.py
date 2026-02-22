"""Expression parsing: precedence climbing from assignment to unary."""

from ..ast_nodes import AssignExpr, BinaryExpr, TernaryExpr, UnaryExpr
from ..tokens import TokenType


class ExpressionsMixin:

    def _parse_expr(self):
        return self._parse_assignment()

    def _parse_assignment(self):
        left = self._parse_ternary()
        assign_ops = {
            TokenType.EQ, TokenType.PLUS_EQ, TokenType.MINUS_EQ,
            TokenType.STAR_EQ, TokenType.SLASH_EQ, TokenType.PERCENT_EQ,
            TokenType.AMP_EQ, TokenType.PIPE_EQ, TokenType.CARET_EQ,
            TokenType.LT_LT_EQ, TokenType.GT_GT_EQ,
        }
        if self._peek().type in assign_ops:
            op_tok = self._advance()
            right = self._parse_assignment()
            return AssignExpr(target=left, op=op_tok.value, value=right,
                              line=left.line, col=left.col)
        return left

    def _parse_ternary(self):
        expr = self._parse_null_coalesce()
        if self._match(TokenType.QUESTION):
            true_expr = self._parse_expr()
            self._expect(TokenType.COLON)
            false_expr = self._parse_ternary()
            return TernaryExpr(condition=expr, true_expr=true_expr,
                               false_expr=false_expr, line=expr.line, col=expr.col)
        return expr

    def _parse_null_coalesce(self):
        left = self._parse_logical_or()
        while self._match(TokenType.QUESTION_QUESTION):
            right = self._parse_logical_or()
            left = BinaryExpr(left=left, op="??", right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_logical_or(self):
        left = self._parse_logical_and()
        while self._match(TokenType.PIPE_PIPE):
            right = self._parse_logical_and()
            left = BinaryExpr(left=left, op="||", right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_logical_and(self):
        left = self._parse_bitwise_or()
        while self._match(TokenType.AMP_AMP):
            right = self._parse_bitwise_or()
            left = BinaryExpr(left=left, op="&&", right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_bitwise_or(self):
        left = self._parse_bitwise_xor()
        while self._match(TokenType.PIPE):
            right = self._parse_bitwise_xor()
            left = BinaryExpr(left=left, op="|", right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_bitwise_xor(self):
        left = self._parse_bitwise_and()
        while self._match(TokenType.CARET):
            right = self._parse_bitwise_and()
            left = BinaryExpr(left=left, op="^", right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_bitwise_and(self):
        left = self._parse_equality()
        while self._match(TokenType.AMP):
            right = self._parse_equality()
            left = BinaryExpr(left=left, op="&", right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_equality(self):
        left = self._parse_relational()
        while self._check(TokenType.EQ_EQ, TokenType.BANG_EQ):
            op = self._advance().value
            right = self._parse_relational()
            left = BinaryExpr(left=left, op=op, right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_relational(self):
        left = self._parse_shift()
        while self._check(TokenType.LT, TokenType.GT, TokenType.LT_EQ, TokenType.GT_EQ):
            op = self._advance().value
            right = self._parse_shift()
            left = BinaryExpr(left=left, op=op, right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_shift(self):
        left = self._parse_additive()
        while self._check(TokenType.LT_LT, TokenType.GT_GT):
            op = self._advance().value
            right = self._parse_additive()
            left = BinaryExpr(left=left, op=op, right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_additive(self):
        left = self._parse_multiplicative()
        while self._check(TokenType.PLUS, TokenType.MINUS):
            op = self._advance().value
            right = self._parse_multiplicative()
            left = BinaryExpr(left=left, op=op, right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_multiplicative(self):
        left = self._parse_unary()
        while self._check(TokenType.STAR, TokenType.SLASH, TokenType.PERCENT):
            op = self._advance().value
            right = self._parse_unary()
            left = BinaryExpr(left=left, op=op, right=right,
                              line=left.line, col=left.col)
        return left

    def _parse_unary(self):
        tok = self._peek()

        if tok.type in (TokenType.BANG, TokenType.TILDE):
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op=tok.value, operand=operand, prefix=True,
                             line=tok.line, col=tok.col)
        if tok.type == TokenType.MINUS:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="-", operand=operand, prefix=True,
                             line=tok.line, col=tok.col)
        if tok.type == TokenType.PLUS_PLUS:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="++", operand=operand, prefix=True,
                             line=tok.line, col=tok.col)
        if tok.type == TokenType.MINUS_MINUS:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="--", operand=operand, prefix=True,
                             line=tok.line, col=tok.col)
        if tok.type == TokenType.STAR:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="*", operand=operand, prefix=True,
                             line=tok.line, col=tok.col)
        if tok.type == TokenType.AMP:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="&", operand=operand, prefix=True,
                             line=tok.line, col=tok.col)
        if tok.type == TokenType.SIZEOF:
            return self._parse_sizeof()
        if tok.type == TokenType.LPAREN and self._is_cast():
            return self._parse_cast()

        return self._parse_postfix()
