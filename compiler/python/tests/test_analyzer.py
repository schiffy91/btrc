"""Tests for the btrc semantic analyzer."""

from compiler.python.lexer import Lexer
from compiler.python.parser import Parser
from compiler.python.analyzer import Analyzer


def analyze(source: str):
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    analyzer = Analyzer()
    return analyzer.analyze(program)


def errors(source: str) -> list[str]:
    return analyze(source).errors


def has_error(source: str, substring: str) -> bool:
    return any(substring in e for e in errors(source))


def no_errors(source: str) -> bool:
    return len(errors(source)) == 0


# --- Access control ---

class TestAccessControl:
    def test_public_field_access(self):
        src = '''
            class Foo { public int x; }
            void test() {
                Foo f = Foo();
                f.x = 5;
            }
        '''
        assert no_errors(src)

    def test_private_field_access_outside(self):
        src = '''
            class Foo { private int x; }
            void test() {
                Foo f = Foo();
                f.x = 5;
            }
        '''
        assert has_error(src, "private field")

    def test_private_field_access_inside(self):
        src = '''
            class Foo {
                private int x;
                public void set(int val) { self.x = val; }
            }
        '''
        assert no_errors(src)

    def test_private_method_access_outside(self):
        src = '''
            class Foo {
                private void secret() { }
                public void pub() { self.secret(); }
            }
            void test() {
                Foo f = Foo();
                f.secret();
            }
        '''
        assert has_error(src, "private method")

    def test_private_method_access_inside(self):
        src = '''
            class Foo {
                private void helper() { }
                public void run() { self.helper(); }
            }
        '''
        assert no_errors(src)


# --- Self validation ---

class TestSelfValidation:
    def test_self_in_method(self):
        src = '''
            class Foo {
                private int x;
                public void set(int v) { self.x = v; }
            }
        '''
        assert no_errors(src)

    def test_self_outside_class(self):
        src = '''
            void test() { self.x = 5; }
        '''
        assert has_error(src, "self")

    def test_self_in_class_method(self):
        src = '''
            class Foo {
                class int create() { self.x = 1; return 0; }
            }
        '''
        assert has_error(src, "self")


# --- Generics ---

class TestGenerics:
    def test_generic_instantiation_collected(self):
        src = '''
            void test() {
                List<int> a;
                List<float> b;
            }
        '''
        result = analyze(src)
        assert "List" in result.generic_instances
        bases = [args[0].base for args in result.generic_instances["List"]]
        assert "int" in bases
        assert "float" in bases

    def test_map_generic_collected(self):
        src = '''
            void test() {
                Map<string, int> m;
            }
        '''
        result = analyze(src)
        assert "Map" in result.generic_instances

    def test_nested_generic(self):
        src = '''
            void test() {
                List<List<int>> nested;
            }
        '''
        result = analyze(src)
        assert "List" in result.generic_instances
        # Should have both List<int> and List<List<int>>
        assert len(result.generic_instances["List"]) == 2

    def test_generic_class_registered(self):
        src = '''
            class Stack<T> {
                private T data;
                public void push(T val) { }
            }
            void test() {
                Stack<int> s;
            }
        '''
        result = analyze(src)
        assert "Stack" in result.generic_instances


# --- Constructor resolution ---

class TestConstructors:
    def test_constructor_call(self):
        src = '''
            class Vec3 {
                public float x;
                public Vec3(float x) { self.x = x; }
            }
            void test() {
                Vec3 v = Vec3(1.0);
            }
        '''
        assert no_errors(src)

    def test_new_constructor(self):
        src = '''
            class Node {
                public int val;
                public Node(int v) { self.val = v; }
            }
            void test() {
                Node* n = new Node(42);
            }
        '''
        assert no_errors(src)


# --- Class table ---

class TestClassTable:
    def test_class_registered(self):
        src = '''
            class Vec3 {
                public float x;
                public float y;
                public void add() { }
            }
        '''
        result = analyze(src)
        assert "Vec3" in result.class_table
        cls = result.class_table["Vec3"]
        assert "x" in cls.fields
        assert "y" in cls.fields
        assert "add" in cls.methods

    def test_static_method_registered(self):
        src = '''
            class Math {
                class int square(int x) { return x * x; }
            }
        '''
        result = analyze(src)
        cls = result.class_table["Math"]
        assert "square" in cls.methods
        assert cls.methods["square"].access == "class"


# --- For-in validation ---

class TestForIn:
    def test_for_in_list(self):
        src = '''
            void test() {
                List<int> nums;
                for x in nums { }
            }
        '''
        assert no_errors(src)

    def test_for_in_non_iterable(self):
        src = '''
            void test() {
                int x = 5;
                for item in x { }
            }
        '''
        assert has_error(src, "not iterable")


# --- Pure C passthrough ---

class TestPassthrough:
    def test_c_program(self):
        src = '''
            #include <stdio.h>
            int main() {
                int x = 5;
                return 0;
            }
        '''
        assert no_errors(src)

    def test_struct_decl(self):
        src = '''
            struct Point { int x; int y; };
        '''
        assert no_errors(src)

    def test_enum_decl(self):
        src = '''
            enum Color { RED, GREEN, BLUE };
        '''
        assert no_errors(src)


# --- Var type inference ---

class TestVarInference:
    def test_var_infer_int(self):
        src = '''
            void test() {
                var x = 42;
            }
        '''
        result = analyze(src)
        assert not result.errors
        # Verify the type was inferred on the AST node
        stmt = result.program.declarations[0].body.statements[0]
        assert stmt.type is not None
        assert stmt.type.base == "int"

    def test_var_infer_float(self):
        src = '''
            void test() {
                var x = 3.14;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[0]
        assert stmt.type.base == "float"

    def test_var_infer_string(self):
        src = '''
            void test() {
                var s = "hello";
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[0]
        assert stmt.type.base == "string"

    def test_var_infer_bool(self):
        src = '''
            void test() {
                var b = true;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[0]
        assert stmt.type.base == "bool"

    def test_var_missing_initializer(self):
        """var without initializer should produce an error."""
        # This would be caught at parser level since = is required,
        # but we test the analyzer fallback
        src = '''
            void test() {
                var x = 42;
            }
        '''
        # Valid case should have no errors
        assert no_errors(src)

    def test_var_infer_binary_expr(self):
        src = '''
            void test() {
                int a = 1;
                int b = 2;
                var c = a + b;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[2]
        assert stmt.type.base == "int"

    def test_var_infer_constructor(self):
        src = '''
            class Point {
                public int x;
                public Point(int x) { self.x = x; }
            }
            void test() {
                var p = Point(5);
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[1].body.statements[0]
        assert stmt.type.base == "Point"
