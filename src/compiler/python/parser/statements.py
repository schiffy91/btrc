"""Statement dispatch, variable declaration detection and parsing."""

from ..ast_nodes import (
    Block,
    BreakStmt,
    ContinueStmt,
    DeleteStmt,
    KeepStmt,
    ReleaseStmt,
    VarDeclStmt,
)
from ..tokens import TokenType
from .type_lookahead import scan_type_expr


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
        if tok.type == TokenType.RELEASE:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return ReleaseStmt(expr=expr, line=tok.line, col=tok.col)
        if tok.type == TokenType.KEEP:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return KeepStmt(expr=expr, line=tok.line, col=tok.col)

        if self._is_var_decl_start():
            return self._parse_var_decl_stmt()

        return self._parse_expr_stmt()

    # ---- Variable declaration detection ----

    def _is_var_decl_start(self) -> bool:
        """Lookahead to determine if current position starts a variable declaration."""
        tok = self._peek()

        if tok.type == TokenType.VAR:
            return True
        return self._lookahead_is_var_decl()

    def _lookahead_is_var_decl(self) -> bool:
        """Recognize a complete type, name, and declaration boundary."""
        type_end = scan_type_expr(self.tokens, self.pos)
        if type_end is None or type_end >= len(self.tokens) or self.tokens[type_end].type != TokenType.IDENT:
            return False
        after_name = type_end + 1
        if after_name >= len(self.tokens):
            return False
        return self.tokens[after_name].type in (
            TokenType.EQ,
            TokenType.SEMICOLON,
            TokenType.LBRACKET,
        )

    # ---- Variable declaration ----

    def _parse_var_decl_stmt(self) -> VarDeclStmt:
        tok = self._peek()

        if self._check(TokenType.VAR):
            self._advance()
            name_tok = self._expect(TokenType.IDENT, "variable name")
            name = name_tok.value
            self._expect(TokenType.EQ, "'=' (var requires an initializer)")
            init = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return VarDeclStmt(
                type=None,
                name=name,
                initializer=init,
                line=tok.line,
                col=tok.col,
                name_line=name_tok.line,
                name_col=name_tok.col,
            )

        type_expr = self._parse_type_expr()
        name_tok = self._expect(TokenType.IDENT, "variable name")
        name = name_tok.value
        self._parse_declarator_array_suffix(type_expr)
        init = None
        if self._match(TokenType.EQ):
            init = self._parse_expr()
        self._expect(TokenType.SEMICOLON)
        return VarDeclStmt(
            type=type_expr,
            name=name,
            initializer=init,
            line=tok.line,
            col=tok.col,
            name_line=name_tok.line,
            name_col=name_tok.col,
        )
