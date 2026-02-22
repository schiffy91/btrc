"""Recursive descent parser for the btrc language."""

from .tokens import Token, TokenType, TYPE_KEYWORDS, KEYWORDS
from .ast_nodes import *


class ParseError(Exception):
    def __init__(self, message: str, line: int, col: int):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self) -> Program:
        decls = []
        while not self._at_end():
            decls.append(self._parse_top_level_item())
        return Program(declarations=decls)

    # ---- Token helpers ----

    def _peek(self, offset: int = 0) -> Token:
        pos = self.pos + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]  # EOF

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _at_end(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _check(self, *types: TokenType) -> bool:
        return self._peek().type in types

    def _match(self, *types: TokenType) -> Optional[Token]:
        if self._peek().type in types:
            return self._advance()
        return None

    def _expect(self, token_type: TokenType, msg: str = "") -> Token:
        tok = self._peek()
        if tok.type == token_type:
            return self._advance()
        expected = msg or token_type.name
        raise ParseError(
            f"Expected {expected}, got {tok.type.name} '{tok.value}'",
            tok.line, tok.col
        )

    def _error(self, msg: str) -> ParseError:
        tok = self._peek()
        return ParseError(msg, tok.line, tok.col)

    # ---- Helpers for >> splitting in generic context ----

    def _expect_gt(self) -> Token:
        """Expect a '>' — handles splitting '>>' and '>>=' tokens."""
        tok = self._peek()
        if tok.type == TokenType.GT:
            return self._advance()
        if tok.type == TokenType.GT_GT:
            # Split >> into > and >
            self._advance()
            # Insert a synthetic > token back into the stream
            synthetic = Token(TokenType.GT, ">", tok.line, tok.col + 1)
            self.tokens.insert(self.pos, synthetic)
            return Token(TokenType.GT, ">", tok.line, tok.col)
        if tok.type == TokenType.GT_GT_EQ:
            # Split >>= into > and >=
            self._advance()
            synthetic = Token(TokenType.GT_EQ, ">=", tok.line, tok.col + 1)
            self.tokens.insert(self.pos, synthetic)
            return Token(TokenType.GT, ">", tok.line, tok.col)
        raise ParseError(
            f"Expected '>', got {tok.type.name} '{tok.value}'",
            tok.line, tok.col
        )

    # ---- Top level ----

    def _parse_top_level_item(self):
        tok = self._peek()

        # Preprocessor directive
        if tok.type == TokenType.PREPROCESSOR:
            return self._parse_preprocessor()

        # @gpu annotation
        is_gpu = False
        if tok.type == TokenType.AT_GPU:
            is_gpu = True
            self._advance()
            tok = self._peek()

        # class declaration
        if tok.type == TokenType.CLASS and not is_gpu:
            # Could be class keyword (access spec) or class declaration
            # If next token after 'class' is an IDENT and the one after that
            # is '{' or '<', it's a class declaration
            next_tok = self._peek(1)
            if next_tok.type == TokenType.IDENT:
                after = self._peek(2)
                if after.type in (TokenType.LBRACE, TokenType.LT, TokenType.EXTENDS):
                    return self._parse_class_decl()

        # struct declaration (only if 'struct Name {' or 'struct Name ;', not 'struct Name* func()')
        if tok.type == TokenType.STRUCT and not is_gpu:
            next_tok = self._peek(1)
            if next_tok.type == TokenType.IDENT:
                after = self._peek(2)
                if after.type in (TokenType.LBRACE, TokenType.SEMICOLON):
                    return self._parse_struct_decl()
            elif next_tok.type == TokenType.LBRACE:
                return self._parse_struct_decl()

        # enum declaration
        if tok.type == TokenType.ENUM and not is_gpu:
            return self._parse_enum_decl()

        # typedef
        if tok.type == TokenType.TYPEDEF and not is_gpu:
            return self._parse_typedef_decl()

        # function or variable declaration
        # Both start with a type expression
        if self._is_type_start(tok):
            return self._parse_function_or_var_decl(is_gpu)

        raise self._error(f"Unexpected token '{tok.value}' at top level")

    def _parse_preprocessor(self) -> PreprocessorDirective:
        tok = self._advance()
        return PreprocessorDirective(text=tok.value, line=tok.line, col=tok.col)

    # ---- Class declaration ----

    def _parse_class_decl(self) -> ClassDecl:
        tok = self._expect(TokenType.CLASS)
        name_tok = self._expect(TokenType.IDENT, "class name")
        name = name_tok.value

        # Generic params
        generic_params = []
        if self._match(TokenType.LT):
            generic_params.append(self._expect(TokenType.IDENT, "generic param").value)
            while self._match(TokenType.COMMA):
                generic_params.append(self._expect(TokenType.IDENT, "generic param").value)
            self._expect_gt()

        # Inheritance
        parent = None
        if self._match(TokenType.EXTENDS):
            parent = self._expect(TokenType.IDENT, "parent class name").value

        self._expect(TokenType.LBRACE)

        members = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            members.append(self._parse_class_member())

        self._expect(TokenType.RBRACE)
        return ClassDecl(name=name, generic_params=generic_params,
                         members=members, parent=parent, line=tok.line, col=tok.col)

    def _parse_class_member(self):
        """Parse a class member: access_spec (field | method)."""
        tok = self._peek()

        # access specifier
        if tok.type == TokenType.PUBLIC:
            access = "public"
            self._advance()
        elif tok.type == TokenType.PRIVATE:
            access = "private"
            self._advance()
        elif tok.type == TokenType.CLASS:
            access = "class"
            self._advance()
        else:
            raise self._error(f"Expected access specifier (public/private/class), got '{tok.value}'")

        # Check for @gpu
        is_gpu = False
        if self._check(TokenType.AT_GPU):
            is_gpu = True
            self._advance()

        # Parse type
        type_expr = self._parse_type_expr()

        # Constructor detection: if next token is '(' instead of IDENT,
        # the "type" we just parsed is actually the constructor name
        if self._check(TokenType.LPAREN):
            # Constructor — type_expr.base is the method name, return type is the same
            name = type_expr.base
            return self._parse_method_rest(access, type_expr, name, is_gpu, tok.line, tok.col)

        # Name
        name_tok = self._expect(TokenType.IDENT, "member name")
        name = name_tok.value

        # If next is '(' → method, otherwise → field
        if self._check(TokenType.LPAREN):
            return self._parse_method_rest(access, type_expr, name, is_gpu, tok.line, tok.col)
        else:
            # Field
            init = None
            if self._match(TokenType.EQ):
                init = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return FieldDecl(access=access, type=type_expr, name=name,
                             initializer=init, line=tok.line, col=tok.col)

    def _parse_method_rest(self, access, return_type, name, is_gpu, line, col) -> MethodDecl:
        self._expect(TokenType.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenType.RPAREN)
        body = self._parse_block()
        return MethodDecl(access=access, return_type=return_type, name=name,
                          params=params, body=body, is_gpu=is_gpu,
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
                # C-style array field: type name[N]
                if self._check(TokenType.LBRACKET):
                    self._advance()  # [
                    if self._check(TokenType.RBRACKET):
                        self._advance()  # ]
                        ftype.is_array = True
                    else:
                        size_expr = self._parse_expr()
                        self._expect(TokenType.RBRACKET)
                        ftype.is_array = True
                        ftype.array_size = size_expr
                fields.append(FieldDecl(type=ftype, name=fname, line=tok.line, col=tok.col))
                self._expect(TokenType.SEMICOLON)
            self._expect(TokenType.RBRACE)
            self._expect(TokenType.SEMICOLON)
            return StructDecl(name=name, fields=fields, line=tok.line, col=tok.col)
        else:
            # Forward declaration: struct Foo;
            self._expect(TokenType.SEMICOLON)
            return StructDecl(name=name, fields=[], line=tok.line, col=tok.col)

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
            values.append((vname, vval))
            if not self._match(TokenType.COMMA):
                break
        self._expect(TokenType.RBRACE)
        self._expect(TokenType.SEMICOLON)
        return EnumDecl(name=name, values=values, line=tok.line, col=tok.col)

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

        # Handle 'var' at top level — always a variable
        if self._check(TokenType.VAR):
            if is_gpu:
                raise self._error("@gpu cannot be applied to variables")
            self._advance()  # consume 'var'
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
            # Function
            self._expect(TokenType.LPAREN)
            params = self._parse_param_list()
            self._expect(TokenType.RPAREN)
            body = self._parse_block()
            return FunctionDecl(return_type=type_expr, name=name, params=params,
                                body=body, is_gpu=is_gpu,
                                line=start.line, col=start.col)
        else:
            # Variable
            if is_gpu:
                raise self._error("@gpu cannot be applied to variables")
            init = None
            if self._match(TokenType.EQ):
                init = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return VarDeclStmt(type=type_expr, name=name, initializer=init,
                               line=start.line, col=start.col)

    # ---- Type expressions ----

    def _is_type_start(self, tok: Token) -> bool:
        """Check if a token could start a type expression."""
        if tok.type == TokenType.VAR:
            return True
        if tok.type in TYPE_KEYWORDS:
            return True
        if tok.type == TokenType.IDENT:
            return True
        if tok.type == TokenType.LIST or tok.type == TokenType.MAP or tok.type == TokenType.ARRAY:
            return True
        # Tuple type: (int, int)
        if tok.type == TokenType.LPAREN and self._is_tuple_type_start():
            return True
        return False

    def _parse_type_expr(self) -> TypeExpr:
        tok = self._peek()
        line, col = tok.line, tok.col

        # Handle const/static/extern/volatile qualifiers (skip them, pass through)
        while self._check(TokenType.CONST, TokenType.STATIC, TokenType.EXTERN, TokenType.VOLATILE):
            self._advance()

        # Handle unsigned/signed qualifiers
        if self._check(TokenType.UNSIGNED, TokenType.SIGNED):
            base = self._advance().value
            # Can be followed by int/short/long/char or standalone
            if self._check(TokenType.INT, TokenType.SHORT, TokenType.LONG, TokenType.CHAR):
                base += " " + self._advance().value
                # Handle "long long"
                if base.endswith("long") and self._check(TokenType.LONG):
                    base += " " + self._advance().value
        elif self._check(TokenType.LONG):
            base = self._advance().value
            # Handle "long long", "long int", "long double"
            if self._check(TokenType.LONG):
                base += " " + self._advance().value
            if self._check(TokenType.INT, TokenType.DOUBLE):
                base += " " + self._advance().value
        elif self._check(TokenType.SHORT):
            base = self._advance().value
            if self._check(TokenType.INT):
                base += " " + self._advance().value
        elif self._check(TokenType.STRUCT):
            self._advance()
            base = "struct " + self._expect(TokenType.IDENT, "struct name").value
        elif self._check(TokenType.ENUM):
            self._advance()
            base = "enum " + self._expect(TokenType.IDENT, "enum name").value
        elif self._check(TokenType.UNION):
            self._advance()
            base = "union " + self._expect(TokenType.IDENT, "union name").value
        elif self._check(TokenType.LPAREN):
            # Tuple type: (int, int) or (string, int, float)
            return self._parse_tuple_type(line, col)
        else:
            base_tok = self._advance()
            base = base_tok.value

        # Generic arguments
        generic_args = []
        if self._check(TokenType.LT) and self._is_generic_start():
            self._advance()  # consume <
            generic_args.append(self._parse_type_expr())
            while self._match(TokenType.COMMA):
                generic_args.append(self._parse_type_expr())
            self._expect_gt()

        # Array suffix []
        is_array = False
        if self._check(TokenType.LBRACKET) and self._peek(1).type == TokenType.RBRACKET:
            self._advance()  # [
            self._advance()  # ]
            is_array = True

        # Pointer
        pointer_depth = 0
        while self._match(TokenType.STAR):
            pointer_depth += 1

        # Nullable: T? is sugar for T* (adds one pointer level)
        if self._match(TokenType.QUESTION):
            pointer_depth += 1

        return TypeExpr(base=base, generic_args=generic_args,
                        pointer_depth=pointer_depth, is_array=is_array,
                        line=line, col=col)

    def _is_tuple_type_start(self) -> bool:
        """Check if ( starts a tuple type like (int, int). Must have a comma inside."""
        save = self.pos
        self.pos += 1  # skip (
        tok = self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]
        # First token must be a type keyword
        if tok.type not in TYPE_KEYWORDS and tok.type not in (TokenType.LIST, TokenType.MAP, TokenType.ARRAY):
            self.pos = save
            return False
        # Scan forward for a comma inside the parens — distinguishes from cast (type)expr
        depth = 1
        self.pos += 1
        found_comma = False
        while self.pos < len(self.tokens) and depth > 0:
            t = self.tokens[self.pos]
            if t.type == TokenType.LPAREN:
                depth += 1
            elif t.type == TokenType.RPAREN:
                depth -= 1
            elif t.type == TokenType.COMMA and depth == 1:
                found_comma = True
                break
            self.pos += 1
        self.pos = save
        return found_comma

    def _parse_tuple_type(self, line: int, col: int) -> TypeExpr:
        """Parse tuple type: (type, type, ...)"""
        self._expect(TokenType.LPAREN)
        types = [self._parse_type_expr()]
        while self._match(TokenType.COMMA):
            types.append(self._parse_type_expr())
        self._expect(TokenType.RPAREN)
        return TypeExpr(base="Tuple", generic_args=types, line=line, col=col)

    def _is_generic_start(self) -> bool:
        """Look ahead to determine if '<' starts generic args or is a comparison.
        Uses a bracket-counting heuristic: try to find matching '>' with valid types inside."""
        save = self.pos
        depth = 1
        self.pos += 1  # skip the <

        while self.pos < len(self.tokens) and depth > 0:
            tok = self.tokens[self.pos]
            if tok.type == TokenType.LT:
                depth += 1
            elif tok.type == TokenType.GT:
                depth -= 1
            elif tok.type == TokenType.GT_GT:
                depth -= 2
                if depth <= 0:
                    # >> closed our level (and possibly a parent's). Still valid.
                    self.pos += 1
                    break
            elif tok.type in (TokenType.SEMICOLON, TokenType.LBRACE,
                              TokenType.RBRACE, TokenType.EOF):
                # Definitely not generic args
                self.pos = save
                return False
            self.pos += 1

        if depth <= 0:
            # Check what follows the closing >
            # If it's an identifier, *, (, [, ), comma, or > → generic
            tok = self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]
            self.pos = save
            return tok.type in (TokenType.IDENT, TokenType.STAR, TokenType.LPAREN,
                                TokenType.RPAREN, TokenType.LBRACKET, TokenType.COMMA,
                                TokenType.GT, TokenType.GT_GT, TokenType.SEMICOLON,
                                TokenType.LBRACE, TokenType.EQ)

        self.pos = save
        return False

    # ---- Parameters ----

    def _parse_param_list(self) -> list[Param]:
        params = []
        if self._check(TokenType.RPAREN):
            return params
        params.append(self._parse_param())
        while self._match(TokenType.COMMA):
            params.append(self._parse_param())
        return params

    def _parse_param(self) -> Param:
        tok = self._peek()
        type_expr = self._parse_type_expr()
        name = self._expect(TokenType.IDENT, "parameter name").value
        # C-style array param: int arr[] or int arr[N]
        if self._check(TokenType.LBRACKET):
            self._advance()  # [
            if self._check(TokenType.RBRACKET):
                self._advance()  # ]
                type_expr.is_array = True
            else:
                size_expr = self._parse_expr()
                self._expect(TokenType.RBRACKET)
                type_expr.is_array = True
                type_expr.array_size = size_expr
        # Default parameter value: type name = expr
        default = None
        if self._match(TokenType.EQ):
            default = self._parse_expr()
        return Param(type=type_expr, name=name, default=default, line=tok.line, col=tok.col)

    # ---- Block ----

    def _parse_block(self) -> Block:
        tok = self._expect(TokenType.LBRACE)
        stmts = []
        while not self._check(TokenType.RBRACE) and not self._at_end():
            stmts.append(self._parse_statement())
        self._expect(TokenType.RBRACE)
        return Block(statements=stmts, line=tok.line, col=tok.col)

    # ---- Statements ----

    def _parse_statement(self):
        tok = self._peek()

        # Block
        if tok.type == TokenType.LBRACE:
            return self._parse_block()

        # Return
        if tok.type == TokenType.RETURN:
            return self._parse_return_stmt()

        # If
        if tok.type == TokenType.IF:
            return self._parse_if_stmt()

        # While
        if tok.type == TokenType.WHILE:
            return self._parse_while_stmt()

        # Do-while
        if tok.type == TokenType.DO:
            return self._parse_do_while_stmt()

        # For (C-style or for-in)
        if tok.type == TokenType.FOR:
            return self._parse_for_stmt()

        # Parallel for
        if tok.type == TokenType.PARALLEL:
            return self._parse_parallel_for_stmt()

        # Switch
        if tok.type == TokenType.SWITCH:
            return self._parse_switch_stmt()

        # Break
        if tok.type == TokenType.BREAK:
            self._advance()
            self._expect(TokenType.SEMICOLON)
            return BreakStmt(line=tok.line, col=tok.col)

        # Continue
        if tok.type == TokenType.CONTINUE:
            self._advance()
            self._expect(TokenType.SEMICOLON)
            return ContinueStmt(line=tok.line, col=tok.col)

        # Try/catch
        if tok.type == TokenType.TRY:
            return self._parse_try_catch()

        # Throw
        if tok.type == TokenType.THROW:
            return self._parse_throw()

        # Delete
        if tok.type == TokenType.DELETE:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return DeleteStmt(expr=expr, line=tok.line, col=tok.col)

        # Variable declaration or expression statement
        # Try to detect if this is a type followed by a name (var decl)
        if self._is_var_decl_start():
            return self._parse_var_decl_stmt()

        # Expression statement
        return self._parse_expr_stmt()

    def _is_var_decl_start(self) -> bool:
        """Lookahead to determine if the current position starts a variable declaration."""
        tok = self._peek()

        # 'var' keyword always starts a var decl
        if tok.type == TokenType.VAR:
            return True

        # Obvious type keywords
        if tok.type in TYPE_KEYWORDS and tok.type not in (TokenType.CONST, TokenType.STATIC,
                                                           TokenType.EXTERN, TokenType.VOLATILE):
            # After a type keyword, if we see an identifier (skipping *, <...>) → var decl
            return self._lookahead_is_var_decl()

        # Const/static/extern followed by type → var decl
        if tok.type in (TokenType.CONST, TokenType.STATIC, TokenType.EXTERN, TokenType.VOLATILE):
            return True

        # IDENT could be a user-defined type name
        if tok.type == TokenType.IDENT:
            return self._lookahead_is_var_decl()

        # Built-in btrc types
        if tok.type in (TokenType.LIST, TokenType.MAP, TokenType.ARRAY):
            return self._lookahead_is_var_decl()

        # Tuple type: (int, int) name
        if tok.type == TokenType.LPAREN and self._is_tuple_type_start():
            return self._lookahead_is_var_decl()

        return False

    def _lookahead_is_var_decl(self) -> bool:
        """From current position, try to parse a type + name pattern.
        Returns True if it looks like a var decl."""
        # 'var' is always a var decl
        if self.tokens[self.pos].type == TokenType.VAR:
            return True

        save = self.pos

        try:
            # Skip qualifiers
            while self.tokens[self.pos].type in (TokenType.CONST, TokenType.STATIC,
                                                   TokenType.EXTERN, TokenType.VOLATILE):
                self.pos += 1

            # Skip base type (keyword or ident)
            tok = self.tokens[self.pos]
            # Tuple type: (type, type, ...)
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
                # After closing ), check for identifier
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
                if self.tokens[self.pos].type in (TokenType.INT, TokenType.LONG, TokenType.DOUBLE):
                    self.pos += 1
            elif tok.type == TokenType.STRUCT or tok.type == TokenType.ENUM or tok.type == TokenType.UNION:
                self.pos += 1
                if self.tokens[self.pos].type == TokenType.IDENT:
                    self.pos += 1
            elif tok.type in TYPE_KEYWORDS or tok.type == TokenType.IDENT or \
                 tok.type in (TokenType.LIST, TokenType.MAP, TokenType.ARRAY):
                self.pos += 1
            else:
                self.pos = save
                return False

            # Skip generic args if present
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

            # Skip [] if present
            if (self.pos < len(self.tokens) and
                self.tokens[self.pos].type == TokenType.LBRACKET and
                self.pos + 1 < len(self.tokens) and
                self.tokens[self.pos + 1].type == TokenType.RBRACKET):
                self.pos += 2

            # Skip pointers
            while self.pos < len(self.tokens) and self.tokens[self.pos].type == TokenType.STAR:
                self.pos += 1

            # Now we should see an identifier (the variable name)
            result = (self.pos < len(self.tokens) and
                      self.tokens[self.pos].type == TokenType.IDENT)
            self.pos = save
            return result
        except IndexError:
            self.pos = save
            return False

    def _parse_var_decl_stmt(self) -> VarDeclStmt:
        tok = self._peek()

        # Handle 'var' keyword: var name = expr;
        if self._check(TokenType.VAR):
            self._advance()  # consume 'var'
            name = self._expect(TokenType.IDENT, "variable name").value
            self._expect(TokenType.EQ, "'=' (var requires an initializer)")
            init = self._parse_expr()
            self._expect(TokenType.SEMICOLON)
            return VarDeclStmt(type=None, name=name, initializer=init,
                               line=tok.line, col=tok.col)

        type_expr = self._parse_type_expr()
        name = self._expect(TokenType.IDENT, "variable name").value
        # C-style array: type name[N] or type name[] = {...}
        if self._check(TokenType.LBRACKET):
            self._advance()  # [
            if self._check(TokenType.RBRACKET):
                self._advance()  # ]
                type_expr.is_array = True
            else:
                # Fixed-size array: name[N] — emit as raw C
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
                else_block = self._parse_if_stmt()
            else:
                else_block = self._parse_block()
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

        # C for: 'for' '(' init ';' cond ';' update ')' block
        self._expect(TokenType.LPAREN)

        # Init
        init = None
        if not self._check(TokenType.SEMICOLON):
            if self._is_var_decl_start():
                start = self._peek()
                # Handle 'var' in for-init
                if self._check(TokenType.VAR):
                    self._advance()  # consume 'var'
                    name = self._expect(TokenType.IDENT, "variable name").value
                    self._expect(TokenType.EQ, "'=' (var requires an initializer)")
                    init_val = self._parse_expr()
                    init = VarDeclStmt(type=None, name=name, initializer=init_val,
                                       line=start.line, col=start.col)
                else:
                    # Parse type + name + optional init, but don't consume the semicolon
                    type_expr = self._parse_type_expr()
                    name = self._expect(TokenType.IDENT, "variable name").value
                    init_val = None
                    if self._match(TokenType.EQ):
                        init_val = self._parse_expr()
                    init = VarDeclStmt(type=type_expr, name=name, initializer=init_val,
                                       line=start.line, col=start.col)
            else:
                init = self._parse_expr()
        self._expect(TokenType.SEMICOLON)

        # Condition
        condition = None
        if not self._check(TokenType.SEMICOLON):
            condition = self._parse_expr()
        self._expect(TokenType.SEMICOLON)

        # Update
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
        # catch (string e) or catch (e)
        if self._is_type_start(self._peek()) and self._peek(1).type == TokenType.IDENT:
            self._parse_type_expr()  # skip the type (always string for now)
        catch_var = self._expect(TokenType.IDENT, "catch variable").value
        self._expect(TokenType.RPAREN)
        catch_block = self._parse_block()
        return TryCatchStmt(try_block=try_block, catch_var=catch_var,
                            catch_block=catch_block, line=tok.line, col=tok.col)

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

    # ---- Expressions (precedence climbing) ----

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
            right = self._parse_assignment()  # right-associative
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

        # Prefix operators
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

        # Dereference
        if tok.type == TokenType.STAR:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="*", operand=operand, prefix=True,
                             line=tok.line, col=tok.col)

        # Address-of
        if tok.type == TokenType.AMP:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="&", operand=operand, prefix=True,
                             line=tok.line, col=tok.col)

        # sizeof
        if tok.type == TokenType.SIZEOF:
            return self._parse_sizeof()

        # C-style cast: (type)expr
        if tok.type == TokenType.LPAREN and self._is_cast():
            return self._parse_cast()

        return self._parse_postfix()

    def _is_cast(self) -> bool:
        """Check if '(' starts a cast expression."""
        save = self.pos
        self.pos += 1  # skip (

        tok = self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]

        # If the token after ( is a type keyword → likely cast
        if tok.type in TYPE_KEYWORDS or tok.type in (TokenType.LIST, TokenType.MAP, TokenType.ARRAY):
            # Find the matching )
            depth = 1
            self.pos += 1
            while self.pos < len(self.tokens) and depth > 0:
                t = self.tokens[self.pos]
                if t.type == TokenType.LPAREN:
                    depth += 1
                elif t.type == TokenType.RPAREN:
                    depth -= 1
                self.pos += 1
            # After ), check if what follows could be a unary expr (not an operator)
            if self.pos < len(self.tokens):
                next_tok = self.tokens[self.pos]
                self.pos = save
                return next_tok.type in (
                    TokenType.IDENT, TokenType.INT_LIT, TokenType.FLOAT_LIT,
                    TokenType.STRING_LIT, TokenType.CHAR_LIT, TokenType.LPAREN,
                    TokenType.STAR, TokenType.AMP, TokenType.BANG, TokenType.TILDE,
                    TokenType.MINUS, TokenType.PLUS_PLUS, TokenType.MINUS_MINUS,
                    TokenType.SELF, TokenType.TRUE, TokenType.FALSE, TokenType.NULL,
                    TokenType.NEW,
                )
            self.pos = save
            return False

        self.pos = save
        return False

    def _parse_cast(self) -> CastExpr:
        tok = self._expect(TokenType.LPAREN)
        target_type = self._parse_type_expr()
        self._expect(TokenType.RPAREN)
        expr = self._parse_unary()
        return CastExpr(target_type=target_type, expr=expr,
                        line=tok.line, col=tok.col)

    def _parse_sizeof(self) -> SizeofExpr:
        tok = self._expect(TokenType.SIZEOF)
        self._expect(TokenType.LPAREN)
        # Could be a type or an expression — try type first
        if self._is_type_start(self._peek()) and self._is_sizeof_type():
            operand = self._parse_type_expr()
        else:
            operand = self._parse_expr()
        self._expect(TokenType.RPAREN)
        return SizeofExpr(operand=operand, line=tok.line, col=tok.col)

    def _is_sizeof_type(self) -> bool:
        """Lookahead to check if sizeof contains a type."""
        save = self.pos
        tok = self.tokens[self.pos]
        # If it's an obvious type keyword → type
        if tok.type in TYPE_KEYWORDS and tok.type != TokenType.IDENT:
            self.pos = save
            return True
        # If IDENT followed by ) → could be either, default to type if it's a known type
        # For now, assume type if it's a type keyword
        self.pos = save
        return tok.type in TYPE_KEYWORDS

    def _parse_postfix(self):
        expr = self._parse_primary()

        while True:
            tok = self._peek()

            # Function call
            if tok.type == TokenType.LPAREN:
                self._advance()
                args = []
                if not self._check(TokenType.RPAREN):
                    args.append(self._parse_expr())
                    while self._match(TokenType.COMMA):
                        args.append(self._parse_expr())
                self._expect(TokenType.RPAREN)
                expr = CallExpr(callee=expr, args=args, line=expr.line, col=expr.col)

            # Index
            elif tok.type == TokenType.LBRACKET:
                self._advance()
                index = self._parse_expr()
                self._expect(TokenType.RBRACKET)
                expr = IndexExpr(obj=expr, index=index, line=expr.line, col=expr.col)

            # Field access
            elif tok.type == TokenType.DOT:
                self._advance()
                # Allow numeric field access for tuples: t.0, t.1
                if self._check(TokenType.INT_LIT):
                    idx_tok = self._advance()
                    field_name = f"_{idx_tok.value}"
                else:
                    field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=False,
                                       line=expr.line, col=expr.col)

            # Optional chaining: obj?.field
            elif tok.type == TokenType.QUESTION_DOT:
                self._advance()
                field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=True,
                                       optional=True, line=expr.line, col=expr.col)

            # Arrow access
            elif tok.type == TokenType.ARROW:
                self._advance()
                field_name = self._expect(TokenType.IDENT, "field name").value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=True,
                                       line=expr.line, col=expr.col)

            # Postfix ++
            elif tok.type == TokenType.PLUS_PLUS:
                self._advance()
                expr = UnaryExpr(op="++", operand=expr, prefix=False,
                                 line=expr.line, col=expr.col)

            # Postfix --
            elif tok.type == TokenType.MINUS_MINUS:
                self._advance()
                expr = UnaryExpr(op="--", operand=expr, prefix=False,
                                 line=expr.line, col=expr.col)

            else:
                break

        return expr

    def _parse_primary(self):
        tok = self._peek()

        # Integer literal
        if tok.type == TokenType.INT_LIT:
            self._advance()
            return IntLiteral(value=int(tok.value, 0), raw=tok.value,
                              line=tok.line, col=tok.col)

        # Float literal
        if tok.type == TokenType.FLOAT_LIT:
            self._advance()
            raw = tok.value
            # Strip suffix for float conversion
            fval = raw.rstrip('fF')
            return FloatLiteral(value=float(fval), raw=raw,
                                line=tok.line, col=tok.col)

        # String literal
        if tok.type == TokenType.STRING_LIT:
            self._advance()
            return StringLiteral(value=tok.value, line=tok.line, col=tok.col)

        # Char literal
        if tok.type == TokenType.CHAR_LIT:
            self._advance()
            return CharLiteral(value=tok.value, line=tok.line, col=tok.col)

        # F-string literal
        if tok.type == TokenType.FSTRING_LIT:
            self._advance()
            return self._parse_fstring(tok)

        # Bool literals
        if tok.type == TokenType.TRUE:
            self._advance()
            return BoolLiteral(value=True, line=tok.line, col=tok.col)
        if tok.type == TokenType.FALSE:
            self._advance()
            return BoolLiteral(value=False, line=tok.line, col=tok.col)

        # Null
        if tok.type == TokenType.NULL:
            self._advance()
            return NullLiteral(line=tok.line, col=tok.col)

        # Self
        if tok.type == TokenType.SELF:
            self._advance()
            return SelfExpr(line=tok.line, col=tok.col)

        # new expression
        if tok.type == TokenType.NEW:
            return self._parse_new_expr()

        # Parenthesized expression or tuple literal
        if tok.type == TokenType.LPAREN:
            self._advance()
            expr = self._parse_expr()
            if self._match(TokenType.COMMA):
                # Tuple literal: (expr, expr, ...)
                elements = [expr]
                elements.append(self._parse_expr())
                while self._match(TokenType.COMMA):
                    elements.append(self._parse_expr())
                self._expect(TokenType.RPAREN)
                return TupleLiteral(elements=elements, line=tok.line, col=tok.col)
            self._expect(TokenType.RPAREN)
            return expr

        # List literal
        if tok.type == TokenType.LBRACKET:
            return self._parse_list_literal()

        # Map literal — only if { is followed by expr : (not a statement block)
        if tok.type == TokenType.LBRACE and self._is_map_literal():
            return self._parse_map_literal()

        # C-style brace initializer: {a, b, c} (used in array/struct init)
        if tok.type == TokenType.LBRACE:
            return self._parse_brace_initializer()

        # Identifier
        if tok.type == TokenType.IDENT:
            self._advance()
            return Identifier(name=tok.value, line=tok.line, col=tok.col)

        raise self._error(f"Unexpected token '{tok.value}' in expression")

    def _parse_new_expr(self) -> NewExpr:
        tok = self._expect(TokenType.NEW)
        type_expr = self._parse_type_expr()
        self._expect(TokenType.LPAREN)
        args = []
        if not self._check(TokenType.RPAREN):
            args.append(self._parse_expr())
            while self._match(TokenType.COMMA):
                args.append(self._parse_expr())
        self._expect(TokenType.RPAREN)
        return NewExpr(type=type_expr, args=args, line=tok.line, col=tok.col)

    def _parse_list_literal(self) -> ListLiteral:
        tok = self._expect(TokenType.LBRACKET)
        elements = []
        if not self._check(TokenType.RBRACKET):
            elements.append(self._parse_expr())
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACKET):
                    break  # trailing comma
                elements.append(self._parse_expr())
        self._expect(TokenType.RBRACKET)
        return ListLiteral(elements=elements, line=tok.line, col=tok.col)

    def _is_map_literal(self) -> bool:
        """Check if { starts a map literal (has expr : expr pattern)."""
        # Empty {} is a block, not a map
        if self._peek(1).type == TokenType.RBRACE:
            return False
        # Look for the : pattern after the first expression
        save = self.pos
        self.pos += 1  # skip {
        depth = 0
        while self.pos < len(self.tokens):
            t = self.tokens[self.pos]
            if t.type == TokenType.COLON and depth == 0:
                self.pos = save
                return True
            if t.type in (TokenType.LPAREN, TokenType.LBRACKET, TokenType.LBRACE):
                depth += 1
            elif t.type in (TokenType.RPAREN, TokenType.RBRACKET, TokenType.RBRACE):
                if depth == 0:
                    break
                depth -= 1
            elif t.type == TokenType.SEMICOLON:
                break
            self.pos += 1
        self.pos = save
        return False

    def _parse_map_literal(self) -> MapLiteral:
        tok = self._expect(TokenType.LBRACE)
        entries = []
        if not self._check(TokenType.RBRACE):
            key = self._parse_expr()
            self._expect(TokenType.COLON)
            value = self._parse_expr()
            entries.append((key, value))
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACE):
                    break  # trailing comma
                key = self._parse_expr()
                self._expect(TokenType.COLON)
                value = self._parse_expr()
                entries.append((key, value))
        self._expect(TokenType.RBRACE)
        return MapLiteral(entries=entries, line=tok.line, col=tok.col)

    def _parse_brace_initializer(self) -> BraceInitializer:
        """Parse C-style brace initializer: {expr, expr, ...}"""
        tok = self._expect(TokenType.LBRACE)
        elements = []
        if not self._check(TokenType.RBRACE):
            elements.append(self._parse_expr())
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACE):
                    break  # trailing comma
                elements.append(self._parse_expr())
        self._expect(TokenType.RBRACE)
        return BraceInitializer(elements=elements, line=tok.line, col=tok.col)

    def _parse_fstring(self, tok: Token) -> FStringLiteral:
        """Parse f-string content into text and expression parts."""
        raw = tok.value
        parts = []
        i = 0
        text_buf = []
        while i < len(raw):
            ch = raw[i]
            if ch == '{':
                # Flush accumulated text
                if text_buf:
                    parts.append(("text", ''.join(text_buf)))
                    text_buf = []
                # Extract expression source between { and matching }
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
                i += 1  # skip closing }
                expr_src = ''.join(expr_chars)
                # Unescape quotes that were escaped for the outer f-string
                expr_src = expr_src.replace('\\"', '"')
                # Parse the expression using a sub-lexer and sub-parser
                from .lexer import Lexer
                sub_tokens = Lexer(expr_src + ";").tokenize()
                sub_parser = Parser(sub_tokens)
                expr_node = sub_parser._parse_expr()
                parts.append(("expr", expr_node))
            elif ch == '\\':
                # Pass escape sequences through as-is
                text_buf.append(ch)
                if i + 1 < len(raw):
                    i += 1
                    text_buf.append(raw[i])
                i += 1
            else:
                text_buf.append(ch)
                i += 1
        if text_buf:
            parts.append(("text", ''.join(text_buf)))
        return FStringLiteral(parts=parts, line=tok.line, col=tok.col)
