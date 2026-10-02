"""Complete stateful recursive-descent parser for the btrc language."""

from __future__ import annotations

import copy
import dataclasses
from types import MappingProxyType

from src.compiler.python.syntax.ast.generated import (
    AssignExpr,
    BinaryExpr,
    Block,
    BoolLiteral,
    BraceInitializer,
    BreakStmt,
    CallExpr,
    CaseClause,
    CastExpr,
    CForStmt,
    CharLiteral,
    ClassDecl,
    CommaExpr,
    ContinueStmt,
    DeleteStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    EnumDecl,
    EnumValue,
    ExprStmt,
    FieldAccessExpr,
    FieldDecl,
    FieldDef,
    FloatLiteral,
    ForInitExpr,
    ForInitVar,
    ForInStmt,
    FStringExpr,
    FStringLiteral,
    FStringText,
    FunctionDecl,
    Identifier,
    IfStmt,
    ImportDecl,
    IndexExpr,
    InterfaceDecl,
    IntLiteral,
    KeepStmt,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    LibraryGlob,
    LibraryModules,
    ListLiteral,
    MapEntry,
    MapLiteral,
    MethodDecl,
    MethodSig,
    NewExpr,
    NullLiteral,
    PackagePath,
    ParallelForStmt,
    Param,
    PreprocessorDirective,
    Program,
    PropertyDecl,
    QuotedPath,
    RelativePath,
    ReleaseStmt,
    ReturnStmt,
    RichEnumDecl,
    RichEnumVariant,
    SelfExpr,
    SizeofExpr,
    SizeofExprOp,
    SizeofType,
    SpawnExpr,
    StringConcat,
    StringLiteral,
    StructDecl,
    SuperExpr,
    SwitchStmt,
    TernaryExpr,
    ThrowStmt,
    TryCatchStmt,
    TupleLiteral,
    TypedefDecl,
    TypeExpr,
    UnaryExpr,
    VarDeclStmt,
    WhileStmt,
)

from ..lexer.lexer import Lexer, LiteralDecoder
from ..syntax.tokens import TYPE_KEYWORDS, Token, TokenKind, TokenVocabulary

# C parameter-list refusals (docs/design/c-compatibility.md, item (a)).
VOID_PARAMETER_LIST = "A 'void' parameter must be the only one, unnamed and unqualified: write '(void)'"
UNNAMED_PARAMETER = "Parameter name required: only a function prototype without a body may omit it"
UNNAMED_KEEP_PARAMETER = "A 'keep' parameter requires a name"
UNNAMED_DEFAULT_PARAMETER = "An unnamed parameter cannot have a default value"
NULLABLE_DECLARATORS = "A nullable declaration declares one variable: write one declaration per nullable variable"
VAR_DECLARATORS = "'var' declares one variable: write one 'var' declaration per variable"
FUNCTION_BESIDE_DECLARATORS = "Function '{}' must be declared on its own, not beside other declarators"


class ParseError(Exception):
    def __init__(self, message: str, line: int, col: int):
        self.line = line
        self.col = col
        super().__init__(f"{message} at {line}:{col}")


