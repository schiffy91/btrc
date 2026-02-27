"""Statement dispatch, variable declaration detection and parsing."""

from ..tokens import TokenType, TYPE_KEYWORDS
from ..ast_nodes import Block, BreakStmt, ContinueStmt, DeleteStmt, VarDeclStmt


class StatementsMixin:

    def _parse_block(self) -> Block:
        tok = self._expect(TokenType.LBRACE)
        stmts = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            stmts.append(self._parse_statement())
        self._expect(TokenType.RBRACE)
        return Block(statements=stmts, line=tok.line, col=tok.col)

    def _parse_statement(self):
        tok = self._peek()

        if tok.type == TokenType.LBRACE:
            return self._parse_block()
        if tok.type == TokenType.RETURN:
            return self._parse_return_stmt()
        if tok.type == TokenType.IF:
            return self._parse_if_stmt()
        if tok.type == TokenType.WHILE:
            return self._parse_while_stmt()
        if tok.type == TokenType.DO:
            return self._parse_do_while_stmt()
        if tok.type == TokenType.FOR:
            return self._parse_for_stmt()
        if tok.type == TokenType.PARALLEL:
            return self._parse_parallel_for_stmt()
        if tok.type == TokenType.SWITCH:
            return self._parse_switch_stmt()
        if tok.type == TokenType.BREAK:
            self._advance()
            self._expect(TokenType.SEMICOLON)
            return BreakStmt(line=tok.line, col=tok.col)
        if tok.type == TokenType.CONTINUE:
            self._advance()
            self._expect(TokenType.SEMICOLON)
            return ContinueStmt(line=tok.line, col=tok.col)
        if tok.type == TokenType.TRY:
            return self._parse_try_catch()
        if tok.type == TokenType.THROW:
            return self._parse_throw()
        if tok.type == TokenType.DELETE:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return DeleteStmt(expr=expr, line=tok.line, col=tok.col)

        if self._is_var_decl_start():
            return self._parse_var_decl_stmt()

        return self._parse_expr_stmt()

    # ---- Variable declaration detection ----

    def _is_var_decl_start(self) -> bool:
        """Lookahead to determine if current position starts a variable declaration."""
        tok = self._peek()

        if tok.type == TokenType.VAR:
            return True
        if tok.type in TYPE_KEYWORDS and tok.type not in (
                TokenType.CONST, TokenType.STATIC,
                TokenType.EXTERN, TokenType.VOLATILE):
            return self._lookahead_is_var_decl()
        if tok.type in (TokenType.CONST, TokenType.STATIC,
                        TokenType.EXTERN, TokenType.VOLATILE):
            return True
        if tok.type == TokenType.IDENT:
            return self._lookahead_is_var_decl()
        if tok.type == TokenType.LPAREN and self._is_tuple_type_start():
            return self._lookahead_is_var_decl()
        return False

    def _lookahead_is_var_decl(self) -> bool:
        """From current position, try to parse a type + name pattern."""
        if self.tokens[self.pos].type == TokenType.VAR:
            return True
        save = self.pos
        try:
            # Skip qualifiers
            while self.tokens[self.pos].type in (TokenType.CONST, TokenType.STATIC,
                                                   TokenType.EXTERN, TokenType.VOLATILE):
                self.pos += 1
            tok = self.tokens[self.pos]

            # Tuple type
            if tok.type == TokenType.LPAREN:
                depth = 1
                self.pos += 1
                while self.pos < len(self.tokens) and depth > 0:
                    t = self.tokens[self.pos]
                    if t.type == TokenType.LPAREN:
                        depth += 1
                    elif t.type == TokenType.RPAREN:
                        depth -= 1
                    self.pos += 1
                result = (self.pos < len(self.tokens) and
                          self.tokens[self.pos].type == TokenType.IDENT)
                self.pos = save
                return result
            elif tok.type in (TokenType.UNSIGNED, TokenType.SIGNED):
                self.pos += 1
                if self.tokens[self.pos].type in (TokenType.INT, TokenType.SHORT,
                                                    TokenType.LONG, TokenType.CHAR):
                    self.pos += 1
            elif tok.type in (TokenType.LONG, TokenType.SHORT):
                self.pos += 1
                if self.tokens[self.pos].type in (TokenType.INT, TokenType.LONG,
                                                    TokenType.DOUBLE):
                    self.pos += 1
            elif tok.type in (TokenType.STRUCT, TokenType.ENUM, TokenType.UNION):
                self.pos += 1
                if self.tokens[self.pos].type == TokenType.IDENT:
                    self.pos += 1
            elif tok.type in TYPE_KEYWORDS or tok.type == TokenType.IDENT:
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
                    elif t.type in (TokenType.SEMICOLON, TokenType.LBRACE, TokenType.EOF):
                        self.pos = save
                        return False
                    self.pos += 1
                if depth != 0:
                    self.pos = save
                    return False

            # Skip []
            if (self.pos < len(self.tokens) and
                self.tokens[self.pos].type == TokenType.LBRACKET and
                self.pos + 1 < len(self.tokens) and
                    self.tokens[self.pos + 1].type == TokenType.RBRACKET):
                self.pos += 2

            # Skip pointers
            while self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.STAR:
                self.pos += 1

            result = (self.pos < len(self.tokens) and
                      self.tokens[self.pos].type == TokenType.IDENT)
            self.pos = save
            return result
        except IndexError:
            self.pos = save
            return False

    # ---- Variable declaration ----

    def _parse_var_decl_stmt(self) -> VarDeclStmt:
        tok = self._peek()

        if self._check(TokenType.VAR):
            self._advance()
            name = self._expect(TokenType.IDENT, "variable name").value
            self._expect(TokenType.EQ, "'=' (var requires an initializer)")
            init = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return VarDeclStmt(type=None, name=name, initializer=init,
                               line=tok.line, col=tok.col)

        type_expr = self._parse_type_expr()
        name = self._expect(TokenType.IDENT, "variable name").value
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
        init = None
        if self._match(TokenType.EQ):
            init = self._parse_expr()
        self._expect(TokenType.SEMICOLON)
        return VarDeclStmt(type=type_expr, name=name, initializer=init,
                           line=tok.line, col=tok.col)
