"""Tests for the btrc parser."""

import pytest
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.parser.core import ParseError
from src.compiler.python.ast_nodes import (
    AssignExpr,
    BinaryExpr,
    Block,
    BoolLiteral,
    BraceInitializer,
    BreakStmt,
    CallExpr,
    CastExpr,
    CForStmt,
    CharLiteral,
    ClassDecl,
    ContinueStmt,
    DeleteStmt,
    DoWhileStmt,
    ElseBlock,
    ElseIf,
    EnumDecl,
    FieldAccessExpr,
    FieldDecl,
    FloatLiteral,
    ForInitVar,
    ForInStmt,
    FStringExpr,
    FStringLiteral,
    FStringText,
    FunctionDecl,
    Identifier,
    IfStmt,
    IndexExpr,
    IntLiteral,
    LambdaBlock,
    LambdaExpr,
    LambdaExprBody,
    ListLiteral,
    MapLiteral,
    MethodDecl,
    NewExpr,
    NullLiteral,
    ParallelForStmt,
    PreprocessorDirective,
    Program,
    PropertyDecl,
    ReturnStmt,
    SelfExpr,
    SizeofExpr,
    SizeofType,
    StringLiteral,
    StructDecl,
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


def parse(source: str) -> Program:
    tokens = Lexer(source).tokenize()
    return Parser(tokens).parse()


def parse_expr(source: str):
    """Parse a single expression (wraps in a function to get statement context)."""
    prog = parse(f"void __test__() {{ {source}; }}")
    func = prog.declarations[0]
    stmt = func.body.statements[0]
    return stmt.expr


def parse_stmt(source: str):
    """Parse a single statement."""
    prog = parse(f"void __test__() {{ {source} }}")
    func = prog.declarations[0]
    return func.body.statements[0]


# --- Preprocessor ---

class TestPreprocessor:
    def test_parse_preprocessor(self):
        prog = parse('#include <stdio.h>')
        assert len(prog.declarations) == 1
        assert isinstance(prog.declarations[0], PreprocessorDirective)
        assert prog.declarations[0].text == '#include <stdio.h>'

    def test_parse_multiple_preprocessors(self):
        prog = parse('#include <stdio.h>\n#define MAX 100')
        assert len(prog.declarations) == 2
        assert all(isinstance(d, PreprocessorDirective) for d in prog.declarations)


# --- Variable declarations ---

class TestVarDecl:
    def test_parse_var_decl_int(self):
        prog = parse('int x = 5;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.type.base == "int"
        assert d.name == "x"
        assert isinstance(d.initializer, IntLiteral)
        assert d.initializer.value == 5

    def test_parse_var_decl_no_init(self):
        prog = parse('int x;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.name == "x"
        assert d.initializer is None

    def test_parse_var_decl_pointer(self):
        prog = parse('int* p;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.type.base == "int"
        assert d.type.pointer_depth == 1

    def test_parse_var_decl_double_pointer(self):
        prog = parse('char** argv;')
        d = prog.declarations[0]
        assert d.type.base == "char"
        assert d.type.pointer_depth == 2

    def test_parse_var_decl_generic(self):
        prog = parse('Vector<int> nums;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.type.base == "Vector"
        assert len(d.type.generic_args) == 1
        assert d.type.generic_args[0].base == "int"


# --- Functions ---

class TestFunctions:
    def test_parse_function_void(self):
        prog = parse('void foo() { return; }')
        f = prog.declarations[0]
        assert isinstance(f, FunctionDecl)
        assert f.return_type.base == "void"
        assert f.name == "foo"
        assert len(f.params) == 0
        assert len(f.body.statements) == 1
        assert isinstance(f.body.statements[0], ReturnStmt)

    def test_parse_function_params(self):
        prog = parse('int add(int a, int b) { return a + b; }')
        f = prog.declarations[0]
        assert f.name == "add"
        assert len(f.params) == 2
        assert f.params[0].name == "a"
        assert f.params[1].name == "b"
        ret = f.body.statements[0]
        assert isinstance(ret, ReturnStmt)
        assert isinstance(ret.value, BinaryExpr)

    def test_parse_gpu_function(self):
        prog = parse('@gpu void kern(float[] a) { }')
        f = prog.declarations[0]
        assert isinstance(f, FunctionDecl)
        assert f.is_gpu is True
        assert f.params[0].type.is_array is True

    def test_parse_function_pointer_return(self):
        prog = parse('int* create() { return null; }')
        f = prog.declarations[0]
        assert f.return_type.base == "int"
        assert f.return_type.pointer_depth == 1


# --- Classes ---

class TestClasses:
    def test_parse_empty_class(self):
        prog = parse('class Foo { }')
        c = prog.declarations[0]
        assert isinstance(c, ClassDecl)
        assert c.name == "Foo"
        assert len(c.members) == 0
        assert len(c.generic_params) == 0

    def test_parse_class_field(self):
        prog = parse('class Foo { private int x; }')
        c = prog.declarations[0]
        assert len(c.members) == 1
        f = c.members[0]
        assert isinstance(f, FieldDecl)
        assert f.access == "private"
        assert f.type.base == "int"
        assert f.name == "x"

    def test_parse_class_public_field(self):
        prog = parse('class Foo { public float y; }')
        f = prog.declarations[0].members[0]
        assert f.access == "public"

    def test_parse_class_method(self):
        prog = parse('class Foo { public void bar() { } }')
        m = prog.declarations[0].members[0]
        assert isinstance(m, MethodDecl)
        assert m.access == "public"
        assert m.return_type.base == "void"
        assert m.name == "bar"

    def test_parse_class_static_method(self):
        prog = parse('class Foo { class int create() { return 0; } }')
        m = prog.declarations[0].members[0]
        assert isinstance(m, MethodDecl)
        assert m.access == "class"

    def test_parse_class_generic(self):
        prog = parse('class Stack<T> { private T data; }')
        c = prog.declarations[0]
        assert c.generic_params == ["T"]
        f = c.members[0]
        assert f.type.base == "T"

    def test_parse_class_multi_generic(self):
        prog = parse('class Pair<A, B> { public A first; public B second; }')
        c = prog.declarations[0]
        assert c.generic_params == ["A", "B"]

    def test_parse_class_constructor(self):
        prog = parse('class Vec3 { public Vec3(float x) { self.x = x; } }')
        m = prog.declarations[0].members[0]
        assert isinstance(m, MethodDecl)
        assert m.name == "Vec3"

    def test_parse_class_with_initializer(self):
        prog = parse('class Foo { private int x = 0; }')
        f = prog.declarations[0].members[0]
        assert isinstance(f.initializer, IntLiteral)
        assert f.initializer.value == 0

    def test_parse_class_multiple_members(self):
        prog = parse('''
            class Vec3 {
                private float x;
                private float y;
                private float z;
                public void add(Vec3 other) { }
            }
        ''')
        c = prog.declarations[0]
        assert len(c.members) == 4
        assert isinstance(c.members[0], FieldDecl)
        assert isinstance(c.members[3], MethodDecl)


# --- Struct ---

class TestStruct:
    def test_parse_struct(self):
        prog = parse('struct Point { int x; int y; };')
        s = prog.declarations[0]
        assert isinstance(s, StructDecl)
        assert s.name == "Point"
        assert len(s.fields) == 2


# --- Enum ---

class TestEnum:
    def test_parse_enum(self):
        prog = parse('enum Color { RED, GREEN, BLUE };')
        e = prog.declarations[0]
        assert isinstance(e, EnumDecl)
        assert e.name == "Color"
        assert len(e.values) == 3
        assert e.values[0].name == "RED"

    def test_parse_enum_with_values(self):
        prog = parse('enum Flags { A = 1, B = 2 };')
        e = prog.declarations[0]
        assert isinstance(e.values[0].value, IntLiteral)


# --- Statements ---

class TestStatements:
    def test_parse_return(self):
        stmt = parse_stmt('return 42;')
        assert isinstance(stmt, ReturnStmt)
        assert isinstance(stmt.value, IntLiteral)
        assert stmt.value.value == 42

    def test_parse_return_void(self):
        stmt = parse_stmt('return;')
        assert isinstance(stmt, ReturnStmt)
        assert stmt.value is None

    def test_parse_if(self):
        stmt = parse_stmt('if (x > 0) { return x; }')
        assert isinstance(stmt, IfStmt)
        assert isinstance(stmt.condition, BinaryExpr)
        assert stmt.else_block is None

    def test_parse_if_else(self):
        stmt = parse_stmt('if (x) { a; } else { b; }')
        assert isinstance(stmt, IfStmt)
        assert isinstance(stmt.else_block, ElseBlock)

    def test_parse_if_else_if(self):
        stmt = parse_stmt('if (x) { } else if (y) { } else { }')
        assert isinstance(stmt, IfStmt)
        assert isinstance(stmt.else_block, ElseIf)
        assert isinstance(stmt.else_block.if_stmt.else_block, ElseBlock)

    def test_parse_while(self):
        stmt = parse_stmt('while (x > 0) { x--; }')
        assert isinstance(stmt, WhileStmt)
        assert isinstance(stmt.condition, BinaryExpr)

    def test_parse_do_while(self):
        stmt = parse_stmt('do { x++; } while (x < 10);')
        assert isinstance(stmt, DoWhileStmt)

    def test_parse_c_for(self):
        stmt = parse_stmt('for (int i = 0; i < 10; i++) { }')
        assert isinstance(stmt, CForStmt)
        assert isinstance(stmt.init, ForInitVar)
        assert stmt.init.var_decl.name == "i"
        assert isinstance(stmt.condition, BinaryExpr)
        assert isinstance(stmt.update, UnaryExpr)

    def test_parse_for_in(self):
        stmt = parse_stmt('for item in myList { }')
        assert isinstance(stmt, ForInStmt)
        assert stmt.var_name == "item"
        assert isinstance(stmt.iterable, Identifier)
        assert stmt.iterable.name == "myList"

    def test_parse_for_in_map_two_vars(self):
        stmt = parse_stmt('for k, v in myMap { }')
        assert isinstance(stmt, ForInStmt)
        assert stmt.var_name == "k"
        assert stmt.var_name2 == "v"
        assert isinstance(stmt.iterable, Identifier)
        assert stmt.iterable.name == "myMap"

    def test_parse_for_in_map_single_var(self):
        stmt = parse_stmt('for key in myMap { }')
        assert isinstance(stmt, ForInStmt)
        assert stmt.var_name == "key"
        assert stmt.var_name2 in ("", None)
        assert isinstance(stmt.iterable, Identifier)

    def test_parse_parallel_for(self):
        stmt = parse_stmt('parallel for x in data { }')
        assert isinstance(stmt, ParallelForStmt)
        assert stmt.var_name == "x"

    def test_parse_switch(self):
        stmt = parse_stmt('switch (x) { case 1: break; default: break; }')
        assert isinstance(stmt, SwitchStmt)
        assert len(stmt.cases) == 2
        assert stmt.cases[0].value is not None  # case 1
        assert stmt.cases[1].value is None      # default

    def test_parse_break(self):
        stmt = parse_stmt('break;')
        assert isinstance(stmt, BreakStmt)

    def test_parse_continue(self):
        stmt = parse_stmt('continue;')
        assert isinstance(stmt, ContinueStmt)

    def test_parse_delete(self):
        stmt = parse_stmt('delete ptr;')
        assert isinstance(stmt, DeleteStmt)
        assert isinstance(stmt.expr, Identifier)

    def test_parse_var_decl_in_function(self):
        stmt = parse_stmt('int x = 5;')
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.name == "x"

    def test_parse_nested_blocks(self):
        stmt = parse_stmt('{ int x = 1; { int y = 2; } }')
        assert isinstance(stmt, Block)
        assert len(stmt.statements) == 2


# --- Expressions ---

class TestExpressions:
    def test_parse_int_literal(self):
        e = parse_expr('42')
        assert isinstance(e, IntLiteral)
        assert e.value == 42

    def test_parse_hex_literal(self):
        e = parse_expr('0xFF')
        assert isinstance(e, IntLiteral)
        assert e.value == 0xFF

    def test_parse_float_literal(self):
        e = parse_expr('3.14')
        assert isinstance(e, FloatLiteral)
        assert e.value == 3.14

    def test_parse_string_literal(self):
        e = parse_expr('"hello"')
        assert isinstance(e, StringLiteral)

    def test_parse_char_literal(self):
        e = parse_expr("'a'")
        assert isinstance(e, CharLiteral)

    def test_parse_bool_true(self):
        e = parse_expr('true')
        assert isinstance(e, BoolLiteral)
        assert e.value is True

    def test_parse_bool_false(self):
        e = parse_expr('false')
        assert isinstance(e, BoolLiteral)
        assert e.value is False

    def test_parse_null(self):
        e = parse_expr('null')
        assert isinstance(e, NullLiteral)

    def test_parse_self(self):
        e = parse_expr('self')
        assert isinstance(e, SelfExpr)

    def test_parse_identifier(self):
        e = parse_expr('foo')
        assert isinstance(e, Identifier)
        assert e.name == "foo"

    def test_parse_binary_add(self):
        e = parse_expr('a + b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "+"
        assert isinstance(e.left, Identifier)
        assert isinstance(e.right, Identifier)

    def test_parse_precedence_mul_add(self):
        e = parse_expr('a + b * c')
        assert isinstance(e, BinaryExpr)
        assert e.op == "+"
        assert isinstance(e.right, BinaryExpr)
        assert e.right.op == "*"

    def test_parse_precedence_parens(self):
        e = parse_expr('(a + b) * c')
        assert isinstance(e, BinaryExpr)
        assert e.op == "*"
        assert isinstance(e.left, BinaryExpr)
        assert e.left.op == "+"

    def test_parse_unary_neg(self):
        e = parse_expr('-x')
        assert isinstance(e, UnaryExpr)
        assert e.op == "-"
        assert e.prefix is True

    def test_parse_unary_not(self):
        e = parse_expr('!x')
        assert isinstance(e, UnaryExpr)
        assert e.op == "!"
        assert e.prefix is True

    def test_parse_unary_deref(self):
        e = parse_expr('*p')
        assert isinstance(e, UnaryExpr)
        assert e.op == "*"
        assert e.prefix is True

    def test_parse_unary_addr(self):
        e = parse_expr('&x')
        assert isinstance(e, UnaryExpr)
        assert e.op == "&"
        assert e.prefix is True

    def test_parse_prefix_increment(self):
        e = parse_expr('++x')
        assert isinstance(e, UnaryExpr)
        assert e.op == "++"
        assert e.prefix is True

    def test_parse_postfix_increment(self):
        e = parse_expr('x++')
        assert isinstance(e, UnaryExpr)
        assert e.op == "++"
        assert e.prefix is False

    def test_parse_function_call(self):
        e = parse_expr('foo(1, 2)')
        assert isinstance(e, CallExpr)
        assert isinstance(e.callee, Identifier)
        assert e.callee.name == "foo"
        assert len(e.args) == 2

    def test_parse_function_call_no_args(self):
        e = parse_expr('foo()')
        assert isinstance(e, CallExpr)
        assert len(e.args) == 0

    def test_parse_method_call(self):
        e = parse_expr('obj.method(x)')
        assert isinstance(e, CallExpr)
        assert isinstance(e.callee, FieldAccessExpr)
        assert e.callee.field == "method"

    def test_parse_chained_method(self):
        e = parse_expr('a.b().c()')
        assert isinstance(e, CallExpr)
        assert isinstance(e.callee, FieldAccessExpr)
        assert e.callee.field == "c"

    def test_parse_index(self):
        e = parse_expr('arr[0]')
        assert isinstance(e, IndexExpr)
        assert isinstance(e.obj, Identifier)
        assert isinstance(e.index, IntLiteral)

    def test_parse_field_access(self):
        e = parse_expr('obj.x')
        assert isinstance(e, FieldAccessExpr)
        assert e.field == "x"
        assert e.arrow is False

    def test_parse_arrow_access(self):
        e = parse_expr('ptr->x')
        assert isinstance(e, FieldAccessExpr)
        assert e.field == "x"
        assert e.arrow is True

    def test_parse_assignment(self):
        e = parse_expr('x = 5')
        assert isinstance(e, AssignExpr)
        assert e.op == "="
        assert isinstance(e.target, Identifier)
        assert isinstance(e.value, IntLiteral)

    def test_parse_compound_assignment(self):
        e = parse_expr('x += 5')
        assert isinstance(e, AssignExpr)
        assert e.op == "+="

    def test_parse_ternary(self):
        e = parse_expr('x ? a : b')
        assert isinstance(e, TernaryExpr)
        assert isinstance(e.condition, Identifier)

    def test_parse_sizeof(self):
        e = parse_expr('sizeof(int)')
        assert isinstance(e, SizeofExpr)
        assert isinstance(e.operand, SizeofType)

    def test_parse_cast(self):
        e = parse_expr('(float)x')
        assert isinstance(e, CastExpr)
        assert e.target_type.base == "float"

    def test_parse_list_literal(self):
        e = parse_expr('[1, 2, 3]')
        assert isinstance(e, ListLiteral)
        assert len(e.elements) == 3
        assert all(isinstance(el, IntLiteral) for el in e.elements)

    def test_parse_empty_list(self):
        e = parse_expr('[]')
        assert isinstance(e, ListLiteral)
        assert len(e.elements) == 0

    def test_parse_map_literal(self):
        # Map literals appear in expression context (e.g., after =)
        # In statement context, { is always a block
        prog = parse('void test() { Map<string, int> m = {"a": 1, "b": 2}; }')
        stmt = prog.declarations[0].body.statements[0]
        assert isinstance(stmt, VarDeclStmt)
        assert isinstance(stmt.initializer, MapLiteral)
        assert len(stmt.initializer.entries) == 2

    def test_parse_new_expr(self):
        e = parse_expr('new Vec3(1, 2, 3)')
        assert isinstance(e, NewExpr)
        assert e.type.base == "Vec3"
        assert len(e.args) == 3

    def test_parse_logical_and(self):
        e = parse_expr('a && b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "&&"

    def test_parse_logical_or(self):
        e = parse_expr('a || b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "||"

    def test_parse_logical_precedence(self):
        e = parse_expr('a && b || c')
        assert isinstance(e, BinaryExpr)
        assert e.op == "||"
        assert isinstance(e.left, BinaryExpr)
        assert e.left.op == "&&"

    def test_parse_bitwise_and(self):
        e = parse_expr('a & b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "&"

    def test_parse_bitwise_or(self):
        e = parse_expr('a | b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "|"

    def test_parse_bitwise_xor(self):
        e = parse_expr('a ^ b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "^"

    def test_parse_shift_left(self):
        e = parse_expr('a << 2')
        assert isinstance(e, BinaryExpr)
        assert e.op == "<<"

    def test_parse_equality(self):
        e = parse_expr('a == b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "=="

    def test_parse_not_equal(self):
        e = parse_expr('a != b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "!="

    def test_parse_relational(self):
        e = parse_expr('a < b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "<"

    def test_parse_complex_expr(self):
        e = parse_expr('a + b * c - d')
        assert isinstance(e, BinaryExpr)
        assert e.op == "-"

    def test_parse_self_field(self):
        e = parse_expr('self.x')
        assert isinstance(e, FieldAccessExpr)
        assert isinstance(e.obj, SelfExpr)
        assert e.field == "x"


# --- Full programs ---

class TestFullPrograms:
    def test_parse_hello_world(self):
        prog = parse('''
            #include <stdio.h>
            int main() {
                printf("hello\\n");
                return 0;
            }
        ''')
        assert len(prog.declarations) == 2
        assert isinstance(prog.declarations[0], PreprocessorDirective)
        assert isinstance(prog.declarations[1], FunctionDecl)
        assert prog.declarations[1].name == "main"

    def test_parse_class_with_methods(self):
        prog = parse('''
            class Counter {
                private int count;
                public Counter() {
                    self.count = 0;
                }
                public void inc() {
                    self.count++;
                }
                public int get() {
                    return self.count;
                }
            }
        ''')
        c = prog.declarations[0]
        assert isinstance(c, ClassDecl)
        assert c.name == "Counter"
        assert len(c.members) == 4  # 1 field + 3 methods

    def test_parse_generic_usage(self):
        prog = parse('''
            void test() {
                Vector<int> nums = [1, 2, 3];
                for item in nums {
                    printf("%d\\n", item);
                }
            }
        ''')
        f = prog.declarations[0]
        stmts = f.body.statements
        assert isinstance(stmts[0], VarDeclStmt)
        assert stmts[0].type.base == "Vector"
        assert isinstance(stmts[1], ForInStmt)

    def test_parse_mixed_c_and_btrc(self):
        prog = parse('''
            #include <stdio.h>
            struct Point { int x; int y; };
            class Vec3 {
                public float x;
                public float y;
                public float z;
            }
            int main() {
                Vec3 v;
                return 0;
            }
        ''')
        assert isinstance(prog.declarations[0], PreprocessorDirective)
        assert isinstance(prog.declarations[1], StructDecl)
        assert isinstance(prog.declarations[2], ClassDecl)
        assert isinstance(prog.declarations[3], FunctionDecl)


# --- F-string parsing ---

class TestFStringParsing:
    def test_parse_fstring_text_only(self):
        expr = parse_expr('f"hello world"')
        assert isinstance(expr, FStringLiteral)
        assert len(expr.parts) == 1
        assert isinstance(expr.parts[0], FStringText)
        assert expr.parts[0].text == "hello world"

    def test_parse_fstring_single_expr(self):
        expr = parse_expr('f"x={x}"')
        assert isinstance(expr, FStringLiteral)
        assert len(expr.parts) == 2
        assert isinstance(expr.parts[0], FStringText)
        assert expr.parts[0].text == "x="
        assert isinstance(expr.parts[1], FStringExpr)
        assert isinstance(expr.parts[1].expression, Identifier)
        assert expr.parts[1].expression.name == "x"

    def test_parse_fstring_multi_expr(self):
        expr = parse_expr('f"{a} + {b} = {c}"')
        assert isinstance(expr, FStringLiteral)
        assert len(expr.parts) == 5
        assert isinstance(expr.parts[0], FStringExpr)
        assert isinstance(expr.parts[1], FStringText)
        assert expr.parts[1].text == " + "
        assert isinstance(expr.parts[2], FStringExpr)
        assert isinstance(expr.parts[3], FStringText)
        assert expr.parts[3].text == " = "
        assert isinstance(expr.parts[4], FStringExpr)


# --- Var type inference ---

class TestVarInference:
    def test_parse_var_int(self):
        stmt = parse_stmt('var x = 42;')
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.type is None
        assert stmt.name == "x"
        assert isinstance(stmt.initializer, IntLiteral)
        assert stmt.initializer.value == 42

    def test_parse_var_string(self):
        stmt = parse_stmt('var s = "hello";')
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.type is None
        assert stmt.name == "s"
        assert isinstance(stmt.initializer, StringLiteral)

    def test_parse_var_bool(self):
        stmt = parse_stmt('var b = true;')
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.type is None
        assert isinstance(stmt.initializer, BoolLiteral)

    def test_parse_var_expr(self):
        stmt = parse_stmt('var y = a + b;')
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.type is None
        assert isinstance(stmt.initializer, BinaryExpr)

    def test_parse_var_in_for_init(self):
        stmt = parse_stmt('for (var i = 0; i < 10; i++) { }')
        assert isinstance(stmt, CForStmt)
        assert isinstance(stmt.init, ForInitVar)
        assert stmt.init.var_decl.type is None
        assert stmt.init.var_decl.name == "i"

    def test_parse_var_top_level(self):
        prog = parse('var x = 42;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.type is None
        assert d.name == "x"


# --- Nullable types ---

class TestNullableTypes:
    def test_parse_nullable_type(self):
        prog = parse('int? x;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.type.base == "int"
        assert d.type.pointer_depth == 1  # T? adds one pointer level

    def test_parse_nullable_float_type(self):
        prog = parse('float? f;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.type.base == "float"
        assert d.type.pointer_depth == 1

    def test_parse_nullable_string_type(self):
        prog = parse('string? s;')
        d = prog.declarations[0]
        assert d.type.base == "string"
        assert d.type.pointer_depth == 1

    def test_parse_nullable_param(self):
        prog = parse('void process(int? ptr) { }')
        f = prog.declarations[0]
        assert f.params[0].type.base == "int"
        assert f.params[0].type.pointer_depth == 1


# --- Try/catch/throw ---

class TestTryCatch:
    def test_parse_try_catch(self):
        stmt = parse_stmt('try { int x = 1; } catch (string e) { int y = 2; }')
        assert isinstance(stmt, TryCatchStmt)
        assert isinstance(stmt.try_block, Block)
        assert stmt.catch_var == "e"
        assert isinstance(stmt.catch_block, Block)

    def test_parse_try_catch_short_form(self):
        stmt = parse_stmt('try { foo(); } catch (e) { bar(); }')
        assert isinstance(stmt, TryCatchStmt)
        assert stmt.catch_var == "e"

    def test_parse_throw(self):
        stmt = parse_stmt('throw "error message";')
        assert isinstance(stmt, ThrowStmt)
        assert isinstance(stmt.expr, StringLiteral)

    def test_parse_throw_fstring(self):
        stmt = parse_stmt('throw f"error: {msg}";')
        assert isinstance(stmt, ThrowStmt)
        assert isinstance(stmt.expr, FStringLiteral)


# --- For-in with range ---

class TestForInRange:
    def test_parse_for_in_range_single(self):
        stmt = parse_stmt('for i in range(10) { }')
        assert isinstance(stmt, ForInStmt)
        assert stmt.var_name == "i"
        assert isinstance(stmt.iterable, CallExpr)
        assert stmt.iterable.callee.name == "range"
        assert len(stmt.iterable.args) == 1

    def test_parse_for_in_range_double(self):
        stmt = parse_stmt('for i in range(0, 10) { }')
        assert isinstance(stmt, ForInStmt)
        assert isinstance(stmt.iterable, CallExpr)
        assert len(stmt.iterable.args) == 2

    def test_parse_for_in_range_triple(self):
        stmt = parse_stmt('for i in range(0, 100, 5) { }')
        assert isinstance(stmt, ForInStmt)
        assert isinstance(stmt.iterable, CallExpr)
        assert len(stmt.iterable.args) == 3


# --- Default parameters ---

class TestDefaultParams:
    def test_parse_default_param_int(self):
        prog = parse('int add(int a, int b = 0) { return a + b; }')
        f = prog.declarations[0]
        assert f.params[0].default is None
        assert isinstance(f.params[1].default, IntLiteral)
        assert f.params[1].default.value == 0

    def test_parse_default_param_string(self):
        prog = parse('void greet(string name = "world") { }')
        f = prog.declarations[0]
        assert isinstance(f.params[0].default, StringLiteral)

    def test_parse_default_param_bool(self):
        prog = parse('void toggle(bool flag = true) { }')
        f = prog.declarations[0]
        assert isinstance(f.params[0].default, BoolLiteral)
        assert f.params[0].default.value is True

    def test_parse_default_param_null(self):
        prog = parse('void process(int* ptr = null) { }')
        f = prog.declarations[0]
        assert isinstance(f.params[0].default, NullLiteral)


# --- Inheritance ---

class TestInheritance:
    def test_parse_class_extends(self):
        prog = parse('class Dog extends Animal { public void bark() { } }')
        c = prog.declarations[0]
        assert isinstance(c, ClassDecl)
        assert c.name == "Dog"
        assert c.parent == "Animal"

    def test_parse_inheritance_no_parent(self):
        prog = parse('class Foo { }')
        c = prog.declarations[0]
        assert c.parent is None

    def test_parse_inheritance_with_members(self):
        prog = parse('''
            class Shape {
                private string name;
                public Shape(string n) { self.name = n; }
                public string getName() { return self.name; }
            }
            class Circle extends Shape {
                private float radius;
                public Circle(float r) { self.radius = r; }
            }
        ''')
        shape = prog.declarations[0]
        circle = prog.declarations[1]
        assert shape.parent is None
        assert circle.parent == "Shape"
        assert circle.name == "Circle"


# --- Typedef ---

class TestTypedef:
    def test_parse_typedef(self):
        prog = parse('typedef int Number;')
        t = prog.declarations[0]
        assert isinstance(t, TypedefDecl)
        assert t.original.base == "int"
        assert t.alias == "Number"

    def test_parse_typedef_pointer(self):
        prog = parse('typedef char* CString;')
        t = prog.declarations[0]
        assert isinstance(t, TypedefDecl)
        assert t.original.base == "char"
        assert t.original.pointer_depth == 1
        assert t.alias == "CString"


# --- Tuple types and literals ---

class TestTuples:
    def test_parse_tuple_literal(self):
        e = parse_expr('(1, 2)')
        assert isinstance(e, TupleLiteral)
        assert len(e.elements) == 2
        assert isinstance(e.elements[0], IntLiteral)
        assert isinstance(e.elements[1], IntLiteral)

    def test_parse_triple_tuple(self):
        e = parse_expr('(1, 2, 3)')
        assert isinstance(e, TupleLiteral)
        assert len(e.elements) == 3

    def test_parse_tuple_type(self):
        prog = parse('void test() { (int, int) t; }')
        stmt = prog.declarations[0].body.statements[0]
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.type.base == "Tuple"
        assert len(stmt.type.generic_args) == 2
        assert stmt.type.generic_args[0].base == "int"
        assert stmt.type.generic_args[1].base == "int"


# --- Optional chaining and null coalescing ---

class TestOptionalChaining:
    def test_parse_optional_chaining(self):
        e = parse_expr('obj?.field')
        assert isinstance(e, FieldAccessExpr)
        assert e.field == "field"
        assert e.optional is True
        assert e.arrow is True

    def test_parse_null_coalescing(self):
        e = parse_expr('a ?? b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "??"

    def test_parse_null_coalescing_chain(self):
        e = parse_expr('a ?? b ?? c')
        assert isinstance(e, BinaryExpr)
        assert e.op == "??"
        assert isinstance(e.left, BinaryExpr)
        assert e.left.op == "??"


# --- Additional expression coverage ---

class TestAdditionalExpressions:
    def test_parse_postfix_decrement(self):
        e = parse_expr('x--')
        assert isinstance(e, UnaryExpr)
        assert e.op == "--"
        assert e.prefix is False

    def test_parse_prefix_decrement(self):
        e = parse_expr('--x')
        assert isinstance(e, UnaryExpr)
        assert e.op == "--"
        assert e.prefix is True

    def test_parse_bitwise_not(self):
        e = parse_expr('~x')
        assert isinstance(e, UnaryExpr)
        assert e.op == "~"
        assert e.prefix is True

    def test_parse_modulo(self):
        e = parse_expr('a % b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "%"

    def test_parse_division(self):
        e = parse_expr('a / b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "/"

    def test_parse_shift_right(self):
        e = parse_expr('a >> 2')
        assert isinstance(e, BinaryExpr)
        assert e.op == ">>"

    def test_parse_compound_minus_eq(self):
        e = parse_expr('x -= 3')
        assert isinstance(e, AssignExpr)
        assert e.op == "-="

    def test_parse_compound_star_eq(self):
        e = parse_expr('x *= 2')
        assert isinstance(e, AssignExpr)
        assert e.op == "*="

    def test_parse_compound_slash_eq(self):
        e = parse_expr('x /= 4')
        assert isinstance(e, AssignExpr)
        assert e.op == "/="

    def test_parse_compound_percent_eq(self):
        e = parse_expr('x %= 5')
        assert isinstance(e, AssignExpr)
        assert e.op == "%="

    def test_parse_compound_amp_eq(self):
        e = parse_expr('x &= 0xFF')
        assert isinstance(e, AssignExpr)
        assert e.op == "&="

    def test_parse_compound_pipe_eq(self):
        e = parse_expr('x |= 1')
        assert isinstance(e, AssignExpr)
        assert e.op == "|="

    def test_parse_compound_caret_eq(self):
        e = parse_expr('x ^= 3')
        assert isinstance(e, AssignExpr)
        assert e.op == "^="

    def test_parse_relational_le(self):
        e = parse_expr('a <= b')
        assert isinstance(e, BinaryExpr)
        assert e.op == "<="

    def test_parse_relational_ge(self):
        e = parse_expr('a >= b')
        assert isinstance(e, BinaryExpr)
        assert e.op == ">="

    def test_parse_relational_gt(self):
        e = parse_expr('a > b')
        assert isinstance(e, BinaryExpr)
        assert e.op == ">"


# --- Brace initializer ---

class TestBraceInitializer:
    def test_parse_brace_initializer(self):
        prog = parse('void test() { int arr[] = {1, 2, 3}; }')
        stmt = prog.declarations[0].body.statements[0]
        assert isinstance(stmt, VarDeclStmt)
        assert isinstance(stmt.initializer, BraceInitializer)
        assert len(stmt.initializer.elements) == 3


# --- Switch with multiple cases and fallthrough ---

class TestSwitchAdvanced:
    def test_parse_switch_multiple_cases(self):
        stmt = parse_stmt('''switch (x) {
            case 1: a; break;
            case 2: b; break;
            case 3: c; break;
            default: d; break;
        }''')
        assert isinstance(stmt, SwitchStmt)
        assert len(stmt.cases) == 4
        assert stmt.cases[0].value is not None
        assert stmt.cases[1].value is not None
        assert stmt.cases[2].value is not None
        assert stmt.cases[3].value is None  # default

    def test_parse_switch_case_body(self):
        stmt = parse_stmt('switch (x) { case 0: return 1; }')
        assert isinstance(stmt, SwitchStmt)
        case = stmt.cases[0]
        assert isinstance(case.value, IntLiteral)
        assert case.value.value == 0
        assert isinstance(case.body[0], ReturnStmt)


# --- Nested generic types ---

class TestNestedGenerics:
    def test_parse_nested_list(self):
        prog = parse('void test() { Vector<Vector<int>> nested; }')
        stmt = prog.declarations[0].body.statements[0]
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.type.base == "Vector"
        inner = stmt.type.generic_args[0]
        assert inner.base == "Vector"
        assert inner.generic_args[0].base == "int"

    def test_parse_map_with_generic_value(self):
        prog = parse('void test() { Map<string, Vector<int>> m; }')
        stmt = prog.declarations[0].body.statements[0]
        assert stmt.type.base == "Map"
        assert stmt.type.generic_args[0].base == "string"
        assert stmt.type.generic_args[1].base == "Vector"
        assert stmt.type.generic_args[1].generic_args[0].base == "int"


# --- Trailing comma support ---

class TestTrailingComma:
    def test_parse_list_trailing_comma(self):
        e = parse_expr('[1, 2, 3,]')
        assert isinstance(e, ListLiteral)
        assert len(e.elements) == 3

    def test_parse_map_trailing_comma(self):
        prog = parse('void test() { Map<string, int> m = {"a": 1, "b": 2,}; }')
        stmt = prog.declarations[0].body.statements[0]
        assert isinstance(stmt.initializer, MapLiteral)
        assert len(stmt.initializer.entries) == 2


# --- C type qualifiers ---

class TestTypeQualifiers:
    def test_parse_const_type(self):
        prog = parse('void test() { const int x = 5; }')
        stmt = prog.declarations[0].body.statements[0]
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.name == "x"

    def test_parse_unsigned_int(self):
        prog = parse('unsigned int x;')
        d = prog.declarations[0]
        assert d.type.base == "unsigned int"

    def test_parse_long_long(self):
        prog = parse('long long x;')
        d = prog.declarations[0]
        assert d.type.base == "long long"

    def test_parse_unsigned_char(self):
        prog = parse('unsigned char c;')
        d = prog.declarations[0]
        assert d.type.base == "unsigned char"


# --- Struct forward declaration ---

class TestStructForwardDecl:
    def test_parse_struct_forward_decl(self):
        prog = parse('struct Node;')
        s = prog.declarations[0]
        assert isinstance(s, StructDecl)
        assert s.name == "Node"
        assert len(s.fields) == 0


# --- Empty map literal (brace init) ---

class TestEmptyBraceInit:
    def test_parse_empty_brace_initializer(self):
        prog = parse('void test() { Map<string, int> m = {}; }')
        stmt = prog.declarations[0].body.statements[0]
        assert isinstance(stmt, VarDeclStmt)
        assert isinstance(stmt.initializer, BraceInitializer)
        assert len(stmt.initializer.elements) == 0


# --- New expression with no args ---

class TestNewExprVariants:
    def test_parse_new_no_args(self):
        e = parse_expr('new Node()')
        assert isinstance(e, NewExpr)
        assert e.type.base == "Node"
        assert len(e.args) == 0

    def test_parse_new_generic_type(self):
        e = parse_expr('new Vector<int>()')
        assert isinstance(e, NewExpr)
        assert e.type.base == "Vector"
        assert len(e.type.generic_args) == 1


# --- C-style array declarations ---

class TestArrayDecl:
    def test_parse_c_array_fixed_size(self):
        prog = parse('void test() { int arr[10]; }')
        stmt = prog.declarations[0].body.statements[0]
        assert isinstance(stmt, VarDeclStmt)
        assert stmt.type.is_array is True
        assert isinstance(stmt.type.array_size, IntLiteral)
        assert stmt.type.array_size.value == 10

    def test_parse_c_array_empty_brackets(self):
        prog = parse('void test() { int arr[] = {1, 2, 3}; }')
        stmt = prog.declarations[0].body.statements[0]
        assert stmt.type.is_array is True

    def test_parse_array_param(self):
        prog = parse('void sort(int arr[], int n) { }')
        f = prog.declarations[0]
        assert f.params[0].type.is_array is True
        assert f.params[0].name == "arr"


# --- F-string with expression ---

class TestFStringAdvanced:
    def test_parse_fstring_with_method_call(self):
        expr = parse_expr('f"len={s.len()}"')
        assert isinstance(expr, FStringLiteral)
        assert len(expr.parts) == 2
        assert isinstance(expr.parts[0], FStringText)
        assert expr.parts[0].text == "len="
        assert isinstance(expr.parts[1], FStringExpr)
        assert isinstance(expr.parts[1].expression, CallExpr)

    def test_parse_fstring_with_binary_expr(self):
        expr = parse_expr('f"sum={a + b}"')
        assert isinstance(expr, FStringLiteral)
        assert isinstance(expr.parts[1], FStringExpr)
        assert isinstance(expr.parts[1].expression, BinaryExpr)


# --- Do-while details ---

class TestDoWhileDetails:
    def test_parse_do_while_full(self):
        stmt = parse_stmt('do { x = x + 1; } while (x < 100);')
        assert isinstance(stmt, DoWhileStmt)
        assert isinstance(stmt.condition, BinaryExpr)
        assert stmt.condition.op == "<"
        assert isinstance(stmt.body, Block)
        assert len(stmt.body.statements) == 1


# --- Lambdas ---

class TestLambda:
    def test_verbose_lambda(self):
        expr = parse_expr('int function(int x) { return x * 2; }')
        assert isinstance(expr, LambdaExpr)
        assert expr.return_type.base == "int"
        assert len(expr.params) == 1
        assert expr.params[0].name == "x"
        assert isinstance(expr.body, LambdaBlock)

    def test_arrow_lambda_expr_body(self):
        expr = parse_expr('(int x) => x * 3')
        assert isinstance(expr, LambdaExpr)
        assert len(expr.params) == 1
        assert expr.params[0].name == "x"
        assert isinstance(expr.body, LambdaExprBody)

    def test_arrow_lambda_block_body(self):
        expr = parse_expr('(int x) => { return x; }')
        assert isinstance(expr, LambdaExpr)
        assert len(expr.params) == 1
        assert isinstance(expr.body, LambdaBlock)

    def test_arrow_lambda_multiple_params(self):
        expr = parse_expr('(int a, int b) => a + b')
        assert isinstance(expr, LambdaExpr)
        assert len(expr.params) == 2
        assert expr.params[0].name == "a"
        assert expr.params[1].name == "b"

    def test_verbose_lambda_no_params(self):
        expr = parse_expr('int function() { return 42; }')
        assert isinstance(expr, LambdaExpr)
        assert len(expr.params) == 0
        assert expr.return_type.base == "int"


# --- Properties ---

class TestProperties:
    def test_auto_property(self):
        prog = parse('class Foo { public int x { get; set; } }')
        cls = prog.declarations[0]
        prop = cls.members[0]
        assert isinstance(prop, PropertyDecl)
        assert prop.name == "x"
        assert prop.type.base == "int"
        assert prop.has_getter is True
        assert prop.has_setter is True
        assert prop.getter_body is None  # auto
        assert prop.setter_body is None  # auto

    def test_readonly_property(self):
        prog = parse('class Foo { public int x { get; } }')
        prop = prog.declarations[0].members[0]
        assert isinstance(prop, PropertyDecl)
        assert prop.has_getter is True
        assert prop.has_setter is False

    def test_custom_getter(self):
        prog = parse('class Foo { public int x { get { return 42; } } }')
        prop = prog.declarations[0].members[0]
        assert isinstance(prop, PropertyDecl)
        assert prop.has_getter is True
        assert prop.getter_body is not None
        assert len(prop.getter_body.statements) == 1

    def test_custom_getter_and_setter(self):
        prog = parse('''class Foo {
            private int _x;
            public int x {
                get { return self._x; }
                set { self._x = value; }
            }
        }''')
        cls = prog.declarations[0]
        assert isinstance(cls.members[0], FieldDecl)
        prop = cls.members[1]
        assert isinstance(prop, PropertyDecl)
        assert prop.has_getter is True
        assert prop.has_setter is True
        assert prop.getter_body is not None
        assert prop.setter_body is not None


# --- Forward declarations ---

class TestForwardDeclarations:
    def test_forward_decl_basic(self):
        prog = parse('int add(int a, int b);')
        d = prog.declarations[0]
        assert isinstance(d, FunctionDecl)
        assert d.name == 'add'
        assert d.body is None
        assert d.return_type.base == 'int'
        assert len(d.params) == 2

    def test_forward_decl_no_params(self):
        prog = parse('void foo();')
        d = prog.declarations[0]
        assert isinstance(d, FunctionDecl)
        assert d.name == 'foo'
        assert d.body is None
        assert d.return_type.base == 'void'
        assert len(d.params) == 0

    def test_forward_decl_bool_return(self):
        prog = parse('bool is_even(int n);')
        d = prog.declarations[0]
        assert isinstance(d, FunctionDecl)
        assert d.body is None
        assert d.return_type.base == 'bool'

    def test_forward_decl_followed_by_definition(self):
        src = '''
            bool is_even(int n);
            bool is_even(int n) { return true; }
        '''
        prog = parse(src)
        assert len(prog.declarations) == 2
        assert prog.declarations[0].body is None
        assert prog.declarations[1].body is not None

    def test_forward_decl_pointer_return(self):
        prog = parse('int* get_ptr();')
        d = prog.declarations[0]
        assert isinstance(d, FunctionDecl)
        assert d.body is None
        assert d.return_type.base == 'int'
        assert d.return_type.pointer_depth == 1

    def test_forward_decl_multiple(self):
        src = '''
            int foo(int x);
            int bar(int y);
            int foo(int x) { return bar(x); }
            int bar(int y) { return y * 2; }
        '''
        prog = parse(src)
        assert len(prog.declarations) == 4
        assert prog.declarations[0].body is None
        assert prog.declarations[1].body is None
        assert prog.declarations[2].body is not None
        assert prog.declarations[3].body is not None


# --- Parse error ---

class TestParseErrors:
    def test_parse_error_missing_semicolon(self):
        with pytest.raises(ParseError):
            parse('int x = 5')

    def test_parse_error_unexpected_token(self):
        with pytest.raises(ParseError):
            parse('??? unexpected')

    def test_parse_error_missing_rparen(self):
        with pytest.raises(ParseError):
            parse('void foo( { }')

    def test_unmatched_lbrace(self):
        with pytest.raises(ParseError):
            parse('void foo() {')

    def test_missing_class_body(self):
        with pytest.raises(ParseError):
            parse('class Foo')

    def test_missing_function_name(self):
        with pytest.raises(ParseError):
            parse('void (int x) { }')

    def test_missing_if_condition_paren(self):
        with pytest.raises(ParseError):
            parse('void f() { if true { } }')

    def test_missing_while_condition(self):
        with pytest.raises(ParseError):
            parse('void f() { while { } }')

    def test_empty_param_list_with_comma(self):
        with pytest.raises(ParseError):
            parse('void foo(,) { }')

    def test_missing_catch_after_try(self):
        with pytest.raises(ParseError):
            parse('void f() { try { } }')

    def test_missing_switch_brace(self):
        with pytest.raises(ParseError):
            parse('void f() { switch (x) case 1: break; }')

    def test_invalid_member_access(self):
        with pytest.raises(ParseError):
            parse('void f() { x.; }')

    def test_unterminated_string(self):
        from src.compiler.python.lexer import LexerError
        with pytest.raises((ParseError, LexerError)):
            parse('string s = "hello;')

    def test_missing_return_type(self):
        with pytest.raises(ParseError):
            parse('foo() { }')

    def test_unclosed_paren_in_expr(self):
        with pytest.raises(ParseError):
            parse('void f() { int x = (1 + 2; }')
