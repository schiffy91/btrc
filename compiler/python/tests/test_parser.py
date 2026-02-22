"""Tests for the btrc parser."""

import pytest
from compiler.python.lexer import Lexer
from compiler.python.parser import Parser, ParseError
from compiler.python.ast_nodes import *


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
        prog = parse('List<int> nums;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.type.base == "List"
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
        assert e.values[0][0] == "RED"

    def test_parse_enum_with_values(self):
        prog = parse('enum Flags { A = 1, B = 2 };')
        e = prog.declarations[0]
        assert isinstance(e.values[0][1], IntLiteral)


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
        assert isinstance(stmt.else_block, Block)

    def test_parse_if_else_if(self):
        stmt = parse_stmt('if (x) { } else if (y) { } else { }')
        assert isinstance(stmt, IfStmt)
        assert isinstance(stmt.else_block, IfStmt)
        assert isinstance(stmt.else_block.else_block, Block)

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
        assert isinstance(stmt.init, VarDeclStmt)
        assert stmt.init.name == "i"
        assert isinstance(stmt.condition, BinaryExpr)
        assert isinstance(stmt.update, UnaryExpr)

    def test_parse_for_in(self):
        stmt = parse_stmt('for item in myList { }')
        assert isinstance(stmt, ForInStmt)
        assert stmt.var_name == "item"
        assert isinstance(stmt.iterable, Identifier)
        assert stmt.iterable.name == "myList"

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
        assert isinstance(e.operand, TypeExpr)

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
                List<int> nums = [1, 2, 3];
                for item in nums {
                    printf("%d\\n", item);
                }
            }
        ''')
        f = prog.declarations[0]
        stmts = f.body.statements
        assert isinstance(stmts[0], VarDeclStmt)
        assert stmts[0].type.base == "List"
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
        assert expr.parts[0] == ("text", "hello world")

    def test_parse_fstring_single_expr(self):
        expr = parse_expr('f"x={x}"')
        assert isinstance(expr, FStringLiteral)
        assert len(expr.parts) == 2
        assert expr.parts[0] == ("text", "x=")
        assert expr.parts[1][0] == "expr"
        assert isinstance(expr.parts[1][1], Identifier)
        assert expr.parts[1][1].name == "x"

    def test_parse_fstring_multi_expr(self):
        expr = parse_expr('f"{a} + {b} = {c}"')
        assert isinstance(expr, FStringLiteral)
        assert len(expr.parts) == 5
        assert expr.parts[0][0] == "expr"
        assert expr.parts[1] == ("text", " + ")
        assert expr.parts[2][0] == "expr"
        assert expr.parts[3] == ("text", " = ")
        assert expr.parts[4][0] == "expr"


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
        assert isinstance(stmt.init, VarDeclStmt)
        assert stmt.init.type is None
        assert stmt.init.name == "i"

    def test_parse_var_top_level(self):
        prog = parse('var x = 42;')
        d = prog.declarations[0]
        assert isinstance(d, VarDeclStmt)
        assert d.type is None
        assert d.name == "x"
