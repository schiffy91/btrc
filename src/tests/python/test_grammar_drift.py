"""Grammar-vs-parser drift regression tests.

These tests pin down the real parser behavior for the syntax surfaces that the
@syntax section of src/language/grammar.ebnf documents. Each test corresponds to
a row of the grammar-drift audit: the parser is the de-facto language, so these
assertions keep the spec claims honest and catch any future regression.
"""

import pytest

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError, Parser
from src.compiler.python.syntax.ast.generated import (
    BinaryExpr,
    BraceInitializer,
    CastExpr,
    ClassDecl,
    EnumDecl,
    FieldAccessExpr,
    InterfaceDecl,
    ListLiteral,
    MapLiteral,
    SpawnExpr,
    StructDecl,
    TryCatchStmt,
    UnaryExpr,
)


def parse(source: str):
    return Parser(Lexer(source).tokenize()).parse()


def parse_expr(source: str):
    """Parse a single expression as the RHS of a var-decl initializer."""
    prog = parse(f"void __t__() {{ int __z__ = {source}; }}")
    return prog.declarations[0].body.statements[0].initializer


def parse_stmt(source: str):
    prog = parse(f"void __t__() {{ {source} }}")
    return prog.declarations[0].body.statements[0]


# ---- #1 unary + (PARSER FIX: accepted as C-style no-op) ----


class TestUnaryPlus:
    def test_unary_plus_literal(self):
        expr = parse_expr("+5")
        assert isinstance(expr, UnaryExpr)
        assert expr.op == "+"
        assert expr.prefix is True

    def test_unary_plus_ident(self):
        expr = parse_expr("+x")
        assert isinstance(expr, UnaryExpr)
        assert expr.op == "+"

    def test_unary_plus_nested_with_minus(self):
        expr = parse_expr("-+x")
        assert isinstance(expr, UnaryExpr)
        assert expr.op == "-"
        assert isinstance(expr.operand, UnaryExpr)
        assert expr.operand.op == "+"

    def test_binary_plus_still_works(self):
        expr = parse_expr("a + b")
        assert isinstance(expr, BinaryExpr)
        assert expr.op == "+"


# ---- #2 cast disambiguation (mostly already-fixed; spawn is a parser fix) ----


class TestCastDisambiguation:
    def test_cast_of_sizeof(self):
        assert isinstance(parse_expr("(int)sizeof(int)"), CastExpr)

    def test_cast_of_negative(self):
        assert isinstance(parse_expr("(int)-1"), CastExpr)

    def test_cast_of_unary_plus(self):
        assert isinstance(parse_expr("(int)+x"), CastExpr)

    def test_pointer_cast(self):
        assert isinstance(parse_expr("(Foo*)x"), CastExpr)

    def test_cast_of_fstring(self):
        assert isinstance(parse_expr('(int)f"x"'), CastExpr)

    def test_cast_of_new(self):
        assert isinstance(parse_expr("(int)new Foo()"), CastExpr)

    def test_cast_of_spawn(self):
        # The cast-follow set must include `spawn`.
        expr = parse_expr("(int)spawn(() => { return 1; })")
        assert isinstance(expr, CastExpr)
        assert isinstance(expr.expr, SpawnExpr)

    def test_bare_ident_paren_minus_is_grouping(self):
        assert isinstance(parse_expr("(a) - 1"), BinaryExpr)

    def test_bare_ident_paren_plus_is_grouping(self):
        assert isinstance(parse_expr("(a) + 1"), BinaryExpr)

    def test_bare_ident_paren_star_is_grouping(self):
        assert isinstance(parse_expr("(a) * b"), BinaryExpr)


# ---- #3 try/catch: catch optional, optional type annotation ----


class TestTryCatch:
    def test_try_finally_without_catch(self):
        stmt = parse_stmt("try { } finally { }")
        assert isinstance(stmt, TryCatchStmt)
        assert stmt.catch_block is None
        assert stmt.finally_block is not None

    def test_catch_with_type_annotation(self):
        stmt = parse_stmt("try { } catch (Error e) { }")
        assert isinstance(stmt, TryCatchStmt)
        assert stmt.catch_var == "e"

    def test_catch_without_type_annotation(self):
        stmt = parse_stmt("try { } catch (e) { }")
        assert isinstance(stmt, TryCatchStmt)
        assert stmt.catch_var == "e"

    def test_try_alone_is_error(self):
        with pytest.raises(ParseError):
            parse_stmt("try { }")


# ---- #4 static access modifier ----


class TestStaticAccess:
    def test_static_member_method(self):
        prog = parse("class C { static int f() { return 1; } }")
        cls = prog.declarations[0]
        assert isinstance(cls, ClassDecl)
        # `static` is normalized to the same access bucket as `class`.
        assert cls.members[0].access == "class"

    def test_class_keyword_static_member(self):
        prog = parse("class C { class int f() { return 1; } }")
        assert prog.declarations[0].members[0].access == "class"


