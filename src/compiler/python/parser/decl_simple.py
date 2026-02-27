"""Simple declaration parsing: enum, rich enum, typedef, property, function/var."""

from ..tokens import TokenType
from ..ast_nodes import (
    EnumDecl, EnumValue, FunctionDecl, PropertyDecl,
    RichEnumDecl, RichEnumVariant, TypedefDecl, VarDeclStmt,
)


class SimpleDeclarationsMixin:

    def _is_property_start(self) -> bool:
        """Check if '{' starts a property definition (contains 'get' or 'set')."""
        save = self.pos
        self.pos += 1
        tok = self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]
        result = (tok.type == TokenType.IDENT and tok.value in ("get", "set"))
        self.pos = save
        return result

    def _parse_property(self, access, type_expr, name, line, col) -> PropertyDecl:
        """Parse C#-style property: type name { get; set; } or { get { ... } set { ... } }"""
        self._expect(TokenType.LBRACE)
        has_getter = False
        has_setter = False
        getter_body = None
        setter_body = None

        while not self._check(TokenType.RBRACE) and not self._at_end():
            tok = self._peek()
            if tok.type == TokenType.IDENT and tok.value == "get":
                self._advance()
                has_getter = True
                if self._match(TokenType.SEMICOLON):
                    getter_body = None
                elif self._check(TokenType.LBRACE):
                    getter_body = self._parse_block()
                else:
                    raise self._error("Expected ';' or '{' after 'get'")
            elif tok.type == TokenType.IDENT and tok.value == "set":
                self._advance()
                has_setter = True
                if self._match(TokenType.SEMICOLON):
                    setter_body = None
                elif self._check(TokenType.LBRACE):
                    setter_body = self._parse_block()
                else:
                    raise self._error("Expected ';' or '{' after 'set'")
            else:
                raise self._error(
                    f"Expected 'get' or 'set' in property, got '{tok.value}'")

        self._expect(TokenType.RBRACE)
        return PropertyDecl(access=access, type=type_expr, name=name,
                            has_getter=has_getter, has_setter=has_setter,
                            getter_body=getter_body, setter_body=setter_body,
                            line=line, col=col)

    # ---- Enum declaration ----

    def _parse_enum_decl(self) -> EnumDecl:
        tok = self._expect(TokenType.ENUM)
        name = ""
        if self._check(TokenType.IDENT):
            name = self._advance().value
        self._expect(TokenType.LBRACE)
        values = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            vname = self._expect(TokenType.IDENT, "enum value").value
            vval = None
            if self._match(TokenType.EQ):
                vval = self._parse_expr()
            values.append(EnumValue(name=vname, value=vval))
            if not self._match(TokenType.COMMA):
                break
        self._expect(TokenType.RBRACE)
        self._expect(TokenType.SEMICOLON)
        return EnumDecl(name=name, values=values, line=tok.line, col=tok.col)

    # ---- Rich enum declaration ----

    def _parse_rich_enum_decl(self) -> RichEnumDecl:
        """Parse: enum class Name { Variant1(type1 name1), Variant2, ... }"""
        tok = self._expect(TokenType.ENUM)
        self._expect(TokenType.CLASS)
        name = self._expect(TokenType.IDENT, "enum name").value
        self._expect(TokenType.LBRACE)
        variants = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            vname = self._expect(TokenType.IDENT, "variant name").value
            params = []
            if self._match(TokenType.LPAREN):
                if not self._check(TokenType.RPAREN):
                    params = self._parse_param_list()
                self._expect(TokenType.RPAREN)
            variants.append(RichEnumVariant(name=vname, params=params))
            if not self._match(TokenType.COMMA):
                break
        self._expect(TokenType.RBRACE)
        return RichEnumDecl(name=name, variants=variants, line=tok.line, col=tok.col)

    # ---- Typedef declaration ----

    def _parse_typedef_decl(self) -> TypedefDecl:
        tok = self._expect(TokenType.TYPEDEF)
        original = self._parse_type_expr()
        alias = self._expect(TokenType.IDENT, "typedef alias").value
        self._expect(TokenType.SEMICOLON)
        return TypedefDecl(original=original, alias=alias, line=tok.line, col=tok.col)

    # ---- Function or variable declaration ----

    def _parse_function_or_var_decl(self, is_gpu: bool = False):
        """Disambiguate function vs variable at top level."""
        start = self._peek()

        if self._check(TokenType.VAR):
            if is_gpu:
                raise self._error("@gpu cannot be applied to variables")
            self._advance()
            name = self._expect(TokenType.IDENT, "variable name").value
            self._expect(TokenType.EQ, "'=' (var requires an initializer)")
            init = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return VarDeclStmt(type=None, name=name, initializer=init,
                               line=start.line, col=start.col)

        type_expr = self._parse_type_expr()
        name_tok = self._expect(TokenType.IDENT, "name")
        name = name_tok.value

        if self._check(TokenType.LPAREN):
            self._expect(TokenType.LPAREN)
            params = self._parse_param_list()
            self._expect(TokenType.RPAREN)
            if self._match(TokenType.SEMICOLON):
                return FunctionDecl(return_type=type_expr, name=name, params=params,
                                    body=None, is_gpu=is_gpu,
                                    line=start.line, col=start.col)
            body = self._parse_block()
            return FunctionDecl(return_type=type_expr, name=name, params=params,
                                body=body, is_gpu=is_gpu,
                                line=start.line, col=start.col)
        else:
            if is_gpu:
                raise self._error("@gpu cannot be applied to variables")
            init = None
            if self._match(TokenType.EQ):
                init = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return VarDeclStmt(type=type_expr, name=name, initializer=init,
                               line=start.line, col=start.col)
