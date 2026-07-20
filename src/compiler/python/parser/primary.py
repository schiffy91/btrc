"""Primary expression parsing: literals, identifiers, new, list, map, brace."""

from ..ast_nodes import (
    BoolLiteral,
    BraceInitializer,
    CharLiteral,
    FloatLiteral,
    Identifier,
    IntLiteral,
    ListLiteral,
    MapEntry,
    MapLiteral,
    NewExpr,
    NullLiteral,
    SelfExpr,
    SpawnExpr,
    StringLiteral,
    SuperExpr,
    TupleLiteral,
)
from ..numeric_literals import (
    float_literal_problem,
    integer_literal_type,
)
from ..tokens import TokenType
from .core import ParseError

# Valid C integer suffixes, lowercased (combos of u and l/ll)
_INT_SUFFIXES = frozenset(("u", "ul", "ull", "l", "ll", "lu", "llu"))


def _int_literal_value(raw: str) -> int:
    """Convert an INT_LIT token value to int, honoring C suffixes and octal.

    Raises ValueError on malformed literals (caller maps to ParseError).
    """
    body = raw
    suffix = ""
    while body and body[-1] in "uUlL":
        suffix = body[-1] + suffix
        body = body[:-1]
    if suffix and suffix.lower() not in _INT_SUFFIXES:
        raise ValueError(f"invalid integer suffix '{suffix}'")
    if not body:
        raise ValueError("empty integer literal")
    # C-style octal: leading zero with no 0x/0b/0o prefix (e.g. 0123)
    if len(body) > 1 and body[0] == "0" and body[1] not in "xXbBoO":
        return int(body, 8)
    return int(body, 0)


class PrimaryMixin:
    def _parse_primary(self):
        tok = self._peek()

        if tok.type == TokenType.INT_LIT:
            self._advance()
            try:
                value = _int_literal_value(tok.value)
                integer_literal_type(tok.value, value)
            except ValueError:
                raise ParseError(f"Invalid integer literal '{tok.value}'", tok.line, tok.col) from None
            return IntLiteral(value=value, raw=tok.value, line=tok.line, col=tok.col)

        if tok.type == TokenType.FLOAT_LIT:
            self._advance()
            raw = tok.value
            fval = raw.rstrip("fF")
            value = float(fval)
            problem = float_literal_problem(raw, value)
            if problem is not None:
                raise ParseError(problem, tok.line, tok.col)
            return FloatLiteral(value=value, raw=raw, line=tok.line, col=tok.col)

        if tok.type == TokenType.STRING_LIT:
            self._advance()
            return StringLiteral(value=tok.value, line=tok.line, col=tok.col)

        if tok.type == TokenType.CHAR_LIT:
            self._advance()
            return CharLiteral(value=tok.value, line=tok.line, col=tok.col)

        if tok.type == TokenType.FSTRING_LIT:
            self._advance()
            return self._parse_fstring(tok)

        if tok.type == TokenType.TRUE:
            self._advance()
            return BoolLiteral(value=True, line=tok.line, col=tok.col)
        if tok.type == TokenType.FALSE:
            self._advance()
            return BoolLiteral(value=False, line=tok.line, col=tok.col)

        if tok.type == TokenType.NULL:
            self._advance()
            return NullLiteral(line=tok.line, col=tok.col)

        if tok.type == TokenType.SELF:
            self._advance()
            return SelfExpr(line=tok.line, col=tok.col)

        if tok.type == TokenType.SUPER:
            self._advance()
            return SuperExpr(line=tok.line, col=tok.col)

        if tok.type == TokenType.NEW:
            return self._parse_new_expr()

        if tok.type == TokenType.SPAWN:
            return self._parse_spawn_expr()

        # Verbose lambda: type function(params) { body }
        if self._is_type_start(tok) and self._is_verbose_lambda():
            return self._parse_verbose_lambda()

        # Parenthesized expression, tuple literal, or arrow lambda
        if tok.type == TokenType.LPAREN:
            if self._is_arrow_lambda():
                return self._parse_arrow_lambda()
            self._advance()
            expr = self._parse_expr()
            if self._match(TokenType.COMMA):
                elements = [expr]
                elements.append(self._parse_expr())
                while self._match(TokenType.COMMA):
                    elements.append(self._parse_expr())
                self._expect(TokenType.RPAREN)
                return TupleLiteral(elements=elements, line=tok.line, col=tok.col)
            self._expect(TokenType.RPAREN)
            return expr

        if tok.type == TokenType.LBRACKET:
            return self._parse_list_literal()

        if tok.type == TokenType.LBRACE:
            return self._parse_map_or_brace_initializer()

        if tok.type == TokenType.IDENT:
            self._advance()
            return Identifier(name=tok.value, line=tok.line, col=tok.col)

        raise self._error(f"Unexpected token '{tok.value}' in expression")

    # ---- Compound literals ----

    def _parse_new_expr(self) -> NewExpr:
        tok = self._expect(TokenType.NEW)
        type_expr = self._parse_type_expr()
        self._expect(TokenType.LPAREN)
        args, arg_names = self._parse_arg_list()
        self._expect(TokenType.RPAREN)
        return NewExpr(type=type_expr, args=args, arg_names=arg_names, line=tok.line, col=tok.col)

    def _parse_spawn_expr(self) -> SpawnExpr:
        tok = self._expect(TokenType.SPAWN)
        self._expect(TokenType.LPAREN)
        fn = self._parse_expr()
        self._expect(TokenType.RPAREN)
        return SpawnExpr(fn=fn, line=tok.line, col=tok.col)

    def _parse_list_literal(self) -> ListLiteral:
        tok = self._expect(TokenType.LBRACKET)
        elements = []
        if not self._check(TokenType.RBRACKET):
            elements.append(self._parse_expr())
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACKET):
                    break
                elements.append(self._parse_expr())
        self._expect(TokenType.RBRACKET)
        return ListLiteral(elements=elements, line=tok.line, col=tok.col)

    def _parse_map_or_brace_initializer(self):
        """Parse the first expression before deciding map versus initializer."""
        tok = self._expect(TokenType.LBRACE)
        if self._match(TokenType.RBRACE):
            return BraceInitializer(elements=[], line=tok.line, col=tok.col)

        first = self._parse_expr()
        if self._match(TokenType.COLON):
            entries = [MapEntry(key=first, value=self._parse_expr())]
            while self._match(TokenType.COMMA):
                if self._check(TokenType.RBRACE):
                    break
                key = self._parse_expr()
                self._expect(TokenType.COLON)
                entries.append(MapEntry(key=key, value=self._parse_expr()))
            self._expect(TokenType.RBRACE)
            return MapLiteral(entries=entries, line=tok.line, col=tok.col)

        elements = [first]
        while self._match(TokenType.COMMA):
            if self._check(TokenType.RBRACE):
                break
            elements.append(self._parse_expr())
        self._expect(TokenType.RBRACE)
        return BraceInitializer(elements=elements, line=tok.line, col=tok.col)
