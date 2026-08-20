"""S0 parser bug regression tests: integer suffixes (S0-2), cast ambiguity (S0-1)."""

import pytest

from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import (
    BinaryExpr,
    CastExpr,
    Identifier,
    IntLiteral,
    Program,
    SizeofExpr,
    UnaryExpr,
)


def parse(source: str) -> Program:
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def parse_expr(source: str):
    prog = parse(f"void __test__() {{ var __x = {source}; }}")
    return prog.declarations[0].body.statements[0].initializer


# --- S0-2: integer literal suffixes and C-style octal ---


class TestIntLiteralSuffixes:
    def test_unsigned_suffix(self):
        lit = parse_expr("10u")
        assert isinstance(lit, IntLiteral)
        assert lit.value == 10
        assert lit.raw == "10u"

    def test_hex_with_ul_suffix(self):
        lit = parse_expr("0xFFul")
        assert isinstance(lit, IntLiteral)
        assert lit.value == 255
        assert lit.raw == "0xFFul"

    def test_long_long_suffixes(self):
        for raw, val in (("7L", 7), ("7ll", 7), ("7LL", 7), ("7ull", 7), ("7llu", 7), ("7lU", 7), ("0x10U", 16)):
            lit = parse_expr(raw)
            assert isinstance(lit, IntLiteral)
            assert lit.value == val, raw
            assert lit.raw == raw

    def test_binary_with_suffix(self):
        lit = parse_expr("0b101u")
        assert isinstance(lit, IntLiteral)
        assert lit.value == 5

    def test_leading_zero_octal_like_c(self):
        lit = parse_expr("0123")
        assert isinstance(lit, IntLiteral)
        assert lit.value == 0o123  # 83, C octal semantics

    def test_plain_zero_still_works(self):
        lit = parse_expr("0")
        assert lit.value == 0

    def test_python_octal_prefix_still_works(self):
        lit = parse_expr("0o17")
        assert lit.value == 15

    def test_malformed_octal_fails_at_the_lexical_boundary(self):
        # 09 is not valid C-style octal and must never reach either parser as a
        # seemingly valid token (or leak a raw Python ValueError).
        with pytest.raises(LexerError) as exc:
            parse("void f() { int x = 09; }")
        assert exc.value.line == 1


# --- S0-1a: parenthesized single identifier vs cast ---


class TestCastDisambiguation:
    def test_paren_ident_minus_is_binary(self):
        expr = parse_expr("(a) - 1")
        assert isinstance(expr, BinaryExpr)
        assert expr.op == "-"
        assert isinstance(expr.left, Identifier)
        assert expr.left.name == "a"

    def test_paren_ident_star_is_binary(self):
        expr = parse_expr("(a) * b")
        assert isinstance(expr, BinaryExpr)
        assert expr.op == "*"

    def test_paren_ident_amp_is_binary(self):
        expr = parse_expr("(a) & b")
        assert isinstance(expr, BinaryExpr)
        assert expr.op == "&"

    def test_paren_ident_ident_is_cast(self):
        expr = parse_expr("(MyType) x")
        assert isinstance(expr, CastExpr)
        assert expr.target_type.base == "MyType"

    def test_keyword_cast_of_negative_still_works(self):
        expr = parse_expr("(int)-1")
        assert isinstance(expr, CastExpr)
        assert expr.target_type.base == "int"
        assert isinstance(expr.expr, UnaryExpr)

    def test_pointer_cast_still_works(self):
        expr = parse_expr("(Foo*) p")
        assert isinstance(expr, CastExpr)
        assert expr.target_type.base == "Foo"
        assert expr.target_type.pointer_depth == 1

    def test_explicit_pointer_cast_of_deref(self):
        # Explicit type syntax keeps the wider follow set.
        expr = parse_expr("(Foo*) *p")
        assert isinstance(expr, CastExpr)
        assert isinstance(expr.expr, UnaryExpr)

    def test_generic_cast_still_works(self):
        expr = parse_expr("(Vector<int>) v")
        assert isinstance(expr, CastExpr)
        assert expr.target_type.base == "Vector"

    def test_keyword_cast_of_sizeof(self):
        expr = parse_expr("(int)sizeof(int)")
        assert isinstance(expr, CastExpr)
        assert isinstance(expr.expr, SizeofExpr)

    def test_ident_cast_of_sizeof(self):
        expr = parse_expr("(MyType)sizeof(int)")
        assert isinstance(expr, CastExpr)
        assert isinstance(expr.expr, SizeofExpr)

    def test_paren_expr_chain_in_arithmetic(self):
        # Regression shape: (n) - 1 inside a larger expression
        expr = parse_expr("(n) - 1 + (m) * 2")
        assert isinstance(expr, BinaryExpr)
        assert expr.op == "+"
