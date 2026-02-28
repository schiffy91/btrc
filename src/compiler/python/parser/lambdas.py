"""Lambda expression and f-string parsing."""

from ..tokens import TokenType, TYPE_KEYWORDS
from ..ast_nodes import (
    FStringExpr, FStringLiteral, FStringText,
    LambdaBlock, LambdaExpr, LambdaExprBody,
)


class LambdasMixin:

    def _is_verbose_lambda(self) -> bool:
        """Check if current position starts a verbose lambda: type function(...)"""
        save = self.pos
        try:
            while self.tokens[self.pos].type in (TokenType.CONST, TokenType.STATIC,
                                                   TokenType.EXTERN, TokenType.VOLATILE):
                self.pos += 1
            tok = self.tokens[self.pos]
            if tok.type in TYPE_KEYWORDS or tok.type == TokenType.IDENT:
                self.pos += 1
            else:
                self.pos = save
                return False
            # Skip generic args
            if self.tokens[self.pos].type == TokenType.LT:
                depth = 1
                self.pos += 1
                while self.pos < len(self.tokens) and depth > 0:
                    t = self.tokens[self.pos]
                    if t.type == TokenType.LT:
                        depth += 1
                    elif t.type == TokenType.GT:
                        depth -= 1
                    elif t.type == TokenType.GT_GT:
                        depth -= 2
                    self.pos += 1
            # Skip pointers
            while self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.STAR:
                self.pos += 1
            result = (self.pos < len(self.tokens) and
                      self.tokens[self.pos].type == TokenType.FUNCTION)
            self.pos = save
            return result
        except IndexError:
            self.pos = save
            return False

    def _parse_verbose_lambda(self) -> LambdaExpr:
        """Parse verbose lambda: type function(params) { body }"""
        tok = self._peek()
        return_type = self._parse_type_expr()
        self._expect(TokenType.FUNCTION, "'function'")
        self._expect(TokenType.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenType.RPAREN)
        body = LambdaBlock(body=self._parse_block())
        return LambdaExpr(return_type=return_type, params=params, body=body,
                          captures=[], line=tok.line, col=tok.col)

    def _is_arrow_lambda(self) -> bool:
        """Check if '(' starts an arrow lambda: (type name, ...) => ..."""
        save = self.pos
        try:
            self.pos += 1
            if self.tokens[self.pos].type == TokenType.RPAREN:
                self.pos += 1
                result = (self.pos < len(self.tokens) and
                          self.tokens[self.pos].type == TokenType.FAT_ARROW)
                self.pos = save
                return result
            tok = self.tokens[self.pos]
            if tok.type not in TYPE_KEYWORDS and tok.type != TokenType.IDENT:
                self.pos = save
                return False
            depth = 1
            self.pos += 1
            while self.pos < len(self.tokens) and depth > 0:
                t = self.tokens[self.pos]
                if t.type == TokenType.LPAREN:
                    depth += 1
                elif t.type == TokenType.RPAREN:
                    depth -= 1
                elif t.type in (TokenType.SEMICOLON, TokenType.LBRACE, TokenType.EOF):
                    self.pos = save
                    return False
                self.pos += 1
            result = (self.pos < len(self.tokens) and
                      self.tokens[self.pos].type == TokenType.FAT_ARROW)
            self.pos = save
            return result
        except IndexError:
            self.pos = save
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
        return LambdaExpr(return_type=None, params=params, body=body,
                          captures=[], line=tok.line, col=tok.col)

    # ---- F-string parsing ----

    def _parse_fstring(self, tok) -> FStringLiteral:
        """Parse f-string content into text and expression parts."""
        raw = tok.value
        parts = []
        i = 0
        text_buf = []
        while i < len(raw):
            ch = raw[i]
            if ch == '{':
                if i + 1 < len(raw) and raw[i + 1] == '{':
                    text_buf.append('{')
                    i += 2
                    continue
                if text_buf:
                    parts.append(FStringText(text=''.join(text_buf)))
                    text_buf = []
                i += 1
                depth = 1
                expr_chars = []
                while i < len(raw) and depth > 0:
                    if raw[i] == '{':
                        depth += 1
                    elif raw[i] == '}':
                        depth -= 1
                        if depth == 0:
                            break
                    expr_chars.append(raw[i])
                    i += 1
                i += 1
                expr_src = ''.join(expr_chars)
                expr_src = expr_src.replace('\\"', '"')
                from ..lexer import Lexer
                sub_tokens = Lexer(expr_src + ";").tokenize()
                # Late import to avoid circular dependency
                from .parser import Parser
                sub_parser = Parser(sub_tokens)
                expr_node = sub_parser._parse_expr()
                parts.append(FStringExpr(expression=expr_node))
            elif ch == '}':
                if i + 1 < len(raw) and raw[i + 1] == '}':
                    text_buf.append('}')
                    i += 2
                    continue
                text_buf.append(ch)
                i += 1
            elif ch == '\\':
                text_buf.append(ch)
                if i + 1 < len(raw):
                    i += 1
                    text_buf.append(raw[i])
                i += 1
            else:
                text_buf.append(ch)
                i += 1
        if text_buf:
            parts.append(FStringText(text=''.join(text_buf)))
        return FStringLiteral(parts=parts, line=tok.line, col=tok.col)
