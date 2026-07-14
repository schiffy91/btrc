"""Type expression and parameter parsing."""

from ..ast_nodes import Param, TypeExpr
from ..tokens import TYPE_KEYWORDS, TokenType
from .type_lookahead import (
    is_generic_start,
    is_tuple_type_start,
)


class TypesMixin:
    def _is_type_start(self, tok) -> bool:
        """Check if a token could start a type expression."""
        if tok.type == TokenType.VAR:
            return True
        if tok.type in TYPE_KEYWORDS:
            return True
        if tok.type == TokenType.IDENT:
            return True
        return tok.type == TokenType.LPAREN and is_tuple_type_start(self.tokens, self.pos)

    def _parse_type_expr(self) -> TypeExpr:
        tok = self._peek()
        line, col = tok.line, tok.col

        # Handle const/static/extern/volatile qualifiers
        has_const = False
        has_static = False
        has_extern = False
        has_volatile = False
        while self._check(TokenType.CONST, TokenType.STATIC, TokenType.EXTERN, TokenType.VOLATILE):
            qt = self._peek().type
            if qt == TokenType.CONST:
                has_const = True
            elif qt == TokenType.STATIC:
                has_static = True
            elif qt == TokenType.EXTERN:
                has_extern = True
            elif qt == TokenType.VOLATILE:
                has_volatile = True
            self._advance()

        generic_args = []
        if self._check(TokenType.UNSIGNED, TokenType.SIGNED, TokenType.LONG, TokenType.SHORT):
            base = self._parse_integer_base_type()
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
            base = "Tuple"
            generic_args = self._parse_tuple_type_args()
        else:
            base_tok = self._advance()
            base = base_tok.value

        # Generic arguments
        if self._check(TokenType.LT) and self._is_generic_start():
            self._advance()
            generic_args.append(self._parse_type_expr())
            while self._match(TokenType.COMMA):
                generic_args.append(self._parse_type_expr())
            self._expect_gt()

        # Array suffix []
        is_array = False
        if self._check(TokenType.LBRACKET) and self._peek(1).type == TokenType.RBRACKET:
            self._advance()
            self._advance()
            is_array = True

        # Pointer
        pointer_depth = 0
        while self._match(TokenType.STAR):
            pointer_depth += 1

        # Nullable: T? is sugar for T* (adds one pointer level)
        is_nullable = False
        if self._match(TokenType.QUESTION):
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
            if self._check(TokenType.INT, TokenType.CHAR):
                parts.append(self._advance().value)
            elif self._check(TokenType.SHORT):
                parts.append(self._advance().value)
                if self._check(TokenType.INT):
                    parts.append(self._advance().value)
            elif self._check(TokenType.LONG):
                parts.append(self._advance().value)
                if self._check(TokenType.LONG):
                    parts.append(self._advance().value)
                if self._check(TokenType.INT):
                    parts.append(self._advance().value)
        elif first == "short":
            if self._check(TokenType.INT):
                parts.append(self._advance().value)
        else:  # long, long int, long long [int], or long double
            if self._check(TokenType.LONG):
                parts.append(self._advance().value)
                if self._check(TokenType.INT):
                    parts.append(self._advance().value)
            elif self._check(TokenType.INT, TokenType.DOUBLE):
                parts.append(self._advance().value)
        return " ".join(parts)

    def _is_tuple_type_start(self) -> bool:
        """Check if ( starts a tuple type like (int, int)."""
        return is_tuple_type_start(self.tokens, self.pos)

    def _parse_tuple_type_args(self) -> list[TypeExpr]:
        """Parse tuple type: (type, type, ...)"""
        self._expect(TokenType.LPAREN)
        types = [self._parse_type_expr()]
        self._expect(TokenType.COMMA)
        types.append(self._parse_type_expr())
        while self._match(TokenType.COMMA):
            types.append(self._parse_type_expr())
        self._expect(TokenType.RPAREN)
        return types

    def _is_generic_start(self) -> bool:
        """Look ahead to determine if '<' starts generic args or is a comparison."""
        return is_generic_start(self.tokens, self.pos)

    def _parse_declarator_array_suffix(self, type_expr: TypeExpr) -> None:
        """Parse the one array dimension representable by ``TypeExpr``."""
        if not self._check(TokenType.LBRACKET):
            return
        if type_expr.is_array:
            raise self._error("Multi-dimensional arrays require an AST/IR representation for every dimension")
        self._advance()
        if self._check(TokenType.RBRACKET):
            self._advance()
        else:
            type_expr.array_size = self._parse_expr()
            self._expect(TokenType.RBRACKET)
        type_expr.is_array = True
        if self._check(TokenType.LBRACKET):
            raise self._error("Multi-dimensional arrays require an AST/IR representation for every dimension")

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
        has_keep = False
        if self._check(TokenType.KEEP):
            has_keep = True
            self._advance()
        type_expr = self._parse_type_expr()
        name_tok = self._expect(TokenType.IDENT, "parameter name")
        name = name_tok.value
        self._parse_declarator_array_suffix(type_expr)
        default = None
        if self._match(TokenType.EQ):
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
