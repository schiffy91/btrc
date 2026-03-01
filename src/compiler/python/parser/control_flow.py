"""Control flow statement parsing: if, while, for, switch, try/catch, etc."""

from ..ast_nodes import (
    CaseClause,
    CForStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    ExprStmt,
    ForInitExpr,
    ForInitVar,
    ForInStmt,
    IfStmt,
    ParallelForStmt,
    ReturnStmt,
    SwitchStmt,
    ThrowStmt,
    TryCatchStmt,
    VarDeclStmt,
    WhileStmt,
)
from ..tokens import TokenType


class ControlFlowMixin:

    def _parse_return_stmt(self) -> ReturnStmt:
        tok = self._expect(TokenType.RETURN)
        value = None
        if not self._check(TokenType.SEMICOLON):
            value = self._parse_expr()
        self._expect(TokenType.SEMICOLON)
        return ReturnStmt(value=value, line=tok.line, col=tok.col)

    def _parse_if_stmt(self) -> IfStmt:
        tok = self._expect(TokenType.IF)
        self._expect(TokenType.LPAREN)
        condition = self._parse_expr()
        self._expect(TokenType.RPAREN)
        then_block = self._parse_block()
        else_block = None
        if self._match(TokenType.ELSE):
            if self._check(TokenType.IF):
                else_block = ElseIf(if_stmt=self._parse_if_stmt())
            else:
                else_block = ElseBlock(body=self._parse_block())
        return IfStmt(condition=condition, then_block=then_block,
                      else_block=else_block, line=tok.line, col=tok.col)

    def _parse_while_stmt(self) -> WhileStmt:
        tok = self._expect(TokenType.WHILE)
        self._expect(TokenType.LPAREN)
        condition = self._parse_expr()
        self._expect(TokenType.RPAREN)
        body = self._parse_block()
        return WhileStmt(condition=condition, body=body, line=tok.line, col=tok.col)

    def _parse_do_while_stmt(self) -> DoWhileStmt:
        tok = self._expect(TokenType.DO)
        body = self._parse_block()
        self._expect(TokenType.WHILE)
        self._expect(TokenType.LPAREN)
        condition = self._parse_expr()
        self._expect(TokenType.RPAREN)
        self._expect(TokenType.SEMICOLON)
        return DoWhileStmt(body=body, condition=condition, line=tok.line, col=tok.col)

    def _parse_for_stmt(self):
        """Disambiguate for-in vs C for."""
        tok = self._expect(TokenType.FOR)

        # for-in: 'for' IDENT 'in' expr block
        if self._check(TokenType.IDENT) and self._peek(1).type == TokenType.IN:
            var_name = self._advance().value
            self._expect(TokenType.IN)
            iterable = self._parse_expr()
            body = self._parse_block()
            return ForInStmt(var_name=var_name, iterable=iterable,
                             body=body, line=tok.line, col=tok.col)

        # for-in (map): 'for' IDENT ',' IDENT 'in' expr block
        if (self._check(TokenType.IDENT) and self._peek(1).type == TokenType.COMMA
                and self._peek(2).type == TokenType.IDENT
                and self._peek(3).type == TokenType.IN):
            var_name = self._advance().value
            self._expect(TokenType.COMMA)
            var_name2 = self._advance().value
            self._expect(TokenType.IN)
            iterable = self._parse_expr()
            body = self._parse_block()
            return ForInStmt(var_name=var_name, var_name2=var_name2,
                             iterable=iterable, body=body,
                             line=tok.line, col=tok.col)

        # C for: 'for' '(' init ';' cond ';' update ')' block
        self._expect(TokenType.LPAREN)

        init = None
        if not self._check(TokenType.SEMICOLON):
            if self._is_var_decl_start():
                start = self._peek()
                if self._check(TokenType.VAR):
                    self._advance()
                    name = self._expect(TokenType.IDENT, "variable name").value
                    self._expect(TokenType.EQ, "'=' (var requires an initializer)")
                    init_val = self._parse_expr()
                    init = ForInitVar(var_decl=VarDeclStmt(
                        type=None, name=name, initializer=init_val,
                        line=start.line, col=start.col))
                else:
                    type_expr = self._parse_type_expr()
                    name = self._expect(TokenType.IDENT, "variable name").value
                    init_val = None
                    if self._match(TokenType.EQ):
                        init_val = self._parse_expr()
                    init = ForInitVar(var_decl=VarDeclStmt(
                        type=type_expr, name=name, initializer=init_val,
                        line=start.line, col=start.col))
            else:
                init = ForInitExpr(expression=self._parse_expr())
        self._expect(TokenType.SEMICOLON)

        condition = None
        if not self._check(TokenType.SEMICOLON):
            condition = self._parse_expr()
        self._expect(TokenType.SEMICOLON)

        update = None
        if not self._check(TokenType.RPAREN):
            update = self._parse_expr()
        self._expect(TokenType.RPAREN)

        body = self._parse_block()
        return CForStmt(init=init, condition=condition, update=update,
                        body=body, line=tok.line, col=tok.col)

    def _parse_parallel_for_stmt(self) -> ParallelForStmt:
        tok = self._expect(TokenType.PARALLEL)
        self._expect(TokenType.FOR)
        var_name = self._expect(TokenType.IDENT, "loop variable").value
        self._expect(TokenType.IN)
        iterable = self._parse_expr()
        body = self._parse_block()
        return ParallelForStmt(var_name=var_name, iterable=iterable,
                               body=body, line=tok.line, col=tok.col)

    def _parse_switch_stmt(self) -> SwitchStmt:
        tok = self._expect(TokenType.SWITCH)
        self._expect(TokenType.LPAREN)
        value = self._parse_expr()
        self._expect(TokenType.RPAREN)
        self._expect(TokenType.LBRACE)
        cases = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            cases.append(self._parse_case_clause())
        self._expect(TokenType.RBRACE)
        return SwitchStmt(value=value, cases=cases, line=tok.line, col=tok.col)

    def _parse_case_clause(self) -> CaseClause:
        tok = self._peek()
        value = None
        if self._match(TokenType.CASE):
            value = self._parse_expr()
        elif self._match(TokenType.DEFAULT):
            value = None
        else:
            raise self._error(f"Expected 'case' or 'default', got '{tok.value}'")
        self._expect(TokenType.COLON)
        body = []
        while not self._check(TokenType.CASE, TokenType.DEFAULT,
                               TokenType.RBRACE) and not self._at_end():
            body.append(self._parse_statement())
        return CaseClause(value=value, body=body, line=tok.line, col=tok.col)

    def _parse_try_catch(self) -> TryCatchStmt:
        tok = self._expect(TokenType.TRY)
        try_block = self._parse_block()
        self._expect(TokenType.CATCH)
        self._expect(TokenType.LPAREN)
        if self._is_type_start(self._peek()) and self._peek(1).type == TokenType.IDENT:
            self._parse_type_expr()  # optional type annotation (not stored in AST)
        catch_var = self._expect(TokenType.IDENT, "catch variable").value
        self._expect(TokenType.RPAREN)
        catch_block = self._parse_block()
        finally_block = None
        if self._match(TokenType.FINALLY):
            finally_block = self._parse_block()
        return TryCatchStmt(try_block=try_block, catch_var=catch_var,
                            catch_block=catch_block, finally_block=finally_block,
                            line=tok.line, col=tok.col)

    def _parse_throw(self) -> ThrowStmt:
        tok = self._expect(TokenType.THROW)
        expr = self._parse_expr()
        self._expect(TokenType.SEMICOLON)
        return ThrowStmt(expr=expr, line=tok.line, col=tok.col)

    def _parse_expr_stmt(self) -> ExprStmt:
        tok = self._peek()
        expr = self._parse_expr()
        self._expect(TokenType.SEMICOLON)
        return ExprStmt(expr=expr, line=tok.line, col=tok.col)
