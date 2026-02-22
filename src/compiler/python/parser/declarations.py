"""Top-level dispatch and class/struct/interface declaration parsing."""

from ..ast_nodes import (
    ClassDecl,
    FieldDecl,
    FieldDef,
    InterfaceDecl,
    MethodDecl,
    MethodSig,
    PreprocessorDirective,
    StructDecl,
)
from ..tokens import TokenType


class DeclarationsMixin:

    def _parse_top_level_item(self):
        tok = self._peek()

        if tok.type == TokenType.PREPROCESSOR:
            return self._parse_preprocessor()

        is_gpu = False
        keep_return = False
        if tok.type == TokenType.AT_GPU:
            is_gpu = True
            self._advance()
            tok = self._peek()
        if tok.type == TokenType.KEEP:
            keep_return = True
            self._advance()
            tok = self._peek()

        if tok.type == TokenType.INTERFACE and not is_gpu and not keep_return:
            return self._parse_interface_decl()

        if tok.type == TokenType.ABSTRACT and not is_gpu and not keep_return:
            next_tok = self._peek(1)
            if next_tok.type == TokenType.CLASS:
                return self._parse_class_decl(is_abstract=True)

        if tok.type == TokenType.CLASS and not is_gpu and not keep_return:
            next_tok = self._peek(1)
            if next_tok.type == TokenType.IDENT:
                after = self._peek(2)
                if after.type in (TokenType.LBRACE, TokenType.LT, TokenType.EXTENDS,
                                  TokenType.IMPLEMENTS):
                    return self._parse_class_decl()

        if tok.type == TokenType.STRUCT and not is_gpu and not keep_return:
            next_tok = self._peek(1)
            if next_tok.type == TokenType.IDENT:
                after = self._peek(2)
                if after.type in (TokenType.LBRACE, TokenType.SEMICOLON):
                    return self._parse_struct_decl()
            elif next_tok.type == TokenType.LBRACE:
                return self._parse_struct_decl()

        if tok.type == TokenType.ENUM and not is_gpu and not keep_return:
            next_tok = self._peek(1)
            if next_tok.type == TokenType.CLASS:
                return self._parse_rich_enum_decl()
            return self._parse_enum_decl()

        if tok.type == TokenType.TYPEDEF and not is_gpu and not keep_return:
            return self._parse_typedef_decl()

        if self._is_type_start(tok):
            return self._parse_function_or_var_decl(is_gpu, keep_return=keep_return)

        raise self._error(f"Unexpected token '{tok.value}' at top level")

    def _parse_preprocessor(self) -> PreprocessorDirective:
        tok = self._advance()
        return PreprocessorDirective(text=tok.value, line=tok.line, col=tok.col)

    # ---- Class declaration ----

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
        return ClassDecl(name=name, generic_params=generic_params,
                         members=members, parent=parent, interfaces=interfaces,
                         is_abstract=is_abstract, line=tok.line, col=tok.col)

    def _parse_class_member(self, allow_abstract: bool = False):
        """Parse a class member: access_spec (field | method)."""
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
            raise self._error(
                f"Expected access specifier (public/private/static), got '{tok.value}'")

        is_abstract_method = False
        if allow_abstract and self._check(TokenType.ABSTRACT):
            is_abstract_method = True
            self._advance()

        is_gpu = False
        if self._check(TokenType.AT_GPU):
            is_gpu = True
            self._advance()

        keep_return = False
        if self._check(TokenType.KEEP):
            keep_return = True
            self._advance()

        type_expr = self._parse_type_expr()

        # Constructor: if next is '(' instead of IDENT, the "type" is the name
        if self._check(TokenType.LPAREN):
            name = type_expr.base
            return self._parse_method_rest(access, type_expr, name, is_gpu,
                                           tok.line, tok.col,
                                           is_abstract=is_abstract_method,
                                           keep_return=keep_return)

        name_tok = self._expect(TokenType.IDENT, "member name")
        name = name_tok.value

        if self._check(TokenType.LPAREN):
            return self._parse_method_rest(access, type_expr, name, is_gpu,
                                           tok.line, tok.col,
                                           is_abstract=is_abstract_method,
                                           keep_return=keep_return)
        elif self._check(TokenType.LBRACE) and self._is_property_start():
            return self._parse_property(access, type_expr, name, tok.line, tok.col)
        else:
            init = None
            if self._match(TokenType.EQ):
                init = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return FieldDecl(access=access, type=type_expr, name=name,
                             initializer=init, line=tok.line, col=tok.col)

    def _parse_method_rest(self, access, return_type, name, is_gpu, line, col,
                           is_abstract: bool = False,
                           keep_return: bool = False) -> MethodDecl:
        self._expect(TokenType.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenType.RPAREN)
        if is_abstract:
            self._expect(TokenType.SEMICOLON)
            body = None
        else:
            body = self._parse_block()
        return MethodDecl(access=access, return_type=return_type, name=name,
                          params=params, body=body, is_gpu=is_gpu,
                          is_abstract=is_abstract, keep_return=keep_return,
                          line=line, col=col)

    # ---- Struct declaration ----

    def _parse_struct_decl(self) -> StructDecl:
        tok = self._expect(TokenType.STRUCT)
        name = ""
        if self._check(TokenType.IDENT):
            name = self._advance().value
        if self._match(TokenType.LBRACE):
            fields = []
            while not self._check(TokenType.RBRACE) and not self._at_end():
                ftype = self._parse_type_expr()
                fname = self._expect(TokenType.IDENT, "field name").value
                if self._check(TokenType.LBRACKET):
                    self._advance()
                    if self._check(TokenType.RBRACKET):
                        self._advance()
                        ftype.is_array = True
                    else:
                        size_expr = self._parse_expr()
                        self._expect(TokenType.RBRACKET)
                        ftype.is_array = True
                        ftype.array_size = size_expr
                fields.append(FieldDef(type=ftype, name=fname))
                self._expect(TokenType.SEMICOLON)
            self._expect(TokenType.RBRACE)
            self._expect(TokenType.SEMICOLON)
            return StructDecl(name=name, fields=fields, line=tok.line, col=tok.col)
        else:
            self._expect(TokenType.SEMICOLON)
            return StructDecl(name=name, fields=[], line=tok.line, col=tok.col)

    # ---- Interface declaration ----

    def _parse_interface_decl(self) -> InterfaceDecl:
        tok = self._expect(TokenType.INTERFACE)
        name = self._expect(TokenType.IDENT, "interface name").value

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
            sig_keep = False
            if self._check(TokenType.KEEP):
                sig_keep = True
                self._advance()
            ret_type = self._parse_type_expr()
            mname = self._expect(TokenType.IDENT, "method name").value
            self._expect(TokenType.LPAREN)
            params = self._parse_param_list()
            self._expect(TokenType.RPAREN)
            self._expect(TokenType.SEMICOLON)
            methods.append(MethodSig(return_type=ret_type, name=mname,
                                     params=params, keep_return=sig_keep,
                                     line=tok.line, col=tok.col))
        self._expect(TokenType.RBRACE)
        return InterfaceDecl(name=name, methods=methods, parent=parent,
                             generic_params=generic_params,
                             line=tok.line, col=tok.col)
