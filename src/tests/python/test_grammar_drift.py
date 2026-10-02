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
    CForStmt,
    ClassDecl,
    ElseBlock,
    EnumDecl,
    ExprStmt,
    FieldAccessExpr,
    Identifier,
    IfStmt,
    InterfaceDecl,
    ListLiteral,
    MapLiteral,
    ReturnStmt,
    SpawnExpr,
    StringConcat,
    StringLiteral,
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


# ---- C rows 2 and 6: braceless bodies and the empty statement ----


class TestBracelessBodies:
    def test_body_is_a_block_at_its_first_token(self):
        stmt = parse("void t() {\n\tif (a)\n\t\tb = 1;\n\telse\n\t\tb = 2;\n}").declarations[0].body.statements[0]
        assert isinstance(stmt, IfStmt)
        assert (stmt.then_block.line, stmt.then_block.col) == (3, 3)
        assert len(stmt.then_block.statements) == 1
        assert isinstance(stmt.else_block, ElseBlock)
        assert (stmt.else_block.body.line, stmt.else_block.body.col) == (5, 3)

    def test_dangling_else_binds_to_the_nearest_if(self):
        stmt = parse_stmt("if (a) if (b) c = 1; else c = 2;")
        assert stmt.else_block is None
        inner = stmt.then_block.statements[0]
        assert isinstance(inner, IfStmt)
        assert isinstance(inner.else_block, ElseBlock)

    def test_loop_bodies(self):
        assert isinstance(parse_stmt("while (a) a--;").body.statements[0], ExprStmt)
        assert isinstance(parse_stmt("for (i = 0; i < 2; i++) a++;").body.statements[0], ExprStmt)
        assert isinstance(parse_stmt("do a++; while (a < 2);").body.statements[0], ExprStmt)

    def test_empty_statement_body_is_an_empty_block_at_the_semicolon(self):
        stmt = parse_stmt("for (i = 0; i < 2; i++);")
        assert isinstance(stmt, CForStmt)
        assert stmt.body.statements == []
        assert (stmt.body.line, stmt.body.col) == (1, 39)

    def test_empty_statement_in_a_list_produces_nothing(self):
        body = parse("int t() { ; a = 1;; ; return a;; }").declarations[0].body
        assert [type(statement) for statement in body.statements] == [ExprStmt, ReturnStmt]

    def test_declaration_body_is_refused(self):
        with pytest.raises(ParseError, match="A declaration cannot be the body of a control statement"):
            parse_stmt("if (a) int b = 1;")

    def test_stray_file_scope_semicolon_is_refused(self):
        with pytest.raises(ParseError, match="Unexpected token ';' at top level"):
            parse("int t() { return 0; };")

    def test_braced_only_statements_stay_braced(self):
        for source in ("for x in xs x++;", "try x++; catch (e) {}", "switch (x) x++;"):
            with pytest.raises(ParseError, match="Expected LBRACE"):
                parse_stmt(source)


# ---- C row 1: (void) and unnamed prototype parameters ----


class TestCParameterLists:
    def test_void_is_an_empty_list_everywhere(self):
        prog = parse(
            "int f(void);\nint g(void) { return 0; }\n"
            "interface I { int m(void); }\n"
            "class C { public C(void) {} public int m(void) { return 1; } }\n"
            "enum class E { A(void) }\n"
        )
        function, definition, interface, klass, rich = prog.declarations
        assert function.params == [] and definition.params == []
        assert interface.methods[0].params == []
        assert [member.params for member in klass.members] == [[], []]
        assert rich.variants[0].params == []
        assert parse_expr("(void) => 1").params == []
        assert parse_expr("int function(void) { return 1; }").params == []

    def test_prototype_parameter_without_a_name(self):
        param = parse("int f(int, char*);").declarations[0].params[1]
        assert param.name == "" and param.type.base == "char" and param.type.pointer_depth == 1
        assert (param.line, param.col, param.name_line, param.name_col) == (1, 12, 0, 0)

    @pytest.mark.parametrize(
        "source",
        [
            "int f(void x);",
            "int f(void, int y);",
            "int f(const void);",
            "int f(int) { return 0; }",
            "void f(keep int);",
            "int f(int = 3);",
            "class C { public int m(int) { return 0; } }",
            "interface I { int m(int); }",
            "enum class E { A(int) }",
        ],
    )
    def test_refused_parameter_forms(self, source):
        with pytest.raises(ParseError):
            parse(source)

    def test_unnamed_lambda_parameter_is_refused(self):
        with pytest.raises(ParseError):
            parse_expr("(int) => 1")


# ---- string_concat: adjacent literals (C translation phase 6) ----


