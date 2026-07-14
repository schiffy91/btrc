"""Struct and interface declaration parsing."""

from ..ast_nodes import FieldDef, InterfaceDecl, MethodSig, StructDecl
from ..tokens import TokenType


class AggregateDeclarationsMixin:
    def _parse_struct_decl(self) -> StructDecl:
        tok = self._expect(TokenType.STRUCT)
        name = ""
        name_line, name_col = tok.line, tok.col
        if self._check(TokenType.IDENT):
            name_tok = self._advance()
            name = name_tok.value
            name_line, name_col = name_tok.line, name_tok.col
        if not self._match(TokenType.LBRACE):
            self._expect(TokenType.SEMICOLON)
            return StructDecl(
                name=name,
                fields=[],
                is_forward=True,
                line=tok.line,
                col=tok.col,
                name_line=name_line,
                name_col=name_col,
            )

        fields = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            field_type = self._parse_type_expr()
            name_tok = self._expect(TokenType.IDENT, "field name")
            self._parse_declarator_array_suffix(field_type)
            fields.append(
                FieldDef(
                    type=field_type,
                    name=name_tok.value,
                    line=name_tok.line,
                    col=name_tok.col,
                )
            )
            self._expect(TokenType.SEMICOLON)
        self._expect(TokenType.RBRACE)
        self._expect(TokenType.SEMICOLON)
        return StructDecl(
            name=name,
            fields=fields,
            is_forward=False,
            line=tok.line,
            col=tok.col,
            name_line=name_line,
            name_col=name_col,
        )

    def _parse_interface_decl(self) -> InterfaceDecl:
        tok = self._expect(TokenType.INTERFACE)
        name_tok = self._expect(TokenType.IDENT, "interface name")

        generic_params = []
        if self._match(TokenType.LT):
            generic_params.append(self._expect(TokenType.IDENT, "generic param").value)
            while self._match(TokenType.COMMA):
                generic_params.append(self._expect(TokenType.IDENT, "generic param").value)
            self._expect_gt()

        parent = None
        if self._match(TokenType.EXTENDS):
            parent = self._expect(TokenType.IDENT, "parent interface name").value
        self._expect(TokenType.LBRACE)
        methods = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            keep_return = bool(self._match(TokenType.KEEP))
            return_type = self._parse_type_expr()
            method_name = self._expect(TokenType.IDENT, "method name")
            self._expect(TokenType.LPAREN)
            params = self._parse_param_list()
            self._expect(TokenType.RPAREN)
            self._expect(TokenType.SEMICOLON)
            methods.append(
                MethodSig(
                    return_type=return_type,
                    name=method_name.value,
                    params=params,
                    keep_return=keep_return,
                    line=return_type.line,
                    col=return_type.col,
                    name_line=method_name.line,
                    name_col=method_name.col,
                )
            )
        self._expect(TokenType.RBRACE)
        return InterfaceDecl(
            name=name_tok.value,
            methods=methods,
            parent=parent,
            generic_params=generic_params,
            line=tok.line,
            col=tok.col,
            name_line=name_tok.line,
            name_col=name_tok.col,
        )