# ---- #5 member modifier order: abstract @gpu keep ----


class TestMemberModifiers:
    def test_keep_field(self):
        prog = parse("class C { public keep C x; }")
        assert isinstance(prog.declarations[0], ClassDecl)

    def test_gpu_keep_method(self):
        prog = parse("class C { public @gpu keep int f() { return 1; } }")
        m = prog.declarations[0].members[0]
        assert m.is_gpu is True
        assert m.keep_return is True

    def test_abstract_only_in_abstract_class(self):
        prog = parse("abstract class C { public abstract int f(); }")
        assert prog.declarations[0].members[0].is_abstract is True

    def test_full_modifier_order_abstract_gpu_keep(self):
        prog = parse("abstract class C { public abstract @gpu keep int f(); }")
        m = prog.declarations[0].members[0]
        assert m.is_abstract and m.is_gpu and m.keep_return

    def test_abstract_in_plain_class_is_error(self):
        with pytest.raises(ParseError):
            parse("class C { public abstract int f(); }")


# ---- #6 interface: generic params + keep method sigs ----


class TestInterfaceDecl:
    def test_generic_interface(self):
        prog = parse("interface Box<T> { int f(); }")
        iface = prog.declarations[0]
        assert isinstance(iface, InterfaceDecl)
        assert iface.generic_params == ["T"]

    def test_keep_method_signature(self):
        prog = parse("interface I { keep int f(); }")
        assert prog.declarations[0].methods[0].keep_return is True


# ---- #7 struct: anonymous + forward declarations ----


class TestStructDecl:
    def test_anonymous_struct(self):
        prog = parse("struct { int x; };")
        s = prog.declarations[0]
        assert isinstance(s, StructDecl)
        assert s.name == ""
        assert len(s.fields) == 1

    def test_forward_struct(self):
        prog = parse("struct Foo;")
        s = prog.declarations[0]
        assert isinstance(s, StructDecl)
        assert s.name == "Foo"
        assert s.fields == []

    def test_named_struct_with_body(self):
        prog = parse("struct Foo { int x; };")
        assert prog.declarations[0].name == "Foo"


# ---- #8 enum: anonymous ----


class TestEnumDecl:
    def test_anonymous_enum(self):
        prog = parse("enum { A, B };")
        e = prog.declarations[0]
        assert isinstance(e, EnumDecl)
        assert e.name == ""
        assert [v.name for v in e.values] == ["A", "B"]

    def test_named_enum(self):
        prog = parse("enum Color { Red, Green };")
        assert prog.declarations[0].name == "Color"


# ---- #9 param: keep qualifier ----


class TestKeepParam:
    def test_keep_param(self):
        prog = parse("void f(keep C x) { }")
        param = prog.declarations[0].params[0]
        assert param.keep is True
        assert param.name == "x"

    def test_plain_param_not_keep(self):
        prog = parse("void f(C x) { }")
        assert prog.declarations[0].params[0].keep is False


# ---- #11 trailing commas in list / map / brace literals ----


class TestTrailingCommas:
    def test_list_trailing_comma(self):
        expr = parse_expr("[1, 2, 3,]")
        assert isinstance(expr, ListLiteral)
        assert len(expr.elements) == 3

    def test_map_trailing_comma(self):
        expr = parse_expr("{1: 2, 3: 4,}")
        assert isinstance(expr, MapLiteral)
        assert len(expr.entries) == 2

    def test_brace_trailing_comma(self):
        expr = parse_expr("{1, 2, 3,}")
        assert isinstance(expr, BraceInitializer)
        assert len(expr.elements) == 3


# ---- #12 override / reserved-but-unparseable keywords ----


class TestReservedKeywords:
    def test_override_member_is_parse_error(self):
        # `override` is reserved (a keyword) but no member rule consumes it.
        with pytest.raises(ParseError):
            parse("class C { public override int f() { return 1; } }")


# ---- #14 tuple access x.0 works, x.0.1 mis-lexes ----


class TestTupleAccess:
    def test_single_tuple_access(self):
        expr = parse_expr("x.0")
        assert isinstance(expr, FieldAccessExpr)
        assert expr.field == "_0"

    def test_chained_tuple_access_workaround(self):
        # Parenthesizing avoids the FLOAT_LIT mis-lex of `0.1`.
        expr = parse_expr("(x.0).1")
        assert isinstance(expr, FieldAccessExpr)
        assert expr.field == "_1"

    def test_chained_tuple_access_mislexes(self):
        # Documented limitation: x.0.1 lexes `0.1` as a FLOAT_LIT.
        with pytest.raises(ParseError):
            parse_expr("x.0.1")