class TestStringConcat:
    def test_lone_literal_stays_a_string_literal(self):
        expr = parse_expr('"abc"')
        assert isinstance(expr, StringLiteral)

    def test_adjacent_literals_keep_each_spelling(self):
        expr = parse_expr('"\\x4" "1"')
        assert isinstance(expr, StringConcat)
        assert [part.value for part in expr.parts] == ['"\\x4"', '"1"']
        assert (expr.line, expr.col) == (expr.parts[0].line, expr.parts[0].col)

    def test_macro_name_pieces_on_either_side(self):
        expr = parse_expr('PREFIX "mid" SUFFIX')
        assert isinstance(expr, StringConcat)
        assert [type(part) for part in expr.parts] == [Identifier, StringLiteral, Identifier]

    def test_triple_quoted_piece(self):
        expr = parse_expr('"a" """b"""')
        assert isinstance(expr, StringConcat)
        assert expr.parts[1].value == '"b"'

    @pytest.mark.parametrize("source", ['f"{1}" "tail"', '"head" f"{1}"', 'f"{1}" f"{2}"'])
    def test_fstring_beside_a_literal_is_refused(self, source):
        with pytest.raises(ParseError, match="An f-string cannot be concatenated with an adjacent string literal"):
            parse_expr(source)

    def test_quoted_import_path_never_concatenates(self):
        with pytest.raises(ParseError):
            parse('import "a.btrc" "b.btrc";\nint main() { return 0; }')

    def test_a_name_touching_a_literal_is_a_piece_unless_a_prefix(self):
        expr = parse_expr('TAG"b"')
        assert isinstance(expr, StringConcat)
        assert expr.parts[0].name == "TAG"

    def test_encoding_prefix_is_never_a_piece(self):
        with pytest.raises(ParseError, match="Expected SEMICOLON"):
            parse('void __t__() { char* text = L"ab"; }')
        with pytest.raises(ParseError, match="Expected SEMICOLON"):
            parse('void __t__() { char* text = "a" u8"b"; }')


# ---- C row 7: function-pointer declarators ----


def _cfunction(type_expr) -> tuple:
    """A function-pointer TypeExpr as (result, parameters...) base spellings."""
    assert type_expr.base == "__fn_ptr"
    return tuple(f"{arg.base}{'*' * arg.pointer_depth}" for arg in type_expr.generic_args)


class TestFunctionPointerDeclarators:
    def test_every_declarator_position_builds_cfunction(self):
        prog = parse(
            "typedef int (*Op)(int, int);\n"
            "static char* (*hook)(const char* text);\n"
            "int (*table[4])(int);\n"
            "struct S { void (*reset)(void); };\n"
            "class C { public int (*handler)(int) = null; }\n"
            "int apply(int (*f)(int), int (*)(void*));\n"
        )
        typedef, hook, table, struct, klass, function = prog.declarations
        assert typedef.alias == "Op" and _cfunction(typedef.original) == ("int", "int", "int")
        assert hook.name == "hook" and _cfunction(hook.type) == ("char*", "char*")
        assert hook.type.is_static and not hook.type.generic_args[0].is_static
        assert table.name == "table" and table.type.is_array and table.type.array_size.value == 4
        assert struct.fields[0].name == "reset" and _cfunction(struct.fields[0].type) == ("void",)
        assert klass.members[0].name == "handler" and _cfunction(klass.members[0].type) == ("int", "int")
        named, unnamed = function.params
        assert named.name == "f" and unnamed.name == "" and _cfunction(unnamed.type) == ("int", "void*")

    def test_local_declarations_and_their_positions(self):
        statement = parse_stmt("int (*operation)(int, int) = add;")
        assert (statement.name, statement.line, statement.col) == ("operation", 1, 16)
        assert (statement.name_line, statement.name_col) == (1, 22)
        assert _cfunction(statement.type) == ("int", "int", "int")

    def test_abstract_declarators_in_casts_and_sizeof(self):
        cast = parse_expr("(int (*)(const void*, const void*))compare")
        assert isinstance(cast, CastExpr) and _cfunction(cast.target_type) == ("int", "void*", "void*")
        size = parse_expr("sizeof(void (*)(int))")
        assert _cfunction(size.operand.type) == ("void", "int")

    def test_pointee_parameters(self):
        param = parse("int f(int (*g)(int (*)(int), int values[3]));").declarations[0].params[0]
        inner, array = param.type.generic_args[1:]
        assert _cfunction(inner) == ("int", "int") and array.pointer_depth == 1 and not array.is_array
        assert parse("int f(int (*g)());").declarations[0].params[0].type.generic_args[1:] == []

    def test_a_head_that_is_not_a_type_stays_an_expression(self):
        assert isinstance(parse_stmt("pick (*pointer)(4);"), ExprStmt)
        assert isinstance(parse_stmt("pick (*pointer)(value);"), ExprStmt)
        assert parse_stmt("Count (*scale)(Count value);").name == "scale"
        assert parse_stmt("Count (*scale)(const Count*);").name == "scale"
        assert parse_stmt("Count (*scale)(Count) = twice;").name == "scale"
        prog = parse("typedef int Count;\nvoid __t__() { Count (*scale)(Count); }")
        assert prog.declarations[1].body.statements[0].name == "scale"

    @pytest.mark.parametrize(
        "source",
        [
            "int (*pick(int))(int);",
            "void (*report)(const char*, ...);",
            "int (**indirect)(int);",
            "int (* const fixed)(int);",
            "typedef int Unary(int);",
            "int size = sizeof(int (*[3])(int));",
            "int apply(int (*)(int)) { return 0; }",
            "int apply(int (*g)(void, int));",
        ],
    )
    def test_refused_declarator_forms(self, source):
        with pytest.raises(ParseError):
            parse(source)
