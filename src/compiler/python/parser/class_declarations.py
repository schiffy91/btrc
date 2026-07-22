"""Class declaration and class-member parsing."""

from ..ast_nodes import ClassDecl, FieldDecl, MethodDecl
from ..tokens import TokenType


class ClassDeclarationsMixin:
    def _parse_class_decl(self, is_abstract: bool = False) -> ClassDecl:
        if is_abstract:
            self._expect(TokenType.ABSTRACT)
        tok = self._expect(TokenType.CLASS)
        name_tok = self._expect(TokenType.IDENT, "class name")
        name = name_tok.value

        generic_params = []
        if self._match(TokenType.LT):
            generic_params.append(self._expect(TokenType.IDENT, "generic param").value)
            while self._match(TokenType.COMMA):
                generic_params.append(self._expect(TokenType.IDENT, "generic param").value)
            self._expect_gt()

        parent = None
        if self._match(TokenType.EXTENDS):
            parent = self._expect(TokenType.IDENT, "parent class name").value

        interfaces = []
        if self._match(TokenType.IMPLEMENTS):
            interfaces.append(self._expect(TokenType.IDENT, "interface name").value)
            while self._match(TokenType.COMMA):
                interfaces.append(self._expect(TokenType.IDENT, "interface name").value)

        self._expect(TokenType.LBRACE)
        members = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            members.append(self._parse_class_member(allow_abstract=is_abstract))
        self._expect(TokenType.RBRACE)
        return ClassDecl(
            name=name,
            generic_params=generic_params,
            members=members,
            parent=parent,
            interfaces=interfaces,
            is_abstract=is_abstract,
            line=tok.line,
            col=tok.col,
            name_line=name_tok.line,
            name_col=name_tok.col,
        )

    def _parse_class_member(self, allow_abstract: bool = False):
        """Parse a class member: access specifier followed by its declaration."""
        tok = self._peek()
        if tok.type == TokenType.PUBLIC:
            access = "public"
            self._advance()
        elif tok.type == TokenType.PRIVATE:
            access = "private"
            self._advance()
        elif tok.type in (TokenType.CLASS, TokenType.STATIC):
            access = "class"
            self._advance()
        else:
            raise self._error(f"Expected access specifier (public/private/static), got '{tok.value}'")

        is_abstract_method = False
        if allow_abstract and self._check(TokenType.ABSTRACT):
            is_abstract_method = True
            self._advance()

        is_gpu = bool(self._match(TokenType.AT_GPU))
        keep_return = bool(self._match(TokenType.KEEP))
        type_expr = self._parse_type_expr()

        if self._check(TokenType.LPAREN):
            return self._parse_method_rest(
                access,
                type_expr,
                type_expr.base,
                is_gpu,
                tok.line,
                tok.col,
                type_expr.line,
                type_expr.col,
                is_constructor=True,
                is_abstract=is_abstract_method,
                keep_return=keep_return,
            )

        name_tok = self._expect(TokenType.IDENT, "member name")
        name = name_tok.value
        if self._check(TokenType.LT, TokenType.LPAREN):
            return self._parse_method_rest(
                access,
                type_expr,
                name,
                is_gpu,
                tok.line,
                tok.col,
                name_tok.line,
                name_tok.col,
                is_abstract=is_abstract_method,
                keep_return=keep_return,
            )
        self._parse_declarator_array_suffix(type_expr)
        if self._check(TokenType.LBRACE) and self._is_property_start():
            return self._parse_property(
                access,
                type_expr,
                name,
                tok.line,
                tok.col,
                name_tok.line,
                name_tok.col,
            )

        init = self._parse_expr() if self._match(TokenType.EQ) else None
        self._expect(TokenType.SEMICOLON)
        return FieldDecl(
            access=access,
            type=type_expr,
            name=name,
            initializer=init,
            line=tok.line,
            col=tok.col,
            name_line=name_tok.line,
            name_col=name_tok.col,
        )

    def _parse_method_rest(
        self,
        access,
        return_type,
        name,
        is_gpu,
        line,
        col,
        name_line,
        name_col,
        is_abstract: bool = False,
        keep_return: bool = False,
        is_constructor: bool = False,
    ) -> MethodDecl:
        generic_params = []
        if self._match(TokenType.LT):
            generic_params.append(self._expect(TokenType.IDENT, "generic param").value)
            while self._match(TokenType.COMMA):
                generic_params.append(self._expect(TokenType.IDENT, "generic param").value)
            self._expect_gt()
        self._expect(TokenType.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenType.RPAREN)
        if is_abstract:
            self._expect(TokenType.SEMICOLON)
            body = None
        else:
            body = self._parse_block()
        return MethodDecl(
            access=access,
            return_type=return_type,
            name=name,
            is_constructor=is_constructor,
            generic_params=generic_params,
            params=params,
            body=body,
            is_gpu=is_gpu,
            is_abstract=is_abstract,
            keep_return=keep_return,
            line=line,
            col=col,
            name_line=name_line,
            name_col=name_col,
        )
