"""Lambda expression and f-string parsing."""

from ..ast_nodes import (
    FStringExpr,
    FStringLiteral,
    FStringText,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
)
from ..tokens import TokenType
from .type_lookahead import scan_type_expr


class LambdasMixin:
    def _is_verbose_lambda(self) -> bool:
        """Check if current position starts a verbose lambda: type function(...)"""
        type_end = scan_type_expr(self.tokens, self.pos)
        return type_end is not None and type_end < len(self.tokens) and self.tokens[type_end].type == TokenType.FUNCTION

    def _parse_verbose_lambda(self) -> LambdaExpr:
        """Parse verbose lambda: type function(params) { body }"""
        tok = self._peek()
        return_type = self._parse_type_expr()
        self._expect(TokenType.FUNCTION, "'function'")
        self._expect(TokenType.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenType.RPAREN)
        body = LambdaBlock(body=self._parse_block())
        return LambdaExpr(return_type=return_type, params=params, body=body, captures=[], line=tok.line, col=tok.col)

    def _is_arrow_lambda(self) -> bool:
        """Check if '(' starts an arrow lambda: (type name, ...) => ..."""
        if not self._check(TokenType.LPAREN):
            return False
        depth = 0
        pos = self.pos
        while pos < len(self.tokens):
            token_type = self.tokens[pos].type
            if token_type == TokenType.LPAREN:
                depth += 1
            elif token_type == TokenType.RPAREN:
                depth -= 1
                if depth == 0:
                    return pos + 1 < len(self.tokens) and self.tokens[pos + 1].type == TokenType.FAT_ARROW
            elif token_type == TokenType.EOF:
                return False
            pos += 1
        return False

    def _parse_arrow_lambda(self) -> LambdaExpr:
        """Parse arrow lambda: (params) => expr  or  (params) => { body }"""
        tok = self._peek()
        self._expect(TokenType.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenType.RPAREN)
        self._expect(TokenType.FAT_ARROW, "'=>'")
        if self._check(TokenType.LBRACE):
            body = LambdaBlock(body=self._parse_block())
        else:
            expr = self._parse_expr()
            body = LambdaExprBody(expression=expr)
        return LambdaExpr(return_type=None, params=params, body=body, captures=[], line=tok.line, col=tok.col)

    # ---- F-string parsing ----

    def _parse_fstring(self, tok) -> FStringLiteral:
        """Parse f-string content into text and expression parts."""
        raw = tok.value
        parts = []
        i = 0
        text_buf = []
        while i < len(raw):
            ch = raw[i]
            if ch == "{":
                if i + 1 < len(raw) and raw[i + 1] == "{":
                    text_buf.append("{")
                    i += 2
                    continue
                if text_buf:
                    parts.append(FStringText(text="".join(text_buf)))
                    text_buf = []
                i += 1
                depth = 1
                expr_chars = []
                while i < len(raw) and depth > 0:
                    if raw[i] == "{":
                        depth += 1
                    elif raw[i] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    expr_chars.append(raw[i])
                    i += 1
                i += 1
                expr_src = "".join(expr_chars)
                expr_src = expr_src.replace('\\"', '"')
                from ..lexer import Lexer

                sub_tokens = Lexer(expr_src + ";").tokenize()
                # Late import to avoid circular dependency
                from .parser import Parser

                sub_parser = Parser(sub_tokens)
                expr_node = sub_parser._parse_expr()
                sub_parser._expect(TokenType.SEMICOLON)
                parts.append(FStringExpr(expression=expr_node))
            elif ch == "}":
                if i + 1 < len(raw) and raw[i + 1] == "}":
                    text_buf.append("}")
                    i += 2
                    continue
                text_buf.append(ch)
                i += 1
            elif ch == "\\":
                text_buf.append(ch)
                if i + 1 < len(raw):
                    i += 1
                    text_buf.append(raw[i])
                i += 1
            else:
                text_buf.append(ch)
                i += 1
        if text_buf:
            parts.append(FStringText(text="".join(text_buf)))
        return FStringLiteral(parts=parts, line=tok.line, col=tok.col)