class Parser:
    """Own one complete recursive-descent parse invocation."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def parse(self):
        decls = []
        while not self._at_end():
            decls.extend(self._parse_top_level_items())
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

    def _member_name(self) -> Token:
        token = self._peek()
        if token.type == TokenKind.IDENT or TokenVocabulary.canonical().keywords.get(token.value) == token.type:
            return self._advance()
        return self._expect(TokenKind.IDENT, "field name")

    def _at_end(self) -> bool:
        return self._peek().type == TokenKind.EOF

    def _check(self, *types: TokenKind) -> bool:
        return self._peek().type in types

    def _match(self, *types: TokenKind) -> Token | None:
        if self._peek().type in types:
            return self._advance()
        return None

    def _expect(self, token_type: TokenKind, msg: str = "") -> Token:
        tok = self._peek()
        if tok.type == token_type:
            if token_type == TokenKind.IDENT:
                self._refuse_deferred_c_specifier(tok)
            return self._advance()
        if token_type == TokenKind.IDENT and self._is_reserved_name(self.pos):
            raise ParseError(f"'{tok.value}' is a reserved word and cannot be used as a name", tok.line, tok.col)
        expected = msg or token_type.name
        raise ParseError(f"Expected {expected}, got {tok.type.name} '{tok.value}'", tok.line, tok.col)

    def _is_reserved_name(self, position: int) -> bool:
        """Whether a grammar keyword sits where a declarator name belongs."""
        token = self.tokens[position] if position < len(self.tokens) else self.tokens[-1]
        if TokenVocabulary.canonical().keywords.get(token.value) != token.type:
            return False
        return self._token_kind_at(position + 1) in self._DECLARATOR_NAME_FOLLOWERS

    def _refuse_deferred_c_specifier(self, token: Token) -> None:
        if token.type == TokenKind.IDENT and token.value in self._DEFERRED_C_SPECIFIERS:
            raise ParseError(self._DEFERRED_C_SPECIFIERS[token.value], token.line, token.col)

    def _error(self, msg: str) -> ParseError:
        tok = self._peek()
        return ParseError(msg, tok.line, tok.col)

    def _parse_arg_list(self) -> tuple[list, list[str]]:
        """Parse call/constructor arguments plus optional names.

        `foo(a, b = 1)` records args as [a, 1] and arg_names as ["", "b"].
        Parenthesized assignment expressions still work as positional args:
        `foo((b = 1))`.
        """
        args = []
        arg_names = []
        if self._check(TokenKind.RPAREN):
            return args, arg_names

        while True:
            name = ""
            if self._check(TokenKind.IDENT) and self._peek(1).type == TokenKind.EQ:
                name = self._advance().value
                self._advance()
            args.append(self._parse_expr())
            arg_names.append(name)
            if not self._match(TokenKind.COMMA):
                break
        return args, arg_names

    # ---- Helpers for >> splitting in generic context ----

    def _expect_gt(self) -> Token:
        """Expect a '>' — handles splitting '>>' and '>>=' tokens."""
        tok = self._peek()
        if tok.type == TokenKind.GT:
            return self._advance()
        if tok.type == TokenKind.GT_GT:
            self._advance()
            synthetic = Token(TokenKind.GT, ">", tok.line, tok.col + 1)
            self.tokens.insert(self.pos, synthetic)
            return Token(TokenKind.GT, ">", tok.line, tok.col)
        if tok.type == TokenKind.GT_EQ:
            self._advance()
            synthetic = Token(TokenKind.EQ, "=", tok.line, tok.col + 1)
            self.tokens.insert(self.pos, synthetic)
            return Token(TokenKind.GT, ">", tok.line, tok.col)
        if tok.type == TokenKind.GT_GT_EQ:
            self._advance()
            synthetic = Token(TokenKind.GT_EQ, ">=", tok.line, tok.col + 1)
            self.tokens.insert(self.pos, synthetic)
            return Token(TokenKind.GT, ">", tok.line, tok.col)
        raise ParseError(f"Expected '>', got {tok.type.name} '{tok.value}'", tok.line, tok.col)

    # ---- Type-expression lookahead ----

    _QUALIFIERS = frozenset(
        {
            TokenKind.CONST,
            TokenKind.STATIC,
            TokenKind.EXTERN,
            TokenKind.VOLATILE,
        }
    )
    _SIMPLE_BASES = frozenset(
        {
            TokenKind.VOID,
            TokenKind.INT,
            TokenKind.FLOAT,
            TokenKind.DOUBLE,
            TokenKind.CHAR,
            TokenKind.BOOL,
            TokenKind.STRING,
            TokenKind.IDENT,
        }
    )
    # A keyword followed by one of these was written as a declarator name.
    _DECLARATOR_NAME_FOLLOWERS = frozenset(
        {
            TokenKind.EQ,
            TokenKind.SEMICOLON,
            TokenKind.LBRACKET,
            TokenKind.COMMA,
            TokenKind.RPAREN,
            TokenKind.LPAREN,
        }
    )
    # C11 type specifiers btrc defers (C row 24). They lex as identifiers, so
    # each is refused where a type, name or expression would begin.
    _DEFERRED_C_SPECIFIERS = MappingProxyType(
        {
            "_Atomic": "C11 '_Atomic' is not supported; use btrc's Atomic<T> for atomic storage",
            "_Complex": "C11 '_Complex' is not supported; btrc has no complex types",
        }
    )
    _GENERIC_FOLLOWS = frozenset(
        {
            TokenKind.IDENT,
            TokenKind.STAR,
            TokenKind.LPAREN,
            TokenKind.RPAREN,
            TokenKind.LBRACKET,
            TokenKind.RBRACKET,
            TokenKind.COMMA,
            TokenKind.GT,
            TokenKind.GT_GT,
            TokenKind.SEMICOLON,
            TokenKind.LBRACE,
            TokenKind.EQ,
            TokenKind.QUESTION,
            TokenKind.FUNCTION,
            TokenKind.EOF,
        }
    )

    def _token_kind_at(self, position: int) -> TokenKind:
        if position < len(self.tokens):
            return self.tokens[position].type
        return TokenKind.EOF

    def _scan_angle_group(self, position: int) -> int | None:
        """Return the position after a balanced ``<...>`` group."""

        if self._token_kind_at(position) != TokenKind.LT:
            return None
        depth = 1
        position += 1
        while position < len(self.tokens):
            token_kind = self._token_kind_at(position)
            if token_kind == TokenKind.LT:
                depth += 1
            elif token_kind == TokenKind.GT:
                depth -= 1
            elif token_kind == TokenKind.GT_GT:
                depth -= 2
            elif token_kind in (
                TokenKind.SEMICOLON,
                TokenKind.LBRACE,
                TokenKind.RBRACE,
                TokenKind.EOF,
            ):
                return None
            position += 1
            if depth <= 0:
                return position
        return None

    def _scan_generic_start(self, position: int) -> bool:
        """Whether the ``<`` at *position* is a generic argument list."""

        end = self._scan_angle_group(position)
        return end is not None and self._token_kind_at(end) in self._GENERIC_FOLLOWS

    def _scan_integer_base(self, position: int) -> int | None:
        token_kind = self._token_kind_at(position)
        if token_kind in (TokenKind.UNSIGNED, TokenKind.SIGNED):
            position += 1
            token_kind = self._token_kind_at(position)
            if token_kind in (TokenKind.INT, TokenKind.CHAR):
                return position + 1
            if token_kind == TokenKind.SHORT:
                position += 1
                return position + 1 if self._token_kind_at(position) == TokenKind.INT else position
            if token_kind == TokenKind.LONG:
                position += 1
                if self._token_kind_at(position) == TokenKind.LONG:
                    position += 1
                return position + 1 if self._token_kind_at(position) == TokenKind.INT else position
            return position
        if token_kind == TokenKind.SHORT:
            position += 1
            return position + 1 if self._token_kind_at(position) == TokenKind.INT else position
        if token_kind == TokenKind.LONG:
            position += 1
            if self._token_kind_at(position) == TokenKind.DOUBLE:
                return position + 1
            if self._token_kind_at(position) == TokenKind.LONG:
                position += 1
            return position + 1 if self._token_kind_at(position) == TokenKind.INT else position
        return None

    def _scan_tuple_type(self, position: int) -> int | None:
        if self._token_kind_at(position) != TokenKind.LPAREN:
            return None
        position = self._scan_type_expr(position + 1)
        if position is None or self._token_kind_at(position) != TokenKind.COMMA:
            return None
        while self._token_kind_at(position) == TokenKind.COMMA:
            position = self._scan_type_expr(position + 1)
            if position is None:
                return None
        if self._token_kind_at(position) != TokenKind.RPAREN:
            return None
        return position + 1

    def _scan_type_expr(self, position: int) -> int | None:
        """Return the first token after a type expression, or ``None``.

        This recognizer shares the parser's token stream and never produces AST
        nodes. Declaration, cast, lambda, and generic disambiguation therefore
        use one bounded lookahead owned by the stateful parser.
        """

        while self._token_kind_at(position) in self._QUALIFIERS:
            position += 1

        base_end = self._scan_integer_base(position)
        if base_end is not None:
            position = base_end
        elif self._token_kind_at(position) in (TokenKind.STRUCT, TokenKind.ENUM, TokenKind.UNION):
            if self._token_kind_at(position + 1) != TokenKind.IDENT:
                return None
            position += 2
        elif self._token_kind_at(position) in self._SIMPLE_BASES:
            position += 1
        elif self._token_kind_at(position) == TokenKind.LPAREN:
            tuple_end = self._scan_tuple_type(position)
            if tuple_end is None:
                return None
            position = tuple_end
        else:
            return None

        if self._token_kind_at(position) == TokenKind.LT and self._scan_generic_start(position):
            position = self._scan_angle_group(position)
            assert position is not None
        if (
            self._token_kind_at(position) == TokenKind.LBRACKET
            and self._token_kind_at(position + 1) == TokenKind.RBRACKET
        ):
            position += 2
        while self._token_kind_at(position) == TokenKind.STAR:
            position += 1
        if self._token_kind_at(position) == TokenKind.QUESTION:
            position += 1
        return position

    def _is_type_start(self, tok) -> bool:
        """Check if a token could start a type expression."""
        if tok.type == TokenKind.VAR:
            return True
        if tok.type in TYPE_KEYWORDS:
            return True
        if tok.type == TokenKind.IDENT:
            return True
        return tok.type == TokenKind.LPAREN and self._scan_tuple_type(self.pos) is not None

    def _parse_type_expr(self) -> TypeExpr:
        tok = self._peek()
        line, col = tok.line, tok.col

        # Handle const/static/extern/volatile qualifiers
        has_const = False
        has_static = False
        has_extern = False
        has_volatile = False
        while self._check(TokenKind.CONST, TokenKind.STATIC, TokenKind.EXTERN, TokenKind.VOLATILE):
            qt = self._peek().type
            if qt == TokenKind.CONST:
                has_const = True
            elif qt == TokenKind.STATIC:
                has_static = True
            elif qt == TokenKind.EXTERN:
                has_extern = True
            elif qt == TokenKind.VOLATILE:
                has_volatile = True
            self._advance()

        generic_args = []
        if self._check(TokenKind.UNSIGNED, TokenKind.SIGNED, TokenKind.LONG, TokenKind.SHORT):
            base = self._parse_integer_base_type()
        elif self._check(TokenKind.STRUCT):
            self._advance()
            base = "struct " + self._expect(TokenKind.IDENT, "struct name").value
        elif self._check(TokenKind.ENUM):
            self._advance()
            base = "enum " + self._expect(TokenKind.IDENT, "enum name").value
        elif self._check(TokenKind.UNION):
            self._advance()
            base = "union " + self._expect(TokenKind.IDENT, "union name").value
        elif self._check(TokenKind.LPAREN):
            base = "Tuple"
            generic_args = self._parse_tuple_type_args()
        else:
            self._refuse_deferred_c_specifier(self._peek())
            base_tok = self._advance()
            base = base_tok.value

        # CFunction is the public, exact C-callback spelling. RealtimeFunction
        # has the same one-word C representation but retains a distinct
        # semantic base so only statically proven @realtime roots can create it.
        if base == "CFunction":
            base = "__fn_ptr"
        elif base == "RealtimeFunction":
            base = "__realtime_fn_ptr"
        elif base == "_Bool":
            # C11's spelling of the boolean type (D20); int-to-bool stays refused.
            base = "bool"

        # Generic arguments
        if self._check(TokenKind.LT) and self._is_generic_start():
            self._advance()
            generic_args.append(self._parse_type_expr())
            while self._match(TokenKind.COMMA):
                generic_args.append(self._parse_type_expr())
            self._expect_gt()

        # Array suffix []
        is_array = False
        if self._check(TokenKind.LBRACKET) and self._peek(1).type == TokenKind.RBRACKET:
            self._advance()
            self._advance()
            is_array = True

        # Pointer
        pointer_depth = 0
        while self._match(TokenKind.STAR):
            pointer_depth += 1

        # Nullable: T? is sugar for T* (adds one pointer level)
        is_nullable = False
        if self._match(TokenKind.QUESTION):
            pointer_depth += 1
            is_nullable = True

        return TypeExpr(
            base=base,
            generic_args=generic_args,
            pointer_depth=pointer_depth,
            is_array=is_array,
            is_const=has_const,
            is_nullable=is_nullable,
            is_static=has_static,
            is_extern=has_extern,
            is_volatile=has_volatile,
            line=line,
            col=col,
        )

    def _parse_integer_base_type(self) -> str:
        """Parse one of btrc's C-compatible integer type spellings."""
        parts = [self._advance().value]
        first = parts[0]
        if first in ("signed", "unsigned"):
            if self._check(TokenKind.INT, TokenKind.CHAR):
                parts.append(self._advance().value)
            elif self._check(TokenKind.SHORT):
                parts.append(self._advance().value)
                if self._check(TokenKind.INT):
                    parts.append(self._advance().value)
            elif self._check(TokenKind.LONG):
                parts.append(self._advance().value)
                if self._check(TokenKind.LONG):
                    parts.append(self._advance().value)
                if self._check(TokenKind.INT):
                    parts.append(self._advance().value)
        elif first == "short":
            if self._check(TokenKind.INT):
                parts.append(self._advance().value)
        else:  # long, long int, long long [int], or long double
            if self._check(TokenKind.LONG):
                parts.append(self._advance().value)
                if self._check(TokenKind.INT):
                    parts.append(self._advance().value)
            elif self._check(TokenKind.INT, TokenKind.DOUBLE):
                parts.append(self._advance().value)
        return " ".join(parts)

    def _is_tuple_type_start(self) -> bool:
        """Check if ( starts a tuple type like (int, int)."""
        return self._scan_tuple_type(self.pos) is not None

    def _parse_tuple_type_args(self) -> list[TypeExpr]:
        """Parse tuple type: (type, type, ...)"""
        self._expect(TokenKind.LPAREN)
        types = [self._parse_type_expr()]
        self._expect(TokenKind.COMMA)
        types.append(self._parse_type_expr())
        while self._match(TokenKind.COMMA):
            types.append(self._parse_type_expr())
        self._expect(TokenKind.RPAREN)
        return types

    def _is_generic_start(self) -> bool:
        """Look ahead to determine if '<' starts generic args or is a comparison."""
        return self._scan_generic_start(self.pos)

    def _parse_declarator_array_suffix(self, type_expr: TypeExpr) -> None:
        """Parse the one array dimension representable by ``TypeExpr``."""
        if not self._check(TokenKind.LBRACKET):
            return
        if type_expr.is_array:
            raise self._error("Multi-dimensional arrays require an AST/IR representation for every dimension")
        self._advance()
        if self._check(TokenKind.RBRACKET):
            self._advance()
        else:
            type_expr.array_size = self._parse_expr()
            self._expect(TokenKind.RBRACKET)
        type_expr.is_array = True
        if type_expr.is_nullable:
            type_expr.nullable_outer_depth += 1
        if self._check(TokenKind.LBRACKET):
            raise self._error("Multi-dimensional arrays require an AST/IR representation for every dimension")

    def _parse_declarators(
        self,
        type_expr: TypeExpr,
        name_tok: Token,
        start: Token,
        *,
        prefix_array: bool,
        initializers: bool = True,
        array_suffixes: bool = True,
    ) -> list[VarDeclStmt]:
        """Parse a declaration's declarators, the first one's name and suffix already read.

        ``type_expr`` is the specifier plus the first declarator's ``*``s and
        array suffix; ``prefix_array`` says whether btrc's ``T[]`` spelling,
        which belongs to the specifier, was written before the name. Each later
        declarator binds its own ``*``s, array suffix and initializer to a deep
        copy of the specifier (C11 6.7.6, PLAN.md D20), so ``int *p, v;``
        makes ``v`` an ``int``. Initializers parse in source order. The
        declarators come back as ``VarDeclStmt`` records for the caller to
        splice; field, member and typedef callers re-shape them.
        """
        initializer = self._parse_expr() if initializers and self._match(TokenKind.EQ) else None
        declarators = [
            VarDeclStmt(
                type=type_expr,
                name=name_tok.value,
                initializer=initializer,
                line=start.line,
                col=start.col,
                name_line=name_tok.line,
                name_col=name_tok.col,
            )
        ]
        if not self._check(TokenKind.COMMA):
            return declarators
        if type_expr.is_nullable:
            raise self._error(NULLABLE_DECLARATORS)
        specifier = dataclasses.replace(
            type_expr, pointer_depth=0, is_array=prefix_array, array_size=None, nullable_outer_depth=0
        )
        while self._match(TokenKind.COMMA):
            declarator_start = self._peek()
            declarator_type = copy.deepcopy(specifier)
            while self._match(TokenKind.STAR):
                declarator_type.pointer_depth += 1
            declarator_name = self._expect(TokenKind.IDENT, "declarator name")
            if self._check(TokenKind.LPAREN):
                raise ParseError(
                    FUNCTION_BESIDE_DECLARATORS.format(declarator_name.value),
                    declarator_name.line,
                    declarator_name.col,
                )
            if array_suffixes:
                self._parse_declarator_array_suffix(declarator_type)
            initializer = self._parse_expr() if initializers and self._match(TokenKind.EQ) else None
            declarators.append(
                VarDeclStmt(
                    type=declarator_type,
                    name=declarator_name.value,
                    initializer=initializer,
                    line=declarator_start.line,
                    col=declarator_start.col,
                    name_line=declarator_name.line,
                    name_col=declarator_name.col,
                )
            )
        return declarators

    def _refuse_var_declarators(self) -> None:
        """``var`` infers one variable's type from its one initializer."""
        if self._check(TokenKind.COMMA):
            raise self._error(VAR_DECLARATORS)

    # ---- Parameters ----

    def _parse_param_list(self, *, allow_unnamed: bool = False) -> list[Param]:
        """Parse a parameter list; `(void)` is C's spelling of an empty one.

        Only a body-less function prototype may omit parameter names (C11
        6.9.1p5): its caller passes ``allow_unnamed`` and refuses a body that
        follows an unnamed parameter.
        """
        params = []
        if self._check(TokenKind.RPAREN):
            return params
        if self._check(TokenKind.VOID) and self._peek(1).type == TokenKind.RPAREN:
            self._advance()
            return params
        params.append(self._parse_param(allow_unnamed))
        while self._match(TokenKind.COMMA):
            params.append(self._parse_param(allow_unnamed))
        return params

    def _parse_param(self, allow_unnamed: bool = False) -> Param:
        tok = self._peek()
        has_keep = False
        if self._check(TokenKind.KEEP):
            has_keep = True
            self._advance()
        type_expr = self._parse_type_expr()
        if type_expr.base == "void" and type_expr.pointer_depth == 0 and not type_expr.generic_args:
            raise ParseError(VOID_PARAMETER_LIST, tok.line, tok.col)
        if self._check(TokenKind.COMMA, TokenKind.RPAREN, TokenKind.LBRACKET, TokenKind.EQ):
            if not allow_unnamed:
                raise ParseError(UNNAMED_PARAMETER, tok.line, tok.col)
            if has_keep:
                raise ParseError(UNNAMED_KEEP_PARAMETER, tok.line, tok.col)
            self._parse_declarator_array_suffix(type_expr)
            if self._check(TokenKind.EQ):
                raise self._error(UNNAMED_DEFAULT_PARAMETER)
            return Param(type=type_expr, name="", default=None, keep=False, line=tok.line, col=tok.col)
        name_tok = self._expect(TokenKind.IDENT, "parameter name")
        name = name_tok.value
        self._parse_declarator_array_suffix(type_expr)
        default = None
        if self._match(TokenKind.EQ):
            default = self._parse_expr()
        return Param(
            type=type_expr,
            name=name,
            default=default,
            keep=has_keep,
            line=tok.line,
            col=tok.col,
            name_line=name_tok.line,
            name_col=name_tok.col,
        )

    @staticmethod
    def _refuse_unnamed_definition(params: list[Param]) -> None:
        for param in params:
            if not param.name:
                raise ParseError(UNNAMED_PARAMETER, param.line, param.col)

    def _parse_top_level_items(self) -> list:
        """Parse one top-level item; a declaration contributes one node per declarator."""
        tok = self._peek()
        if tok.type == TokenKind.PREPROCESSOR:
            return [self._parse_preprocessor()]
        if tok.type == TokenKind.IMPORT:
            return [self._parse_import_decl()]

        is_gpu = False
        is_realtime = False
        keep_return = False
        if tok.type == TokenKind.AT_GPU:
            is_gpu = True
            self._advance()
            tok = self._peek()
        if tok.type == TokenKind.AT_REALTIME:
            is_realtime = True
            self._advance()
            tok = self._peek()
        if is_gpu and is_realtime:
            raise self._error("@gpu and @realtime cannot be combined")
        if tok.type == TokenKind.KEEP:
            keep_return = True
            self._advance()
            tok = self._peek()

        if tok.type == TokenKind.INTERFACE and not is_gpu and not is_realtime and not keep_return:
            return [self._parse_interface_decl()]
        if tok.type == TokenKind.ABSTRACT and not is_gpu and not is_realtime and not keep_return:
            if self._peek(1).type == TokenKind.CLASS:
                return [self._parse_class_decl(is_abstract=True)]
        if tok.type == TokenKind.CLASS and not is_gpu and not is_realtime and not keep_return:
            if self._peek(1).type == TokenKind.IDENT:
                after = self._peek(2)
                if after.type in (
                    TokenKind.LBRACE,
                    TokenKind.LT,
                    TokenKind.EXTENDS,
                    TokenKind.IMPLEMENTS,
                ):
                    return [self._parse_class_decl()]
        if tok.type == TokenKind.STRUCT and not is_gpu and not is_realtime and not keep_return:
            next_tok = self._peek(1)
            if next_tok.type == TokenKind.IDENT:
                if self._peek(2).type in (TokenKind.LBRACE, TokenKind.SEMICOLON):
                    return [self._parse_struct_decl()]
            elif next_tok.type == TokenKind.LBRACE:
                return [self._parse_struct_decl()]
        if tok.type == TokenKind.ENUM and not is_gpu and not is_realtime and not keep_return:
            if self._peek(1).type == TokenKind.CLASS:
                return [self._parse_rich_enum_decl()]
            return [self._parse_enum_decl()]
        if tok.type == TokenKind.TYPEDEF and not is_gpu and not is_realtime and not keep_return:
            return self._parse_typedef_decls()
        if self._is_type_start(tok):
            return self._parse_function_or_var_decl(is_gpu, is_realtime=is_realtime, keep_return=keep_return)
        raise self._error(f"Unexpected token '{tok.value}' at top level")

    def _parse_preprocessor(self) -> PreprocessorDirective:
        tok = self._advance()
        return PreprocessorDirective(text=tok.value, line=tok.line, col=tok.col)

    def _parse_import_decl(self) -> ImportDecl:
        """Parse an import that owns its complete source line."""
        prev = self.tokens[self.pos - 1] if self.pos > 0 else None
        tok = self._expect(TokenKind.IMPORT)
        if prev is not None and prev.line == tok.line:
            raise ParseError(
                "import must be the first token on its line "
                "(an import sharing a line with other code is never resolved)",
                tok.line,
                tok.col,
            )
        spec = self._parse_import_spec()
        end = self._match(TokenKind.SEMICOLON)
        end_tok = end if end is not None else self.tokens[self.pos - 1]
        next_token = self._peek()
        if next_token.type != TokenKind.EOF and next_token.line == end_tok.line:
            raise ParseError(
                "import must be the only statement on its line "
                "(an import sharing a line with other code is never resolved)",
                next_token.line,
                next_token.col,
            )
        return ImportDecl(spec=spec, line=tok.line, col=tok.col)

    def _parse_import_spec(self):
        if self._check(TokenKind.PATH_SPEC):
            return RelativePath(path=self._advance().value)
        if self._check(TokenKind.STRING_LIT):
            raw = self._advance().value
            if len(raw) >= 2 and raw[0] in ('"', "'") and raw[-1] == raw[0]:
                raw = raw[1:-1]
            return QuotedPath(path=raw)

        ident = self._expect(TokenKind.IDENT, "import path")
        if ident.value == "Library" and self._match(TokenKind.DOT):
            return self._parse_library_spec()
        segments = [ident.value]
        while self._match(TokenKind.DOT):
            segments.append(self._expect(TokenKind.IDENT, "package segment").value)
        return PackagePath(segments=segments)

    def _parse_library_spec(self):
        if self._match(TokenKind.STAR):
            return LibraryGlob(recursive=bool(self._match(TokenKind.STAR)))
        if self._match(TokenKind.LBRACE):
            names = [self._parse_library_module_name()]
            while self._match(TokenKind.COMMA):
                if self._check(TokenKind.RBRACE):
                    break
                names.append(self._parse_library_module_name())
            self._expect(TokenKind.RBRACE)
            return LibraryModules(names=names)
        return LibraryModules(names=[self._parse_library_module_name()])

    def _parse_library_module_name(self):
        segments = [self._expect(TokenKind.IDENT, "module name").value]
        while self._match(TokenKind.DOT):
            segments.append(self._expect(TokenKind.IDENT, "module segment").value)
        return ".".join(segments)

    def _parse_struct_decl(self) -> StructDecl:
        tok = self._expect(TokenKind.STRUCT)
        name = ""
        name_line, name_col = tok.line, tok.col
        if self._check(TokenKind.IDENT):
            name_tok = self._advance()
            name = name_tok.value
            name_line, name_col = name_tok.line, name_tok.col
        if not self._match(TokenKind.LBRACE):
            self._expect(TokenKind.SEMICOLON)
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
        while not self._check(TokenKind.RBRACE) and not self._at_end():
            field_start = self._peek()
            field_type = self._parse_type_expr()
            prefix_array = field_type.is_array
            name_tok = self._expect(TokenKind.IDENT, "field name")
            self._parse_declarator_array_suffix(field_type)
            declarators = self._parse_declarators(
                field_type, name_tok, field_start, prefix_array=prefix_array, initializers=False
            )
            # A struct field is positioned at its name.
            fields.extend(
                FieldDef(type=declarator.type, name=declarator.name, line=declarator.name_line, col=declarator.name_col)
                for declarator in declarators
            )
            self._expect(TokenKind.SEMICOLON)
        self._expect(TokenKind.RBRACE)
        self._expect(TokenKind.SEMICOLON)
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
        tok = self._expect(TokenKind.INTERFACE)
        name_tok = self._expect(TokenKind.IDENT, "interface name")

        generic_params = []
        if self._match(TokenKind.LT):
            generic_params.append(self._expect(TokenKind.IDENT, "generic param").value)
            while self._match(TokenKind.COMMA):
                generic_params.append(self._expect(TokenKind.IDENT, "generic param").value)
            self._expect_gt()

        parent = None
        if self._match(TokenKind.EXTENDS):
            parent = self._expect(TokenKind.IDENT, "parent interface name").value
        self._expect(TokenKind.LBRACE)
        methods = []
        while not self._check(TokenKind.RBRACE) and not self._at_end():
            keep_return = bool(self._match(TokenKind.KEEP))
            return_type = self._parse_type_expr()
            method_name = self._expect(TokenKind.IDENT, "method name")
            self._expect(TokenKind.LPAREN)
            params = self._parse_param_list()
            self._expect(TokenKind.RPAREN)
            self._expect(TokenKind.SEMICOLON)
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
        self._expect(TokenKind.RBRACE)
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

    def _parse_class_decl(self, is_abstract: bool = False) -> ClassDecl:
        if is_abstract:
            self._expect(TokenKind.ABSTRACT)
        tok = self._expect(TokenKind.CLASS)
        name_tok = self._expect(TokenKind.IDENT, "class name")
        name = name_tok.value

        generic_params = []
        if self._match(TokenKind.LT):
            generic_params.append(self._expect(TokenKind.IDENT, "generic param").value)
            while self._match(TokenKind.COMMA):
                generic_params.append(self._expect(TokenKind.IDENT, "generic param").value)
            self._expect_gt()

        parent = None
        if self._match(TokenKind.EXTENDS):
            parent = self._expect(TokenKind.IDENT, "parent class name").value

        interfaces = []
        if self._match(TokenKind.IMPLEMENTS):
            interfaces.append(self._expect(TokenKind.IDENT, "interface name").value)
            while self._match(TokenKind.COMMA):
                interfaces.append(self._expect(TokenKind.IDENT, "interface name").value)

        self._expect(TokenKind.LBRACE)
        members = []
        while not self._check(TokenKind.RBRACE) and not self._at_end():
            members.extend(self._parse_class_members(allow_abstract=is_abstract))
        self._expect(TokenKind.RBRACE)
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

    def _parse_class_members(self, allow_abstract: bool = False) -> list:
        """Parse one class member declaration; a field declaration yields one per declarator."""
        tok = self._peek()
        if tok.type == TokenKind.PUBLIC:
            access = "public"
            self._advance()
        elif tok.type == TokenKind.PRIVATE:
            access = "private"
            self._advance()
        elif tok.type in (TokenKind.CLASS, TokenKind.STATIC):
            access = "class"
            self._advance()
        else:
            raise self._error(f"Expected access specifier (public/private/static), got '{tok.value}'")

        is_abstract_method = False
        if allow_abstract and self._check(TokenKind.ABSTRACT):
            is_abstract_method = True
            self._advance()

        is_gpu = bool(self._match(TokenKind.AT_GPU))
        is_realtime = bool(self._match(TokenKind.AT_REALTIME))
        if is_gpu and is_realtime:
            raise self._error("@gpu and @realtime cannot be combined")
        keep_return = bool(self._match(TokenKind.KEEP))
        type_expr = self._parse_type_expr()

        if self._check(TokenKind.LPAREN):
            return [
                self._parse_method_rest(
                    access,
                    type_expr,
                    type_expr.base,
                    is_gpu,
                    is_realtime,
                    tok.line,
                    tok.col,
                    type_expr.line,
                    type_expr.col,
                    is_constructor=True,
                    is_abstract=is_abstract_method,
                    keep_return=keep_return,
                )
            ]

        name_tok = self._expect(TokenKind.IDENT, "member name")
        name = name_tok.value
        if self._check(TokenKind.LT, TokenKind.LPAREN):
            return [
                self._parse_method_rest(
                    access,
                    type_expr,
                    name,
                    is_gpu,
                    is_realtime,
                    tok.line,
                    tok.col,
                    name_tok.line,
                    name_tok.col,
                    is_abstract=is_abstract_method,
                    keep_return=keep_return,
                )
            ]
        if is_realtime:
            raise self._error("@realtime cannot be applied to fields or properties")
        prefix_array = type_expr.is_array
        self._parse_declarator_array_suffix(type_expr)
        if self._check(TokenKind.LBRACE) and self._is_property_start():
            return [
                self._parse_property(
                    access,
                    type_expr,
                    name,
                    tok.line,
                    tok.col,
                    name_tok.line,
                    name_tok.col,
                )
            ]

        # `public int x, y;` declares one field per declarator, each with its
        # own initializer; the access specifier is copied to every one.
        declarators = self._parse_declarators(type_expr, name_tok, tok, prefix_array=prefix_array)
        self._expect(TokenKind.SEMICOLON)
        return [
            FieldDecl(
                access=access,
                type=declarator.type,
                name=declarator.name,
                initializer=declarator.initializer,
                line=declarator.line,
                col=declarator.col,
                name_line=declarator.name_line,
                name_col=declarator.name_col,
            )
            for declarator in declarators
        ]

    def _parse_method_rest(
        self,
        access,
        return_type,
        name,
        is_gpu,
        is_realtime,
        line,
        col,
        name_line,
        name_col,
        is_abstract: bool = False,
        keep_return: bool = False,
        is_constructor: bool = False,
    ) -> MethodDecl:
        generic_params = []
        if self._match(TokenKind.LT):
            generic_params.append(self._expect(TokenKind.IDENT, "generic param").value)
            while self._match(TokenKind.COMMA):
                generic_params.append(self._expect(TokenKind.IDENT, "generic param").value)
            self._expect_gt()
        self._expect(TokenKind.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenKind.RPAREN)
        if is_abstract:
            self._expect(TokenKind.SEMICOLON)
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
            is_realtime=is_realtime,
            is_abstract=is_abstract,
            keep_return=keep_return,
            line=line,
            col=col,
            name_line=name_line,
            name_col=name_col,
        )

    def _is_property_start(self) -> bool:
        """Check if '{' starts a property definition (contains 'get' or 'set')."""
        save = self.pos
        self.pos += 1
        tok = self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]
        result = tok.type == TokenKind.IDENT and tok.value in ("get", "set")
        self.pos = save
        return result

    def _parse_property(self, access, type_expr, name, line, col, name_line=0, name_col=0) -> PropertyDecl:
        """Parse C#-style property: type name { get; set; } or { get { ... } set { ... } }"""
        self._expect(TokenKind.LBRACE)
        has_getter = False
        has_setter = False
        getter_body = None
        setter_body = None

        while not self._check(TokenKind.RBRACE) and not self._at_end():
            tok = self._peek()
            if tok.type == TokenKind.IDENT and tok.value == "get":
                if has_getter:
                    raise self._error("Property cannot declare 'get' more than once")
                self._advance()
                has_getter = True
                if self._match(TokenKind.SEMICOLON):
                    getter_body = None
                elif self._check(TokenKind.LBRACE):
                    getter_body = self._parse_block()
                else:
                    raise self._error("Expected ';' or '{' after 'get'")
            elif tok.type == TokenKind.IDENT and tok.value == "set":
                if has_setter:
                    raise self._error("Property cannot declare 'set' more than once")
                self._advance()
                has_setter = True
                if self._match(TokenKind.SEMICOLON):
                    setter_body = None
                elif self._check(TokenKind.LBRACE):
                    setter_body = self._parse_block()
                else:
                    raise self._error("Expected ';' or '{' after 'set'")
            else:
                raise self._error(f"Expected 'get' or 'set' in property, got '{tok.value}'")

        self._expect(TokenKind.RBRACE)
        return PropertyDecl(
            access=access,
            type=type_expr,
            name=name,
            has_getter=has_getter,
            has_setter=has_setter,
            getter_body=getter_body,
            setter_body=setter_body,
            line=line,
            col=col,
            name_line=name_line,
            name_col=name_col,
        )

    # ---- Enum declaration ----

    def _parse_enum_decl(self) -> EnumDecl:
        tok = self._expect(TokenKind.ENUM)
        name = ""
        name_line, name_col = tok.line, tok.col
        if self._check(TokenKind.IDENT):
            name_tok = self._advance()
            name = name_tok.value
            name_line, name_col = name_tok.line, name_tok.col
        self._expect(TokenKind.LBRACE)
        values = []
        while not self._check(TokenKind.RBRACE) and not self._at_end():
            vname_tok = self._expect(TokenKind.IDENT, "enum value")
            vname = vname_tok.value
            vval = None
            if self._match(TokenKind.EQ):
                vval = self._parse_expr()
            values.append(EnumValue(name=vname, value=vval, line=vname_tok.line, col=vname_tok.col))
            if not self._match(TokenKind.COMMA):
                break
        self._expect(TokenKind.RBRACE)
        self._expect(TokenKind.SEMICOLON)
        return EnumDecl(name=name, values=values, line=tok.line, col=tok.col, name_line=name_line, name_col=name_col)

    # ---- Rich enum declaration ----

    def _parse_rich_enum_decl(self) -> RichEnumDecl:
        """Parse: enum class Name { Variant1(type1 name1), Variant2, ... }"""
        tok = self._expect(TokenKind.ENUM)
        self._expect(TokenKind.CLASS)
        name_tok = self._expect(TokenKind.IDENT, "enum name")
        name = name_tok.value
        self._expect(TokenKind.LBRACE)
        variants = []
        while not self._check(TokenKind.RBRACE) and not self._at_end():
            vname_tok = self._expect(TokenKind.IDENT, "variant name")
            vname = vname_tok.value
            params = []
            if self._match(TokenKind.LPAREN):
                if not self._check(TokenKind.RPAREN):
                    params = self._parse_param_list()
                self._expect(TokenKind.RPAREN)
            variants.append(RichEnumVariant(name=vname, params=params, line=vname_tok.line, col=vname_tok.col))
            if not self._match(TokenKind.COMMA):
                break
        self._expect(TokenKind.RBRACE)
        return RichEnumDecl(
            name=name, variants=variants, line=tok.line, col=tok.col, name_line=name_tok.line, name_col=name_tok.col
        )

    # ---- Typedef declaration ----

    def _parse_typedef_decls(self) -> list[TypedefDecl]:
        """``typedef int A, *B;`` declares one alias per declarator, ``*`` bound to each."""
        tok = self._expect(TokenKind.TYPEDEF)
        original = self._parse_type_expr()
        prefix_array = original.is_array
        alias_tok = self._expect(TokenKind.IDENT, "typedef alias")
        declarators = self._parse_declarators(
            original, alias_tok, tok, prefix_array=prefix_array, initializers=False, array_suffixes=False
        )
        self._expect(TokenKind.SEMICOLON)
        return [
            TypedefDecl(
                original=declarator.type,
                alias=declarator.name,
                line=declarator.line,
                col=declarator.col,
                name_line=declarator.name_line,
                name_col=declarator.name_col,
            )
            for declarator in declarators
        ]

    # ---- Function or variable declaration ----

    def _parse_function_or_var_decl(
        self, is_gpu: bool = False, *, is_realtime: bool = False, keep_return: bool = False
    ) -> list:
        """Disambiguate function vs variables at top level."""
        start = self._peek()

        if self._check(TokenKind.VAR):
            if is_gpu or is_realtime:
                annotation = "@gpu" if is_gpu else "@realtime"
                raise self._error(f"{annotation} cannot be applied to variables")
            self._advance()
            name_tok = self._expect(TokenKind.IDENT, "variable name")
            name = name_tok.value
            self._expect(TokenKind.EQ, "'=' (var requires an initializer)")
            init = self._parse_expr()
            self._refuse_var_declarators()
            self._expect(TokenKind.SEMICOLON)
            return [
                VarDeclStmt(
                    type=None,
                    name=name,
                    initializer=init,
                    line=start.line,
                    col=start.col,
                    name_line=name_tok.line,
                    name_col=name_tok.col,
                )
            ]

        type_expr = self._parse_type_expr()
        prefix_array = type_expr.is_array
        name_tok = self._expect(TokenKind.IDENT, "name")
        name = name_tok.value
        self._parse_declarator_array_suffix(type_expr)

        if self._check(TokenKind.LPAREN):
            self._expect(TokenKind.LPAREN)
            params = self._parse_param_list(allow_unnamed=True)
            self._expect(TokenKind.RPAREN)
            if self._check(TokenKind.COMMA):
                raise ParseError(FUNCTION_BESIDE_DECLARATORS.format(name), name_tok.line, name_tok.col)
            if self._match(TokenKind.SEMICOLON):
                return [
                    FunctionDecl(
                        return_type=type_expr,
                        name=name,
                        params=params,
                        body=None,
                        is_gpu=is_gpu,
                        is_realtime=is_realtime,
                        keep_return=keep_return,
                        line=start.line,
                        col=start.col,
                        name_line=name_tok.line,
                        name_col=name_tok.col,
                    )
                ]
            if self._check(TokenKind.LBRACE):
                self._refuse_unnamed_definition(params)
            body = self._parse_block()
            return [
                FunctionDecl(
                    return_type=type_expr,
                    name=name,
                    params=params,
                    body=body,
                    is_gpu=is_gpu,
                    is_realtime=is_realtime,
                    keep_return=keep_return,
                    line=start.line,
                    col=start.col,
                    name_line=name_tok.line,
                    name_col=name_tok.col,
                )
            ]
        if is_gpu or is_realtime:
            annotation = "@gpu" if is_gpu else "@realtime"
            raise self._error(f"{annotation} cannot be applied to variables")
        declarators = self._parse_declarators(type_expr, name_tok, start, prefix_array=prefix_array)
        self._expect(TokenKind.SEMICOLON)
        return declarators

    def _parse_block(self) -> Block:
        tok = self._expect(TokenKind.LBRACE)
        stmts = []
        while not self._check(TokenKind.RBRACE) and not self._at_end():
            # An empty statement inside a statement list produces nothing.
            if self._match(TokenKind.SEMICOLON):
                continue
            self._parse_block_item(stmts)
        self._expect(TokenKind.RBRACE)
        return Block(statements=stmts, line=tok.line, col=tok.col)

    def _parse_block_item(self, statements: list) -> None:
        """Append one block item; a declaration splices one statement per declarator."""
        if self._is_var_decl_start():
            statements.extend(self._parse_var_decl_stmts())
        else:
            statements.append(self._parse_statement())

    def _parse_body(self) -> Block:
        """Parse the substatement of ``if``/``else``/``while``/C-``for``/``do``.

        A braced body is its own block. Any other statement is wrapped in a
        synthesized ``Block`` positioned at the statement's first token, so
        the body keeps exactly the scope a braced body has; an empty
        statement ``;`` becomes an empty ``Block`` positioned at the ``;``.
        A declaration is not a statement in C (C11 6.8), so it is refused as
        a body. ``for``-in, parallel ``for``, ``try``/``catch``/``finally``
        and ``switch`` keep requiring braces through ``_parse_block``.
        """
        tok = self._peek()
        if tok.type == TokenKind.LBRACE:
            return self._parse_block()
        if self._match(TokenKind.SEMICOLON):
            return Block(statements=[], line=tok.line, col=tok.col)
        if self._is_var_decl_start():
            raise self._error("A declaration cannot be the body of a control statement; enclose it in braces")
        return Block(statements=[self._parse_statement()], line=tok.line, col=tok.col)

    def _parse_statement(self):
        tok = self._peek()

        if tok.type == TokenKind.LBRACE:
            return self._parse_block()
        if tok.type == TokenKind.RETURN:
            return self._parse_return_stmt()
        if tok.type == TokenKind.IF:
            return self._parse_if_stmt()
        if tok.type == TokenKind.WHILE:
            return self._parse_while_stmt()
        if tok.type == TokenKind.DO:
            return self._parse_do_while_stmt()
        if tok.type == TokenKind.FOR:
            return self._parse_for_stmt()
        if tok.type == TokenKind.PARALLEL:
            return self._parse_parallel_for_stmt()
        if tok.type == TokenKind.SWITCH:
            return self._parse_switch_stmt()
        if tok.type == TokenKind.BREAK:
            self._advance()
            self._expect(TokenKind.SEMICOLON)
            return BreakStmt(line=tok.line, col=tok.col)
        if tok.type == TokenKind.CONTINUE:
            self._advance()
            self._expect(TokenKind.SEMICOLON)
            return ContinueStmt(line=tok.line, col=tok.col)
        if tok.type == TokenKind.TRY:
            return self._parse_try_catch()
        if tok.type == TokenKind.THROW:
            return self._parse_throw()
        if tok.type == TokenKind.DELETE:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenKind.SEMICOLON)
            return DeleteStmt(expr=expr, line=tok.line, col=tok.col)
        if tok.type == TokenKind.RELEASE:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenKind.SEMICOLON)
            return ReleaseStmt(expr=expr, line=tok.line, col=tok.col)
        if tok.type == TokenKind.KEEP:
            self._advance()
            expr = self._parse_expr()
            self._expect(TokenKind.SEMICOLON)
            return KeepStmt(expr=expr, line=tok.line, col=tok.col)

        return self._parse_expr_stmt()

    # ---- Variable declaration detection ----

    def _is_var_decl_start(self) -> bool:
        """Lookahead to determine if current position starts a variable declaration."""
        tok = self._peek()

        if tok.type == TokenKind.VAR:
            return True
        return self._lookahead_is_var_decl()

    def _lookahead_is_var_decl(self) -> bool:
        """Recognize a complete type, name, and declaration boundary."""
        type_end = self._scan_type_expr(self.pos)
        if type_end is None or type_end >= len(self.tokens):
            return False
        if self.tokens[type_end].type != TokenKind.IDENT:
            # `int string = 0;` is a declaration the name check refuses;
            # `int function(...)` stays a verbose lambda.
            return self._is_reserved_name(type_end) and self._token_kind_at(type_end + 1) in (
                TokenKind.EQ,
                TokenKind.SEMICOLON,
                TokenKind.LBRACKET,
                TokenKind.COMMA,
            )
        if self.tokens[type_end].value in self._DEFERRED_C_SPECIFIERS:
            return True
        after_name = type_end + 1
        if after_name >= len(self.tokens):
            return False
        return self.tokens[after_name].type in (
            TokenKind.EQ,
            TokenKind.SEMICOLON,
            TokenKind.LBRACKET,
            TokenKind.COMMA,
        )

    # ---- Variable declaration ----

    def _parse_var_decl_stmts(self) -> list[VarDeclStmt]:
        """Parse one block-scope declaration into one statement per declarator."""
        tok = self._peek()
        declarators = self._parse_declaration_head(tok)
        self._expect(TokenKind.SEMICOLON)
        return declarators

    def _parse_declaration_head(self, tok: Token) -> list[VarDeclStmt]:
        """Parse a block-scope or C-for declaration up to its terminator."""
        if self._check(TokenKind.VAR):
            self._advance()
            name_tok = self._expect(TokenKind.IDENT, "variable name")
            name = name_tok.value
            self._expect(TokenKind.EQ, "'=' (var requires an initializer)")
            init = self._parse_expr()
            self._refuse_var_declarators()
            return [
                VarDeclStmt(
                    type=None,
                    name=name,
                    initializer=init,
                    line=tok.line,
                    col=tok.col,
                    name_line=name_tok.line,
                    name_col=name_tok.col,
                )
            ]

        type_expr = self._parse_type_expr()
        prefix_array = type_expr.is_array
        name_tok = self._expect(TokenKind.IDENT, "variable name")
        self._parse_declarator_array_suffix(type_expr)
        return self._parse_declarators(type_expr, name_tok, tok, prefix_array=prefix_array)

    def _parse_return_stmt(self) -> ReturnStmt:
        tok = self._expect(TokenKind.RETURN)
        value = None
        if not self._check(TokenKind.SEMICOLON):
            value = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return ReturnStmt(value=value, line=tok.line, col=tok.col)

    def _parse_if_stmt(self) -> IfStmt:
        tok = self._expect(TokenKind.IF)
        self._expect(TokenKind.LPAREN)
        condition = self._parse_expr()
        self._expect(TokenKind.RPAREN)
        then_block = self._parse_body()
        else_block = None
        if self._match(TokenKind.ELSE):
            if self._check(TokenKind.IF):
                else_block = ElseIf(if_stmt=self._parse_if_stmt())
            else:
                else_block = ElseBlock(body=self._parse_body())
        return IfStmt(condition=condition, then_block=then_block, else_block=else_block, line=tok.line, col=tok.col)

    def _parse_while_stmt(self) -> WhileStmt:
        tok = self._expect(TokenKind.WHILE)
        self._expect(TokenKind.LPAREN)
        condition = self._parse_expr()
        self._expect(TokenKind.RPAREN)
        body = self._parse_body()
        return WhileStmt(condition=condition, body=body, line=tok.line, col=tok.col)

    def _parse_do_while_stmt(self) -> DoWhileStmt:
        tok = self._expect(TokenKind.DO)
        body = self._parse_body()
        self._expect(TokenKind.WHILE)
        self._expect(TokenKind.LPAREN)
        condition = self._parse_expr()
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.SEMICOLON)
        return DoWhileStmt(body=body, condition=condition, line=tok.line, col=tok.col)

    def _parse_for_stmt(self):
        """Disambiguate for-in vs C for."""
        tok = self._expect(TokenKind.FOR)

        # for-in: 'for' IDENT 'in' expr block
        if self._check(TokenKind.IDENT) and self._peek(1).type == TokenKind.IN:
            var_name = self._advance().value
            self._expect(TokenKind.IN)
            iterable = self._parse_expr()
            body = self._parse_block()
            return ForInStmt(var_name=var_name, iterable=iterable, body=body, line=tok.line, col=tok.col)

        # for-in (map): 'for' IDENT ',' IDENT 'in' expr block
        if (
            self._check(TokenKind.IDENT)
            and self._peek(1).type == TokenKind.COMMA
            and self._peek(2).type == TokenKind.IDENT
            and self._peek(3).type == TokenKind.IN
        ):
            var_name = self._advance().value
            self._expect(TokenKind.COMMA)
            var_name2 = self._advance().value
            self._expect(TokenKind.IN)
            iterable = self._parse_expr()
            body = self._parse_block()
            return ForInStmt(
                var_name=var_name, var_name2=var_name2, iterable=iterable, body=body, line=tok.line, col=tok.col
            )

        # C for: 'for' '(' init ';' cond ';' update ')' block
        self._expect(TokenKind.LPAREN)

        init = None
        if not self._check(TokenKind.SEMICOLON):
            if self._is_var_decl_start():
                init = ForInitVar(declarations=self._parse_declaration_head(self._peek()))
            else:
                init = ForInitExpr(expression=self._parse_for_header_expr())
        self._expect(TokenKind.SEMICOLON)

        condition = None
        if not self._check(TokenKind.SEMICOLON):
            condition = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)

        update = None
        if not self._check(TokenKind.RPAREN):
            update = self._parse_for_header_expr()
        self._expect(TokenKind.RPAREN)

        body = self._parse_body()
        return CForStmt(init=init, condition=condition, update=update, body=body, line=tok.line, col=tok.col)

    def _parse_for_header_expr(self):
        """A C-``for`` initializer or update: C's comma operator (D19 row 19).

        Two or more operands become a ``CommaExpr`` positioned at its first
        operand; a single operand stays a plain expression. The condition and
        every other position keep ``(a, b)`` a tuple.
        """
        first = self._parse_expr()
        if not self._check(TokenKind.COMMA):
            return first
        elements = [first]
        while self._match(TokenKind.COMMA):
            elements.append(self._parse_expr())
        return CommaExpr(elements=elements, line=first.line, col=first.col)

    def _parse_parallel_for_stmt(self) -> ParallelForStmt:
        tok = self._expect(TokenKind.PARALLEL)
        self._expect(TokenKind.FOR)
        var_name = self._expect(TokenKind.IDENT, "loop variable").value
        self._expect(TokenKind.IN)
        iterable = self._parse_expr()
        body = self._parse_block()
        return ParallelForStmt(var_name=var_name, iterable=iterable, body=body, line=tok.line, col=tok.col)

    def _parse_switch_stmt(self) -> SwitchStmt:
        tok = self._expect(TokenKind.SWITCH)
        self._expect(TokenKind.LPAREN)
        value = self._parse_expr()
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.LBRACE)
        cases = []
        while not self._check(TokenKind.RBRACE) and not self._at_end():
            cases.append(self._parse_case_clause())
        self._expect(TokenKind.RBRACE)
        return SwitchStmt(value=value, cases=cases, line=tok.line, col=tok.col)

    def _parse_case_clause(self) -> CaseClause:
        tok = self._peek()
        value = None
        if self._match(TokenKind.CASE):
            value = self._parse_expr()
        elif self._match(TokenKind.DEFAULT):
            value = None
        else:
            raise self._error(f"Expected 'case' or 'default', got '{tok.value}'")
        self._expect(TokenKind.COLON)
        body = []
        while not self._check(TokenKind.CASE, TokenKind.DEFAULT, TokenKind.RBRACE) and not self._at_end():
            if self._match(TokenKind.SEMICOLON):
                continue
            self._parse_block_item(body)
        return CaseClause(value=value, body=body, line=tok.line, col=tok.col)

    def _parse_try_catch(self) -> TryCatchStmt:
        tok = self._expect(TokenKind.TRY)
        try_block = self._parse_block()
        catch_var = ""
        catch_type = None
        catch_block = None
        if self._match(TokenKind.CATCH):
            self._expect(TokenKind.LPAREN)
            if self._is_type_start(self._peek()) and self._peek(1).type == TokenKind.IDENT:
                catch_type = self._parse_type_expr()  # optional type annotation
            catch_var = self._expect(TokenKind.IDENT, "catch variable").value
            self._expect(TokenKind.RPAREN)
            catch_block = self._parse_block()
        finally_block = None
        if self._match(TokenKind.FINALLY):
            finally_block = self._parse_block()
        if catch_block is None and finally_block is None:
            raise self._error("Expected 'catch' or 'finally' after try block")
        return TryCatchStmt(
            try_block=try_block,
            catch_var=catch_var,
            catch_type=catch_type,
            catch_block=catch_block,
            finally_block=finally_block,
            line=tok.line,
            col=tok.col,
        )

    def _parse_throw(self) -> ThrowStmt:
        tok = self._expect(TokenKind.THROW)
        expr = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return ThrowStmt(expr=expr, line=tok.line, col=tok.col)

    def _parse_expr_stmt(self) -> ExprStmt:
        tok = self._peek()
        expr = self._parse_expr()
        self._expect(TokenKind.SEMICOLON)
        return ExprStmt(expr=expr, line=tok.line, col=tok.col)

    def _parse_expr(self):
        return self._parse_assignment()

    def _parse_assignment(self):
        left = self._parse_ternary()
        assign_ops = {
            TokenKind.EQ,
            TokenKind.PLUS_EQ,
            TokenKind.MINUS_EQ,
            TokenKind.STAR_EQ,
            TokenKind.SLASH_EQ,
            TokenKind.PERCENT_EQ,
            TokenKind.AMP_EQ,
            TokenKind.PIPE_EQ,
            TokenKind.CARET_EQ,
            TokenKind.LT_LT_EQ,
            TokenKind.GT_GT_EQ,
        }
        if self._peek().type in assign_ops:
            op_tok = self._advance()
            right = self._parse_assignment()
            return AssignExpr(target=left, op=op_tok.value, value=right, line=left.line, col=left.col)
        return left

    def _parse_ternary(self):
        expr = self._parse_null_coalesce()
        if self._match(TokenKind.QUESTION):
            true_expr = self._parse_expr()
            self._expect(TokenKind.COLON)
            false_expr = self._parse_ternary()
            return TernaryExpr(condition=expr, true_expr=true_expr, false_expr=false_expr, line=expr.line, col=expr.col)
        return expr

    def _parse_null_coalesce(self):
        left = self._parse_logical_or()
        while self._match(TokenKind.QUESTION_QUESTION):
            right = self._parse_logical_or()
            left = BinaryExpr(left=left, op="??", right=right, line=left.line, col=left.col)
        return left

    def _parse_logical_or(self):
        left = self._parse_logical_and()
        while self._match(TokenKind.PIPE_PIPE):
            right = self._parse_logical_and()
            left = BinaryExpr(left=left, op="||", right=right, line=left.line, col=left.col)
        return left

    def _parse_logical_and(self):
        left = self._parse_bitwise_or()
        while self._match(TokenKind.AMP_AMP):
            right = self._parse_bitwise_or()
            left = BinaryExpr(left=left, op="&&", right=right, line=left.line, col=left.col)
        return left

    def _parse_bitwise_or(self):
        left = self._parse_bitwise_xor()
        while self._match(TokenKind.PIPE):
            right = self._parse_bitwise_xor()
            left = BinaryExpr(left=left, op="|", right=right, line=left.line, col=left.col)
        return left

    def _parse_bitwise_xor(self):
        left = self._parse_bitwise_and()
        while self._match(TokenKind.CARET):
            right = self._parse_bitwise_and()
            left = BinaryExpr(left=left, op="^", right=right, line=left.line, col=left.col)
        return left

    def _parse_bitwise_and(self):
        left = self._parse_equality()
        while self._match(TokenKind.AMP):
            right = self._parse_equality()
            left = BinaryExpr(left=left, op="&", right=right, line=left.line, col=left.col)
        return left

    def _parse_equality(self):
        left = self._parse_relational()
        while self._check(TokenKind.EQ_EQ, TokenKind.BANG_EQ):
            op = self._advance().value
            right = self._parse_relational()
            left = BinaryExpr(left=left, op=op, right=right, line=left.line, col=left.col)
        return left

    def _parse_relational(self):
        left = self._parse_shift()
        while self._check(TokenKind.LT, TokenKind.GT, TokenKind.LT_EQ, TokenKind.GT_EQ):
            op = self._advance().value
            right = self._parse_shift()
            left = BinaryExpr(left=left, op=op, right=right, line=left.line, col=left.col)
        return left

    def _parse_shift(self):
        left = self._parse_additive()
        while self._check(TokenKind.LT_LT, TokenKind.GT_GT):
            op = self._advance().value
            right = self._parse_additive()
            left = BinaryExpr(left=left, op=op, right=right, line=left.line, col=left.col)
        return left

    def _parse_additive(self):
        left = self._parse_multiplicative()
        while self._check(TokenKind.PLUS, TokenKind.MINUS):
            op = self._advance().value
            right = self._parse_multiplicative()
            left = BinaryExpr(left=left, op=op, right=right, line=left.line, col=left.col)
        return left

    def _parse_multiplicative(self):
        left = self._parse_unary()
        while self._check(TokenKind.STAR, TokenKind.SLASH, TokenKind.PERCENT):
            op = self._advance().value
            right = self._parse_unary()
            left = BinaryExpr(left=left, op=op, right=right, line=left.line, col=left.col)
        return left

    def _parse_unary(self):
        tok = self._peek()

        # Unary +/- and !/~ all share the same shape. Unary + is a C-style
        # no-op kept for source compatibility (e.g. +5, +x); IR gen treats it
        # as identity. The grammar's `unary` rule lists "+", so accepting it
        # keeps spec and parser aligned.
        if tok.type in (TokenKind.BANG, TokenKind.TILDE, TokenKind.PLUS, TokenKind.MINUS):
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op=tok.value, operand=operand, prefix=True, line=tok.line, col=tok.col)
        if tok.type == TokenKind.PLUS_PLUS:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="++", operand=operand, prefix=True, line=tok.line, col=tok.col)
        if tok.type == TokenKind.MINUS_MINUS:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="--", operand=operand, prefix=True, line=tok.line, col=tok.col)
        if tok.type == TokenKind.STAR:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="*", operand=operand, prefix=True, line=tok.line, col=tok.col)
        if tok.type == TokenKind.AMP:
            self._advance()
            operand = self._parse_unary()
            return UnaryExpr(op="&", operand=operand, prefix=True, line=tok.line, col=tok.col)
        if tok.type == TokenKind.SIZEOF:
            return self._parse_sizeof()
        if tok.type == TokenKind.LPAREN and self._is_cast():
            return self._parse_cast()

        return self._parse_postfix()

    _CAST_FOLLOW_TOKENS = (
        TokenKind.IDENT,
        TokenKind.INT_LIT,
        TokenKind.FLOAT_LIT,
        TokenKind.STRING_LIT,
        TokenKind.CHAR_LIT,
        TokenKind.FSTRING_LIT,
        TokenKind.LPAREN,
        TokenKind.SIZEOF,
        TokenKind.STAR,
        TokenKind.AMP,
        TokenKind.BANG,
        TokenKind.TILDE,
        TokenKind.PLUS,
        TokenKind.MINUS,
        TokenKind.PLUS_PLUS,
        TokenKind.MINUS_MINUS,
        TokenKind.SELF,
        TokenKind.TRUE,
        TokenKind.FALSE,
        TokenKind.NULL,
        TokenKind.NEW,
        TokenKind.SPAWN,
    )

    # For a parenthesized bare identifier `(a)` the follow tokens PLUS, MINUS,
    # STAR, and AMP are ambiguous: `(a) - 1` / `(a) + 1` is far more likely a
    # grouped expression and a binary operator than a cast of `-1` / `+1` to
    # type `a`. Only unambiguous follows (tokens that cannot continue a binary
    # expression) make a bare-identifier paren a cast. Explicit type syntax
    # ((int), (Foo*), (Vector<int>), (Foo?)) keeps the full follow set.
    _BARE_IDENT_CAST_FOLLOW = tuple(
        t for t in _CAST_FOLLOW_TOKENS if t not in (TokenKind.PLUS, TokenKind.MINUS, TokenKind.STAR, TokenKind.AMP)
    )

    def _is_cast(self) -> bool:
        """Check if '(' starts a cast expression."""
        type_start = self.pos + 1
        type_end = self._scan_type_expr(type_start)
        if type_end is None or type_end >= len(self.tokens) or self.tokens[type_end].type != TokenKind.RPAREN:
            return False
        follow_pos = type_end + 1
        if follow_pos >= len(self.tokens):
            return False
        bare_ident = self.tokens[type_start].type == TokenKind.IDENT and type_end == type_start + 1
        follow = self._BARE_IDENT_CAST_FOLLOW if bare_ident else self._CAST_FOLLOW_TOKENS
        return self.tokens[follow_pos].type in follow

    def _parse_cast(self) -> CastExpr:
        tok = self._expect(TokenKind.LPAREN)
        target_type = self._parse_type_expr()
        self._expect(TokenKind.RPAREN)
        expr = self._parse_unary()
        return CastExpr(target_type=target_type, expr=expr, line=tok.line, col=tok.col)

    def _parse_sizeof(self) -> SizeofExpr:
        tok = self._expect(TokenKind.SIZEOF)
        self._expect(TokenKind.LPAREN)
        if self._is_type_start(self._peek()) and self._is_sizeof_type():
            operand = SizeofType(type=self._parse_type_expr())
        else:
            operand = SizeofExprOp(expr=self._parse_expr())
        self._expect(TokenKind.RPAREN)
        return SizeofExpr(operand=operand, line=tok.line, col=tok.col)

    def _is_sizeof_type(self) -> bool:
        """Lookahead to check if sizeof contains a type."""
        type_end = self._scan_type_expr(self.pos)
        return type_end is not None and type_end < len(self.tokens) and self.tokens[type_end].type == TokenKind.RPAREN

    def _parse_postfix(self):
        expr = self._parse_primary()

        while True:
            tok = self._peek()

            if tok.type == TokenKind.LPAREN:
                self._advance()
                args, arg_names = self._parse_arg_list()
                self._expect(TokenKind.RPAREN)
                expr = CallExpr(callee=expr, args=args, arg_names=arg_names, line=expr.line, col=expr.col)

            elif tok.type == TokenKind.LBRACKET:
                self._advance()
                index = self._parse_expr()
                self._expect(TokenKind.RBRACKET)
                expr = IndexExpr(obj=expr, index=index, line=expr.line, col=expr.col)

            elif tok.type == TokenKind.DOT:
                self._advance()
                if self._check(TokenKind.INT_LIT):
                    idx_tok = self._advance()
                    field_name = f"_{idx_tok.value}"
                else:
                    field_name = self._member_name().value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=False, line=expr.line, col=expr.col)

            elif tok.type == TokenKind.QUESTION_DOT:
                self._advance()
                field_name = self._member_name().value
                expr = FieldAccessExpr(
                    obj=expr, field=field_name, arrow=True, optional=True, line=expr.line, col=expr.col
                )

            elif tok.type == TokenKind.ARROW:
                self._advance()
                field_name = self._member_name().value
                expr = FieldAccessExpr(obj=expr, field=field_name, arrow=True, line=expr.line, col=expr.col)

            elif tok.type == TokenKind.PLUS_PLUS:
                self._advance()
                expr = UnaryExpr(op="++", operand=expr, prefix=False, line=expr.line, col=expr.col)

            elif tok.type == TokenKind.MINUS_MINUS:
                self._advance()
                expr = UnaryExpr(op="--", operand=expr, prefix=False, line=expr.line, col=expr.col)

            else:
                break

        return expr

    def _parse_primary(self):
        tok = self._peek()

        if tok.type == TokenKind.INT_LIT:
            self._advance()
            try:
                value = LiteralDecoder.parse_integer_value(tok.value)
            except ValueError:
                raise ParseError(f"Invalid integer literal '{tok.value}'", tok.line, tok.col) from None
            return IntLiteral(value=value, raw=tok.value, line=tok.line, col=tok.col)

        if tok.type == TokenKind.FLOAT_LIT:
            self._advance()
            raw = tok.value
            fval = raw.rstrip("fF")
            value = float(fval)
            problem = LiteralDecoder.float_problem(raw, value)
            if problem is not None:
                raise ParseError(problem, tok.line, tok.col)
            return FloatLiteral(value=value, raw=raw, line=tok.line, col=tok.col)

        if tok.type == TokenKind.STRING_LIT:
            self._advance()
            return self._parse_adjacent_strings(StringLiteral(value=tok.value, line=tok.line, col=tok.col))

        if tok.type == TokenKind.CHAR_LIT:
            self._advance()
            return CharLiteral(value=tok.value, line=tok.line, col=tok.col)

        if tok.type == TokenKind.FSTRING_LIT:
            if self._peek(1).type in (TokenKind.STRING_LIT, TokenKind.FSTRING_LIT):
                raise ParseError(self._ADJACENT_FSTRING, tok.line, tok.col)
            self._advance()
            return self._parse_fstring(tok)

        if tok.type == TokenKind.TRUE:
            self._advance()
            return BoolLiteral(value=True, line=tok.line, col=tok.col)
        if tok.type == TokenKind.FALSE:
            self._advance()
            return BoolLiteral(value=False, line=tok.line, col=tok.col)

        if tok.type == TokenKind.NULL:
            self._advance()
            return NullLiteral(line=tok.line, col=tok.col)

        if tok.type == TokenKind.SELF:
            self._advance()
            return SelfExpr(line=tok.line, col=tok.col)

        if tok.type == TokenKind.SUPER:
            self._advance()
            return SuperExpr(line=tok.line, col=tok.col)

        if tok.type == TokenKind.NEW:
            return self._parse_new_expr()

        if tok.type == TokenKind.SPAWN:
            return self._parse_spawn_expr()

        # Verbose lambda: type function(params) { body }
        if self._is_type_start(tok) and self._is_verbose_lambda():
            return self._parse_verbose_lambda()

        # Parenthesized expression, tuple literal, or arrow lambda
        if tok.type == TokenKind.LPAREN:
            if self._is_arrow_lambda():
                return self._parse_arrow_lambda()
            self._advance()
            expr = self._parse_expr()
            if self._match(TokenKind.COMMA):
                elements = [expr]
                elements.append(self._parse_expr())
                while self._match(TokenKind.COMMA):
                    elements.append(self._parse_expr())
                self._expect(TokenKind.RPAREN)
                return TupleLiteral(elements=elements, line=tok.line, col=tok.col)
            self._expect(TokenKind.RPAREN)
            return expr

        if tok.type == TokenKind.LBRACKET:
            return self._parse_list_literal()

        if tok.type == TokenKind.LBRACE:
            return self._parse_map_or_brace_initializer()

        if tok.type == TokenKind.IDENT:
            self._refuse_deferred_c_specifier(tok)
            self._advance()
            identifier = Identifier(name=tok.value, line=tok.line, col=tok.col)
            if self._check(TokenKind.STRING_LIT) and not self._is_encoding_prefix(tok, self._peek()):
                return self._parse_adjacent_strings(identifier)
            return identifier

        raise self._error(f"Unexpected token '{tok.value}' in expression")

    _ADJACENT_FSTRING = "An f-string cannot be concatenated with an adjacent string literal"

    @staticmethod
    def _is_encoding_prefix(name, following) -> bool:
        """Whether ``L``, ``u``, ``U`` or ``u8`` touches the literal after it.

        An encoding prefix is part of its literal, not a macro piece, so it is
        never absorbed into a concatenation; any other name is a piece.
        """
        return (
            name.value in {"L", "u", "U", "u8"}
            and following.type == TokenKind.STRING_LIT
            and following.line == name.line
            and following.col == name.col + len(name.value)
        )

    def _parse_adjacent_strings(self, first):
        """Absorb the literals and macro names adjacent to ``first`` (C phase 6).

        A lone literal stays a ``StringLiteral``. Each piece keeps its own token
        spelling, so escapes never run across a piece boundary; the analyzer
        resolves a name piece to the string literal its source macro expands to.
        """
        parts = [first]
        while True:
            tok = self._peek()
            if tok.type == TokenKind.STRING_LIT:
                self._advance()
                parts.append(StringLiteral(value=tok.value, line=tok.line, col=tok.col))
            elif tok.type == TokenKind.IDENT and not self._is_encoding_prefix(tok, self._peek(1)):
                self._advance()
                parts.append(Identifier(name=tok.value, line=tok.line, col=tok.col))
            elif tok.type == TokenKind.FSTRING_LIT:
                raise ParseError(self._ADJACENT_FSTRING, first.line, first.col)
            else:
                break
        if len(parts) == 1:
            return first
        return StringConcat(parts=parts, line=first.line, col=first.col)

    # ---- Compound literals ----

    def _parse_new_expr(self) -> NewExpr:
        tok = self._expect(TokenKind.NEW)
        type_expr = self._parse_type_expr()
        self._expect(TokenKind.LPAREN)
        args, arg_names = self._parse_arg_list()
        self._expect(TokenKind.RPAREN)
        return NewExpr(type=type_expr, args=args, arg_names=arg_names, line=tok.line, col=tok.col)

    def _parse_spawn_expr(self) -> SpawnExpr:
        tok = self._expect(TokenKind.SPAWN)
        self._expect(TokenKind.LPAREN)
        fn = self._parse_expr()
        self._expect(TokenKind.RPAREN)
        return SpawnExpr(fn=fn, line=tok.line, col=tok.col)

    def _parse_list_literal(self) -> ListLiteral:
        tok = self._expect(TokenKind.LBRACKET)
        elements = []
        if not self._check(TokenKind.RBRACKET):
            elements.append(self._parse_expr())
            while self._match(TokenKind.COMMA):
                if self._check(TokenKind.RBRACKET):
                    break
                elements.append(self._parse_expr())
        self._expect(TokenKind.RBRACKET)
        return ListLiteral(elements=elements, line=tok.line, col=tok.col)

    def _parse_map_or_brace_initializer(self):
        """Parse the first expression before deciding map versus initializer."""
        tok = self._expect(TokenKind.LBRACE)
        if self._match(TokenKind.RBRACE):
            return BraceInitializer(elements=[], line=tok.line, col=tok.col)

        first = self._parse_expr()
        if self._match(TokenKind.COLON):
            entries = [MapEntry(key=first, value=self._parse_expr())]
            while self._match(TokenKind.COMMA):
                if self._check(TokenKind.RBRACE):
                    break
                key = self._parse_expr()
                self._expect(TokenKind.COLON)
                entries.append(MapEntry(key=key, value=self._parse_expr()))
            self._expect(TokenKind.RBRACE)
            return MapLiteral(entries=entries, line=tok.line, col=tok.col)

        elements = [first]
        while self._match(TokenKind.COMMA):
            if self._check(TokenKind.RBRACE):
                break
            elements.append(self._parse_expr())
        self._expect(TokenKind.RBRACE)
        return BraceInitializer(elements=elements, line=tok.line, col=tok.col)

    def _is_verbose_lambda(self) -> bool:
        """Check if current position starts a verbose lambda: type function(...)"""
        type_end = self._scan_type_expr(self.pos)
        return type_end is not None and type_end < len(self.tokens) and self.tokens[type_end].type == TokenKind.FUNCTION

    def _parse_verbose_lambda(self) -> LambdaExpr:
        """Parse verbose lambda: type function(params) { body }"""
        tok = self._peek()
        return_type = self._parse_type_expr()
        self._expect(TokenKind.FUNCTION, "'function'")
        self._expect(TokenKind.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenKind.RPAREN)
        body = LambdaBlock(body=self._parse_block())
        return LambdaExpr(return_type=return_type, params=params, body=body, captures=[], line=tok.line, col=tok.col)

    def _is_arrow_lambda(self) -> bool:
        """Check if '(' starts an arrow lambda: (type name, ...) => ..."""
        if not self._check(TokenKind.LPAREN):
            return False
        depth = 0
        pos = self.pos
        while pos < len(self.tokens):
            token_type = self.tokens[pos].type
            if token_type == TokenKind.LPAREN:
                depth += 1
            elif token_type == TokenKind.RPAREN:
                depth -= 1
                if depth == 0:
                    return pos + 1 < len(self.tokens) and self.tokens[pos + 1].type == TokenKind.FAT_ARROW
            elif token_type == TokenKind.EOF:
                return False
            pos += 1
        return False

    def _parse_arrow_lambda(self) -> LambdaExpr:
        """Parse arrow lambda: (params) => expr  or  (params) => { body }"""
        tok = self._peek()
        self._expect(TokenKind.LPAREN)
        params = self._parse_param_list()
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.FAT_ARROW, "'=>'")
        if self._check(TokenKind.LBRACE):
            body = LambdaBlock(body=self._parse_block())
        else:
            expr = self._parse_expr()
            body = LambdaExprBody(expression=expr)
        return LambdaExpr(return_type=None, params=params, body=body, captures=[], line=tok.line, col=tok.col)

    # ---- F-string parsing ----

    @staticmethod
    def _fstring_position(tok, raw: str, index: int) -> tuple[int, int]:
        """Map an offset in an f-string's body to its line and column in the source."""
        line = tok.line
        col = tok.col + 2
        for ch in raw[:index]:
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
        return line, col

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
                expr_line, expr_col = self._fstring_position(tok, raw, i)
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
                sub_tokens = Lexer(expr_src + ";", line=expr_line, col=expr_col).tokenize()
                sub_parser = Parser(sub_tokens)
                expr_node = sub_parser._parse_expr()
                sub_parser._expect(TokenKind.SEMICOLON)
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
