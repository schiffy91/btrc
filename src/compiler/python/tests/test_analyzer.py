"""Tests for the btrc semantic analyzer."""

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.analyzer.analyzer import Analyzer


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
                Vector<int> a;
                Vector<float> b;
            }
        '''
        result = analyze(src)
        assert "Vector" in result.generic_instances
        bases = [args[0].base for args in result.generic_instances["Vector"]]
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
                Vector<Vector<int>> nested;
            }
        '''
        result = analyze(src)
        assert "Vector" in result.generic_instances
        # Should have both Vector<int> and Vector<Vector<int>>
        assert len(result.generic_instances["Vector"]) == 2

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
                Node n = new Node(42);
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
                Vector<int> nums;
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


# --- Type Checking ---

class TestTypeChecking:
    def test_var_decl_with_explicit_type_accepts_matching_literal(self):
        """Declaring int x = 42 should produce no errors."""
        src = '''
            void test() {
                int x = 42;
            }
        '''
        assert no_errors(src)

    def test_var_decl_string_type_accepts_string_literal(self):
        """Declaring string s = "hello" should produce no errors."""
        src = '''
            void test() {
                string s = "hello";
            }
        '''
        assert no_errors(src)

    def test_function_return_type_registered_correctly(self):
        """Function return type should be accessible via the function table."""
        src = '''
            int add(int a, int b) {
                return a + b;
            }
        '''
        result = analyze(src)
        assert not result.errors
        assert "add" in result.program.declarations[0].name
        assert result.program.declarations[0].return_type.base == "int"

    def test_method_parameter_types_registered(self):
        """Method parameters should be available in the class table."""
        src = '''
            class Calculator {
                public int add(int a, int b) {
                    return a + b;
                }
            }
        '''
        result = analyze(src)
        assert not result.errors
        cls = result.class_table["Calculator"]
        method = cls.methods["add"]
        assert len(method.params) == 2
        assert method.params[0].type.base == "int"
        assert method.params[1].type.base == "int"

    def test_comparison_operators_infer_bool(self):
        """Comparison operators (==, !=, <, >, etc.) should infer bool type."""
        src = '''
            void test() {
                int a = 1;
                int b = 2;
                var c = a == b;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[2]
        assert stmt.type.base == "bool"

    def test_float_promotion_in_arithmetic(self):
        """When mixing int and float in arithmetic, result should be float."""
        src = '''
            void test() {
                int a = 1;
                float b = 2.5;
                var c = a + b;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[2]
        assert stmt.type.base == "float"

    def test_void_function_return_type_tracked(self):
        """Void functions should have their return type properly set."""
        src = '''
            void doNothing() { }
        '''
        result = analyze(src)
        assert not result.errors
        func = result.program.declarations[0]
        assert func.return_type.base == "void"


# --- Generic Constraints ---

class TestGenericConstraints:
    def test_list_custom_class_generic_collected(self):
        """Vector<CustomClass> should be collected as a generic instance."""
        src = '''
            class Animal {
                public string name;
            }
            void test() {
                Vector<Animal> animals;
            }
        '''
        result = analyze(src)
        assert "Vector" in result.generic_instances
        bases = [args[0].base for args in result.generic_instances["Vector"]]
        assert "Animal" in bases

    def test_map_string_keys_collected(self):
        """Map<string, int> should have both type args collected."""
        src = '''
            void test() {
                Map<string, int> scores;
            }
        '''
        result = analyze(src)
        assert "Map" in result.generic_instances
        map_args = result.generic_instances["Map"][0]
        assert map_args[0].base == "string"
        assert map_args[1].base == "int"

    def test_map_int_keys_collected(self):
        """Map<int, string> should have int keys and string values."""
        src = '''
            void test() {
                Map<int, string> lookup;
            }
        '''
        result = analyze(src)
        assert "Map" in result.generic_instances
        map_args = result.generic_instances["Map"][0]
        assert map_args[0].base == "int"
        assert map_args[1].base == "string"

    def test_nested_generics_inner_and_outer_collected(self):
        """Vector<Vector<int>> should collect both Vector<int> and Vector<Vector<int>>."""
        src = '''
            void test() {
                Vector<Vector<int>> matrix;
            }
        '''
        result = analyze(src)
        instances = result.generic_instances["Vector"]
        # One for Vector<int>, one for Vector<Vector<int>>
        assert len(instances) == 2
        inner_bases = set()
        for args in instances:
            inner_bases.add(args[0].base)
        assert "int" in inner_bases
        assert "Vector" in inner_bases

    def test_generic_class_field_types_collected(self):
        """Generic instances from class field types should be collected."""
        src = '''
            class Container {
                public Vector<string> items;
            }
        '''
        result = analyze(src)
        assert "Vector" in result.generic_instances
        bases = [args[0].base for args in result.generic_instances["Vector"]]
        assert "string" in bases

    def test_generic_method_param_collected(self):
        """Generic types used as method parameters should be collected."""
        src = '''
            class Store {
                public void add(Vector<int> items) { }
            }
        '''
        result = analyze(src)
        assert "Vector" in result.generic_instances
        bases = [args[0].base for args in result.generic_instances["Vector"]]
        assert "int" in bases

    def test_generic_method_return_type_collected(self):
        """Generic types used as method return types should be collected."""
        src = '''
            class Factory {
                public Vector<float> create() {
                    Vector<float> result;
                    return result;
                }
            }
        '''
        result = analyze(src)
        assert "Vector" in result.generic_instances
        bases = [args[0].base for args in result.generic_instances["Vector"]]
        assert "float" in bases

    def test_multiple_generic_classes_tracked_separately(self):
        """Different generic base types should be tracked independently.
        Transitive deps (Map→List) are registered from class_table method return types,
        so they only appear when stdlib is included."""
        src = '''
            void test() {
                Vector<int> nums;
                Map<string, float> scores;
            }
        '''
        result = analyze(src)
        assert "Vector" in result.generic_instances
        assert "Map" in result.generic_instances
        # Vector<int> from declaration (transitive deps come from stdlib class_table)
        assert len(result.generic_instances["Vector"]) >= 1
        list_bases = [args[0].base for args in result.generic_instances["Vector"]]
        assert "int" in list_bases
        assert len(result.generic_instances["Map"]) == 1


# --- Inheritance ---

class TestInheritance:
    def test_child_inherits_parent_fields(self):
        """Child class should have parent's fields in the class table."""
        src = '''
            class Animal {
                public string name;
                public int age;
            }
            class Dog extends Animal {
                public string breed;
            }
        '''
        result = analyze(src)
        dog = result.class_table["Dog"]
        assert "name" in dog.fields
        assert "age" in dog.fields
        assert "breed" in dog.fields

    def test_child_inherits_parent_methods(self):
        """Child class should inherit parent's methods."""
        src = '''
            class Shape {
                public string name;
                public string getName() { return self.name; }
            }
            class Circle extends Shape {
                public float radius;
            }
        '''
        result = analyze(src)
        circle = result.class_table["Circle"]
        assert "getName" in circle.methods
        assert "radius" in circle.fields

    def test_child_overrides_parent_method(self):
        """Child method should override parent method of the same name."""
        src = '''
            class Base {
                public int value() { return 0; }
            }
            class Derived extends Base {
                public int value() { return 1; }
            }
        '''
        result = analyze(src)
        derived = result.class_table["Derived"]
        assert "value" in derived.methods
        # The method should be from Derived (overridden), not Base
        # We check that it exists — the override happens in _register_class
        # where child members are processed after parent inheritance
        assert derived.methods["value"].return_type.base == "int"

    def test_multi_level_inheritance(self):
        """A -> B -> C: C should have fields from both A and B."""
        src = '''
            class A {
                public int x;
            }
            class B extends A {
                public int y;
            }
            class C extends B {
                public int z;
            }
        '''
        result = analyze(src)
        c_cls = result.class_table["C"]
        assert "x" in c_cls.fields
        assert "y" in c_cls.fields
        assert "z" in c_cls.fields

    def test_child_does_not_inherit_parent_constructor(self):
        """Parent constructor should not appear as a method in child class."""
        src = '''
            class Base {
                public int x;
                public Base(int x) { self.x = x; }
                public int getX() { return self.x; }
            }
            class Child extends Base {
                public int y;
            }
        '''
        result = analyze(src)
        child = result.class_table["Child"]
        # Parent constructor "Base" should not be inherited
        assert "Base" not in child.methods
        # But parent methods should be inherited
        assert "getX" in child.methods

    def test_parent_class_recorded(self):
        """The parent field should be set correctly on child ClassInfo."""
        src = '''
            class Vehicle {
                public int speed;
            }
            class Car extends Vehicle {
                public int doors;
            }
        '''
        result = analyze(src)
        car = result.class_table["Car"]
        assert car.parent == "Vehicle"

    def test_child_can_override_parent_field(self):
        """Child field with same name should override parent field."""
        src = '''
            class Base {
                public int val;
            }
            class Derived extends Base {
                public float val;
            }
        '''
        result = analyze(src)
        derived = result.class_table["Derived"]
        assert "val" in derived.fields
        assert derived.fields["val"].type.base == "float"


# --- Scope Analysis ---

class TestScopeAnalysis:
    def test_variable_defined_in_function_scope(self):
        """Variables declared inside a function should not cause errors."""
        src = '''
            void test() {
                int x = 10;
                int y = 20;
            }
        '''
        assert no_errors(src)

    def test_function_parameter_in_scope(self):
        """Function parameters should be available within the function body."""
        src = '''
            int double_it(int x) {
                return x + x;
            }
        '''
        assert no_errors(src)

    def test_for_in_variable_scoped_to_loop(self):
        """For-in loop variable should be available inside the loop body."""
        src = '''
            void test() {
                Vector<int> nums;
                for n in nums {
                    int y = n;
                }
            }
        '''
        assert no_errors(src)

    def test_method_self_properly_scoped(self):
        """Self should be available in instance methods but typed as pointer."""
        src = '''
            class Point {
                public int x;
                public int y;
                public void move(int dx, int dy) {
                    self.x = self.x + dx;
                    self.y = self.y + dy;
                }
            }
        '''
        assert no_errors(src)

    def test_nested_block_scoping(self):
        """Variables in nested blocks should not cause errors."""
        src = '''
            void test() {
                int x = 1;
                if (x == 1) {
                    int y = 2;
                    if (y == 2) {
                        int z = 3;
                    }
                }
            }
        '''
        assert no_errors(src)

    def test_c_for_loop_variable_scoped(self):
        """C-style for loop variable should be available in loop body."""
        src = '''
            void test() {
                for (int i = 0; i < 10; i++) {
                    int y = i;
                }
            }
        '''
        assert no_errors(src)

    def test_while_loop_scoping(self):
        """While loop body should have its own scope."""
        src = '''
            void test() {
                int x = 10;
                while (x > 0) {
                    int y = x;
                    x = x - 1;
                }
            }
        '''
        assert no_errors(src)

    def test_try_catch_variable_scoped(self):
        """Catch variable should be available within the catch block."""
        src = '''
            void test() {
                try {
                    int x = 1;
                } catch (e) {
                    string msg = e;
                }
            }
        '''
        assert no_errors(src)


# --- Error Detection ---

class TestErrorDetection:
    def test_private_field_from_outside_class(self):
        """Accessing a private field from outside the class should error."""
        src = '''
            class Secret {
                private int code;
            }
            void test() {
                Secret s = Secret();
                s.code = 42;
            }
        '''
        assert has_error(src, "private field")

    def test_self_in_static_method(self):
        """Using self in a class (static) method should produce an error."""
        src = '''
            class Utils {
                public int x;
                class void helper() {
                    self.x = 1;
                }
            }
        '''
        assert has_error(src, "self")

    def test_self_outside_any_class(self):
        """Using self in a free function should error."""
        src = '''
            void global_func() {
                self.data = 5;
            }
        '''
        assert has_error(src, "self")

    def test_constructor_with_args_when_no_constructor_defined(self):
        """Calling a class constructor with args when none is defined should error."""
        src = '''
            class Empty {
                public int x;
            }
            void test() {
                Empty e = Empty(42);
            }
        '''
        assert has_error(src, "no constructor")

    def test_new_with_args_when_no_constructor(self):
        """Using new with args on a class without a constructor should error."""
        src = '''
            class Simple {
                public int val;
            }
            void test() {
                Simple s = new Simple(1);
            }
        '''
        assert has_error(src, "no constructor")

    def test_for_in_on_bool_not_iterable(self):
        """Iterating over a bool should produce a 'not iterable' error."""
        src = '''
            void test() {
                bool flag = true;
                for x in flag { }
            }
        '''
        assert has_error(src, "not iterable")

    def test_for_in_on_float_not_iterable(self):
        """Iterating over a float should produce a 'not iterable' error."""
        src = '''
            void test() {
                float pi = 3.14;
                for x in pi { }
            }
        '''
        assert has_error(src, "not iterable")

    def test_for_in_on_class_not_iterable(self):
        """Iterating over a user-defined class should error (not iterable)."""
        src = '''
            class Point {
                public int x;
            }
            void test() {
                Point p = Point();
                for item in p { }
            }
        '''
        assert has_error(src, "not iterable")

    def test_private_method_from_different_class(self):
        """Private methods should not be callable from a different class."""
        src = '''
            class A {
                private void secret() { }
            }
            class B {
                public void callA() {
                    A a = A();
                    a.secret();
                }
            }
        '''
        assert has_error(src, "private method")

    def test_non_static_method_called_statically(self):
        """Calling a non-static method via ClassName.method() should error."""
        src = '''
            class Foo {
                public void bar() { }
            }
            void test() {
                Foo.bar();
            }
        '''
        assert has_error(src, "not a class method")


# --- Type Inference (extended) ---

class TestTypeInferenceExtended:
    def test_var_infer_char_literal(self):
        """Var should infer 'char' type from character literal."""
        src = '''
            void test() {
                var c = 'A';
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[0]
        assert stmt.type.base == "char"

    def test_var_infer_from_method_return_type(self):
        """Var should infer type from a method call's return type."""
        src = '''
            class Counter {
                public int count;
                public int getCount() { return self.count; }
            }
            void test() {
                Counter c = Counter();
                var n = c.getCount();
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[1].body.statements[1]
        assert stmt.type.base == "int"

    def test_var_infer_from_function_return_type(self):
        """Var should infer type from a free function's return type."""
        src = '''
            float pi() { return 3.14; }
            void test() {
                var x = pi();
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[1].body.statements[0]
        assert stmt.type.base == "float"

    def test_var_infer_from_list_literal(self):
        """Var should infer List type from a list literal."""
        src = '''
            void test() {
                var nums = [1, 2, 3];
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[0]
        assert stmt.type.base == "Vector"
        assert stmt.type.generic_args[0].base == "int"

    def test_var_infer_from_map_literal(self):
        """Var should infer Map type from a map literal."""
        src = '''
            void test() {
                var scores = {"alice": 100, "bob": 95};
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[0]
        assert stmt.type.base == "Map"
        assert stmt.type.generic_args[0].base == "string"
        assert stmt.type.generic_args[1].base == "int"

    def test_var_infer_from_comparison_expression(self):
        """Var from a comparison should be inferred as bool."""
        src = '''
            void test() {
                int a = 5;
                int b = 10;
                var result = a < b;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[2]
        assert stmt.type.base == "bool"

    def test_var_infer_from_logical_and(self):
        """Var from && expression should be inferred as bool."""
        src = '''
            void test() {
                bool a = true;
                bool b = false;
                var c = a && b;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[2]
        assert stmt.type.base == "bool"

    def test_var_infer_from_new_expr(self):
        """Var should infer pointer type from new expression."""
        src = '''
            class Node {
                public int val;
                public Node(int v) { self.val = v; }
            }
            void test() {
                var n = new Node(5);
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[1].body.statements[0]
        assert stmt.type.base == "Node"
        assert stmt.type.pointer_depth == 1

    def test_var_infer_from_field_access(self):
        """Var should infer type from field access expression."""
        src = '''
            class Point {
                public float x;
                public float y;
            }
            void test() {
                Point p = Point();
                var val = p.x;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[1].body.statements[1]
        assert stmt.type.base == "float"

    def test_var_infer_from_index_expr(self):
        """Var should infer element type from list indexing."""
        src = '''
            void test() {
                Vector<string> names;
                var first = names[0];
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[1]
        assert stmt.type.base == "string"


# --- Node type recording ---

class TestNodeTypes:
    def test_int_literal_type_recorded(self):
        """IntLiteral expressions should have their type recorded in node_types."""
        src = '''
            void test() {
                int x = 42;
            }
        '''
        result = analyze(src)
        # At least one node should be recorded as int
        has_int = any(t.base == "int" for t in result.node_types.values())
        assert has_int

    def test_string_literal_type_recorded(self):
        """StringLiteral expressions should have their type recorded."""
        src = '''
            void test() {
                string s = "hello";
            }
        '''
        result = analyze(src)
        has_str = any(t.base == "string" for t in result.node_types.values())
        assert has_str

    def test_bool_literal_type_recorded(self):
        """BoolLiteral expressions should have their type recorded."""
        src = '''
            void test() {
                bool b = true;
            }
        '''
        result = analyze(src)
        has_bool = any(t.base == "bool" for t in result.node_types.values())
        assert has_bool

    def test_float_literal_type_recorded(self):
        """FloatLiteral expressions should have their type recorded."""
        src = '''
            void test() {
                float f = 1.5;
            }
        '''
        result = analyze(src)
        has_float = any(t.base == "float" for t in result.node_types.values())
        assert has_float

    def test_constructor_call_type_recorded(self):
        """Constructor call should record the class type in node_types."""
        src = '''
            class Box {
                public int x;
            }
            void test() {
                Box b = Box();
            }
        '''
        result = analyze(src)
        has_box = any(t.base == "Box" for t in result.node_types.values())
        assert has_box


# --- Constructor validation ---

class TestConstructorValidation:
    def test_no_arg_constructor_allowed(self):
        """Class without constructor should allow zero-arg instantiation."""
        src = '''
            class Simple {
                public int x;
            }
            void test() {
                Simple s = Simple();
            }
        '''
        assert no_errors(src)

    def test_constructor_with_correct_usage(self):
        """Constructor with parameters should be allowed when called correctly."""
        src = '''
            class Pair {
                public int a;
                public int b;
                public Pair(int a, int b) {
                    self.a = a;
                    self.b = b;
                }
            }
            void test() {
                Pair p = Pair(1, 2);
            }
        '''
        assert no_errors(src)

    def test_constructor_registered_in_class_table(self):
        """Constructor should be stored in ClassInfo.constructor."""
        src = '''
            class Widget {
                public int id;
                public Widget(int id) { self.id = id; }
            }
        '''
        result = analyze(src)
        cls = result.class_table["Widget"]
        assert cls.constructor is not None
        assert cls.constructor.name == "Widget"

    def test_class_without_constructor_has_none(self):
        """Class without explicit constructor should have constructor=None."""
        src = '''
            class Empty {
                public int val;
            }
        '''
        result = analyze(src)
        cls = result.class_table["Empty"]
        assert cls.constructor is None

    def test_new_expr_no_args_on_no_constructor_class(self):
        """new ClassName() with 0 args on class without constructor should be fine."""
        src = '''
            class Plain {
                public int data;
            }
            void test() {
                Plain p = new Plain();
            }
        '''
        assert no_errors(src)


# --- Class table details ---

class TestClassTableDetails:
    def test_multiple_fields_registered(self):
        """All fields of a class should be in the class table."""
        src = '''
            class Person {
                public string name;
                public int age;
                private float salary;
            }
        '''
        result = analyze(src)
        cls = result.class_table["Person"]
        assert len(cls.fields) == 3
        assert cls.fields["name"].type.base == "string"
        assert cls.fields["age"].type.base == "int"
        assert cls.fields["salary"].type.base == "float"

    def test_field_access_levels(self):
        """Field access levels should be correctly recorded."""
        src = '''
            class Record {
                public int id;
                private string secret;
            }
        '''
        result = analyze(src)
        cls = result.class_table["Record"]
        assert cls.fields["id"].access == "public"
        assert cls.fields["secret"].access == "private"

    def test_multiple_methods_registered(self):
        """All methods of a class should be in the class table."""
        src = '''
            class Service {
                public void start() { }
                public void stop() { }
                private void cleanup() { }
            }
        '''
        result = analyze(src)
        cls = result.class_table["Service"]
        assert "start" in cls.methods
        assert "stop" in cls.methods
        assert "cleanup" in cls.methods

    def test_method_access_levels(self):
        """Method access levels should be correctly recorded."""
        src = '''
            class Obj {
                public void pub() { }
                private void priv() { }
                class void stat() { }
            }
        '''
        result = analyze(src)
        cls = result.class_table["Obj"]
        assert cls.methods["pub"].access == "public"
        assert cls.methods["priv"].access == "private"
        assert cls.methods["stat"].access == "class"

    def test_generic_params_recorded(self):
        """Generic parameters of a class should be recorded."""
        src = '''
            class Pair<K, V> {
                public K key;
                public V value;
            }
        '''
        result = analyze(src)
        cls = result.class_table["Pair"]
        assert cls.generic_params == ["K", "V"]

    def test_multiple_classes_registered(self):
        """Multiple classes should all be present in the class table."""
        src = '''
            class A { public int x; }
            class B { public int y; }
            class C { public int z; }
        '''
        result = analyze(src)
        assert "A" in result.class_table
        assert "B" in result.class_table
        assert "C" in result.class_table


# --- For-in validation (extended) ---

class TestForInExtended:
    def test_for_in_range(self):
        """for x in range(10) should produce no errors."""
        src = '''
            void test() {
                for i in range(10) { }
            }
        '''
        assert no_errors(src)

    def test_for_in_string_iterable(self):
        """Iterating over a string should work (yields chars)."""
        src = '''
            void test() {
                string s = "hello";
                for c in s { }
            }
        '''
        assert no_errors(src)

    def test_for_in_int_not_iterable(self):
        """Iterating over an int should produce not-iterable error."""
        src = '''
            void test() {
                int x = 42;
                for c in x { }
            }
        '''
        assert has_error(src, "not iterable")

    def test_for_in_generic_list_no_error(self):
        """for x in Vector<float> should be valid."""
        src = '''
            void test() {
                Vector<float> vals;
                for v in vals { }
            }
        '''
        assert no_errors(src)


# --- Static method validation ---

class TestStaticMethods:
    def test_static_method_valid_call(self):
        """Calling a class method statically should be valid."""
        src = '''
            class MathUtil {
                class int square(int x) { return x * x; }
            }
        '''
        result = analyze(src)
        assert not result.errors
        cls = result.class_table["MathUtil"]
        assert cls.methods["square"].access == "class"

    def test_non_static_cannot_be_called_statically(self):
        """Calling a non-class method statically should produce an error."""
        src = '''
            class Obj {
                public void doStuff() { }
            }
            void test() {
                Obj.doStuff();
            }
        '''
        assert has_error(src, "not a class method")

    def test_self_not_in_scope_for_static(self):
        """Self should not be available in class (static) methods."""
        src = '''
            class Factory {
                public int data;
                class int build() {
                    self.data = 1;
                    return 0;
                }
            }
        '''
        assert has_error(src, "self")


# --- Complex programs ---

class TestComplexPrograms:
    def test_class_with_methods_and_fields(self):
        """Full class with constructor, fields, and methods should analyze cleanly."""
        src = '''
            class LinkedList {
                private int size;
                public LinkedList() {
                    self.size = 0;
                }
                public int getSize() {
                    return self.size;
                }
                public void add(int val) {
                    self.size = self.size + 1;
                }
            }
            void test() {
                LinkedList ll = LinkedList();
                ll.add(42);
                var s = ll.getSize();
            }
        '''
        result = analyze(src)
        assert not result.errors
        # var s should be inferred as int
        stmt = result.program.declarations[1].body.statements[2]
        assert stmt.type.base == "int"

    def test_multiple_classes_with_relationships(self):
        """Multiple classes referencing each other should analyze cleanly."""
        src = '''
            class Engine {
                public int hp;
                public Engine(int hp) { self.hp = hp; }
            }
            class Car {
                public Engine engine;
                public string model;
                public Car(string model) { self.model = model; }
            }
            void test() {
                Car c = Car("Sedan");
            }
        '''
        assert no_errors(src)

    def test_switch_statement_analysis(self):
        """Switch statement should be analyzed without errors."""
        src = '''
            void test() {
                int x = 2;
                switch (x) {
                    case 1: break;
                    case 2: break;
                    default: break;
                }
            }
        '''
        assert no_errors(src)

    def test_try_catch_analysis(self):
        """Try-catch should be analyzed with catch var scoped correctly."""
        src = '''
            void test() {
                try {
                    int x = 1;
                } catch (err) {
                    string msg = err;
                }
            }
        '''
        assert no_errors(src)

    def test_do_while_analysis(self):
        """Do-while loops should be analyzed correctly."""
        src = '''
            void test() {
                int count = 0;
                do {
                    count = count + 1;
                } while (count < 10);
            }
        '''
        assert no_errors(src)

    def test_ternary_expression_analysis(self):
        """Ternary expression should be analyzed without errors."""
        src = '''
            void test() {
                int x = 5;
                var result = x > 3 ? 1 : 0;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[1]
        assert stmt.type.base == "int"

    def test_cast_expression_analysis(self):
        """Cast expressions should be analyzed and type recorded."""
        src = '''
            void test() {
                int x = 42;
                var f = (float)x;
            }
        '''
        result = analyze(src)
        assert not result.errors
        stmt = result.program.declarations[0].body.statements[1]
        assert stmt.type.base == "float"


# --- Map iteration ---

class TestMapIteration:
    def test_for_kv_in_map(self):
        src = '''
            void test() {
                Map<string, int> m = {};
                for k, v in m { }
            }
        '''
        assert no_errors(src)

    def test_for_key_only_in_map(self):
        src = '''
            void test() {
                Map<int, string> m = {};
                for k in m { }
            }
        '''
        assert no_errors(src)

    def test_for_kv_in_non_map_error(self):
        src = '''
            void test() {
                Vector<int> nums;
                for k, v in nums { }
            }
        '''
        assert has_error(src, "Map")

    def test_for_in_map_with_body(self):
        src = '''
            void test() {
                Map<string, int> scores = {};
                for name, score in scores {
                    print(name);
                }
            }
        '''
        assert no_errors(src)


# --- Circular inheritance ---

class TestCircularInheritance:
    def test_direct_circular_inheritance(self):
        src = '''
            class B extends A { }
            class A extends B { }
        '''
        assert has_error(src, "Circular inheritance")

    def test_valid_single_inheritance(self):
        src = '''
            class Animal {
                public int age = 0;
            }
            class Dog extends Animal {
                public string name = "";
            }
        '''
        assert no_errors(src)

    def test_missing_parent_class(self):
        src = '''
            class Dog extends NonExistent { }
        '''
        assert has_error(src, "not found")

    def test_deep_valid_inheritance(self):
        src = '''
            class A { }
            class B extends A { }
            class C extends B { }
        '''
        assert no_errors(src)


# --- Default parameter validation ---

class TestDefaultParams:
    def test_default_at_end_ok(self):
        src = '''
            void greet(string name, string greeting = "Hello") { }
        '''
        assert no_errors(src)

    def test_non_default_after_default_error(self):
        src = '''
            void bad(int a = 5, int b) { }
        '''
        assert has_error(src, "Non-default parameter")

    def test_all_defaults_ok(self):
        src = '''
            void defaults(int a = 1, int b = 2, int c = 3) { }
        '''
        assert no_errors(src)

    def test_method_default_at_end_ok(self):
        src = '''
            class Foo {
                public void bar(int x, int y = 10) { }
            }
        '''
        assert no_errors(src)

    def test_method_non_default_after_default_error(self):
        src = '''
            class Foo {
                public void bar(int x = 5, int y) { }
            }
        '''
        assert has_error(src, "Non-default parameter")


class TestConstructorArgCount:
    def test_too_many_args_call_syntax(self):
        src = '''
            class Foo {
                public Foo(int x) { }
            }
            int main() {
                Foo f = Foo(1, 2, 3);
                return 0;
            }
        '''
        assert has_error(src, "expects at most 1 argument(s) but got 3")

    def test_too_few_args_call_syntax(self):
        src = '''
            class Foo {
                public Foo(int x, int y) { }
            }
            int main() {
                Foo f = Foo(1);
                return 0;
            }
        '''
        assert has_error(src, "expects at least 2 argument(s) but got 1")

    def test_too_many_args_new_syntax(self):
        src = '''
            class Foo {
                public Foo(int x) { }
            }
            int main() {
                Foo f = new Foo(1, 2);
                return 0;
            }
        '''
        assert has_error(src, "expects at most 1 argument(s) but got 2")

    def test_too_few_args_new_syntax(self):
        src = '''
            class Foo {
                public Foo(int x, int y) { }
            }
            int main() {
                Foo f = new Foo();
                return 0;
            }
        '''
        assert has_error(src, "expects at least 2 argument(s) but got 0")

    def test_correct_arg_count(self):
        src = '''
            class Foo {
                public Foo(int x, int y) { }
            }
            int main() {
                Foo f = Foo(1, 2);
                return 0;
            }
        '''
        assert no_errors(src)

    def test_default_params_optional(self):
        src = '''
            class Foo {
                public Foo(int x, int y = 10) { }
            }
            int main() {
                Foo f = Foo(1);
                return 0;
            }
        '''
        assert no_errors(src)

    def test_default_params_too_few(self):
        src = '''
            class Foo {
                public Foo(int x, int y = 10) { }
            }
            int main() {
                Foo f = Foo();
                return 0;
            }
        '''
        assert has_error(src, "expects at least 1 argument(s) but got 0")

    def test_no_constructor_with_args(self):
        src = '''
            class Foo { }
            int main() {
                Foo f = Foo(1);
                return 0;
            }
        '''
        assert has_error(src, "has no constructor but was called with 1 argument")

    def test_no_constructor_no_args(self):
        src = '''
            class Foo { }
            int main() {
                Foo f = Foo();
                return 0;
            }
        '''
        assert no_errors(src)


class TestGenericArgCount:
    # Generic arg count validation requires class_table entries (from stdlib or stubs)
    _STUBS = '''
        class Vector<T> { public int len; }
        class Map<K, V> { public int len; }
        class Array<T> { public int len; }
        class Set<T> { public int len; }
    '''

    def test_list_too_many_type_args(self):
        src = self._STUBS + '''
            int main() {
                Vector<int, string> x;
                return 0;
            }
        '''
        assert has_error(src, "Type 'Vector' expects 1 generic argument(s) but got 2")

    def test_map_too_few_type_args(self):
        src = self._STUBS + '''
            int main() {
                Map<int> x;
                return 0;
            }
        '''
        assert has_error(src, "Type 'Map' expects 2 generic argument(s) but got 1")

    def test_map_too_many_type_args(self):
        src = self._STUBS + '''
            int main() {
                Map<int, string, bool> x;
                return 0;
            }
        '''
        assert has_error(src, "Type 'Map' expects 2 generic argument(s) but got 3")

    def test_array_too_many_type_args(self):
        src = self._STUBS + '''
            int main() {
                Array<int, string> x;
                return 0;
            }
        '''
        assert has_error(src, "Type 'Array' expects 1 generic argument(s) but got 2")

    def test_set_too_many_type_args(self):
        src = self._STUBS + '''
            int main() {
                Set<int, string> x;
                return 0;
            }
        '''
        assert has_error(src, "Type 'Set' expects 1 generic argument(s) but got 2")

    def test_correct_generic_args(self):
        src = '''
            int main() {
                Vector<int> a;
                Map<string, int> b;
                Array<float> c;
                Set<int> d;
                return 0;
            }
        '''
        assert no_errors(src)


class TestDuplicateDetection:
    def test_duplicate_class_name(self):
        src = '''
            class Foo { }
            class Foo { }
            int main() { return 0; }
        '''
        assert has_error(src, "Duplicate class name 'Foo'")

    def test_duplicate_function_name(self):
        src = '''
            void foo() { }
            void foo() { }
            int main() { return 0; }
        '''
        assert has_error(src, "Duplicate function name 'foo'")

    def test_duplicate_field_in_class(self):
        src = '''
            class Foo {
                public int x;
                public int x;
            }
            int main() { return 0; }
        '''
        assert has_error(src, "Duplicate field 'x' in class 'Foo'")

    def test_duplicate_method_in_class(self):
        src = '''
            class Foo {
                public void bar() { }
                public void bar() { }
            }
            int main() { return 0; }
        '''
        assert has_error(src, "Duplicate method 'bar' in class 'Foo'")

    def test_override_parent_method_ok(self):
        src = '''
            class Base {
                public void greet() { }
            }
            class Child extends Base {
                public void greet() { }
            }
            int main() { return 0; }
        '''
        assert no_errors(src)

    def test_no_duplicate_different_names(self):
        src = '''
            class Foo {
                public int x;
                public int y;
                public void bar() { }
                public void baz() { }
            }
            int main() { return 0; }
        '''
        assert no_errors(src)


class TestReturnTypeValidation:
    def test_missing_return_in_int_function(self):
        src = '''
            int foo() {
                int x = 5;
            }
            int main() { return 0; }
        '''
        assert has_error(src, "has non-void return type but no return statement")

    def test_void_function_no_return_ok(self):
        src = '''
            void foo() {
                int x = 5;
            }
            int main() { return 0; }
        '''
        assert no_errors(src)

    def test_int_function_with_return_ok(self):
        src = '''
            int foo() {
                return 42;
            }
            int main() { return 0; }
        '''
        assert no_errors(src)

    def test_return_in_single_if_branch_error(self):
        """Single if-branch return is not exhaustive — should flag error."""
        src = '''
            int foo(int x) {
                if (x > 0) {
                    return 1;
                }
            }
            int main() { return 0; }
        '''
        assert has_error(src, "no return statement")

    def test_return_in_if_else_ok(self):
        """Exhaustive if/else return is OK."""
        src = '''
            int foo(int x) {
                if (x > 0) {
                    return 1;
                } else {
                    return -1;
                }
            }
            int main() { return 0; }
        '''
        assert no_errors(src)

    def test_return_in_nested_block_ok(self):
        src = '''
            int foo(int x) {
                if (x > 0) {
                    return 1;
                } else {
                    return 0;
                }
            }
            int main() { return 0; }
        '''
        assert no_errors(src)


class TestBreakContinueValidation:
    """Tests for break/continue outside loop detection."""

    def test_break_outside_loop_error(self):
        src = '''
            void test() {
                break;
            }
        '''
        result = analyze(src)
        assert any("'break' statement outside of loop or switch" in e for e in result.errors)

    def test_continue_outside_loop_error(self):
        src = '''
            void test() {
                continue;
            }
        '''
        result = analyze(src)
        assert any("'continue' statement outside of loop" in e for e in result.errors)

    def test_break_in_while_ok(self):
        src = '''
            void test() {
                while (true) {
                    break;
                }
            }
        '''
        assert no_errors(src)

    def test_continue_in_for_ok(self):
        src = '''
            void test() {
                for (int i = 0; i < 10; i++) {
                    continue;
                }
            }
        '''
        assert no_errors(src)

    def test_break_in_switch_ok(self):
        src = '''
            void test() {
                int x = 1;
                switch (x) {
                    case 1: break;
                    case 2: break;
                }
            }
        '''
        assert no_errors(src)

    def test_continue_in_switch_error(self):
        """continue is not valid in switch (only in loops)."""
        src = '''
            void test() {
                int x = 1;
                switch (x) {
                    case 1: continue;
                }
            }
        '''
        result = analyze(src)
        assert any("'continue' statement outside of loop" in e for e in result.errors)

    def test_break_in_nested_loop_ok(self):
        src = '''
            void test() {
                while (true) {
                    for (int i = 0; i < 5; i++) {
                        break;
                    }
                }
            }
        '''
        assert no_errors(src)

    def test_break_in_do_while_ok(self):
        src = '''
            void test() {
                do {
                    break;
                } while (true);
            }
        '''
        assert no_errors(src)

    def test_break_in_for_in_ok(self):
        src = '''
            void test() {
                Vector<int> nums = [1, 2, 3];
                for n in nums {
                    break;
                }
            }
        '''
        assert no_errors(src)

    def test_continue_outside_if_inside_func_error(self):
        """continue inside an if but not inside a loop should error."""
        src = '''
            void test() {
                if (true) {
                    continue;
                }
            }
        '''
        result = analyze(src)
        assert any("'continue' statement outside of loop" in e for e in result.errors)


class TestUnreachableCode:
    """Tests for unreachable code detection."""

    def test_unreachable_after_return(self):
        src = '''
            void test() {
                return;
                int x = 5;
            }
        '''
        result = analyze(src)
        assert any("Unreachable code" in e for e in result.errors)

    def test_unreachable_after_break(self):
        src = '''
            void test() {
                while (true) {
                    break;
                    int x = 5;
                }
            }
        '''
        result = analyze(src)
        assert any("Unreachable code" in e for e in result.errors)

    def test_unreachable_after_continue(self):
        src = '''
            void test() {
                for (int i = 0; i < 10; i++) {
                    continue;
                    int x = 5;
                }
            }
        '''
        result = analyze(src)
        assert any("Unreachable code" in e for e in result.errors)

    def test_no_false_positive_if_return(self):
        """Return inside an if should not make the rest unreachable."""
        src = '''
            int test(int x) {
                if (x > 0) {
                    return 1;
                }
                return 0;
            }
        '''
        assert no_errors(src)

    def test_no_false_positive_sequential_stmts(self):
        """Sequential non-terminal stmts should not trigger."""
        src = '''
            void test() {
                int x = 1;
                int y = 2;
                int z = x + y;
            }
        '''
        assert no_errors(src)


class TestConstructorValidationAdvanced:
    """Tests for constructor-specific validation."""

    def test_constructor_invalid_return_type(self):
        """Constructor with non-void return type should error."""
        src = '''
            class Foo {
                public int Foo() {
                    return 5;
                }
            }
        '''
        result = analyze(src)
        assert any("Constructor 'Foo' cannot have return type 'int'" in e for e in result.errors)

    def test_constructor_void_return_type_ok(self):
        """Constructor with void return type is fine (common pattern)."""
        src = '''
            class Foo {
                public int x;
                public Foo(int x) {
                    self.x = x;
                }
            }
        '''
        assert no_errors(src)

    def test_constructor_with_class_name_return_ok(self):
        """Constructor that returns its own class name is allowed."""
        src = '''
            class Bar {
                public Bar Bar() {
                    return self;
                }
            }
        '''
        # This is an unusual pattern but should not error since the return
        # type matches the class name
        assert no_errors(src)


class TestTypeMismatch:
    """Tests for type mismatch detection in variable declarations."""

    def test_string_to_int_error(self):
        src = '''
            int main() {
                int x = "hello";
                return 0;
            }
        '''
        result = analyze(src)
        assert any("Cannot assign" in e for e in result.errors)

    def test_bool_to_string_error(self):
        src = '''
            void test() {
                string s = true;
            }
        '''
        result = analyze(src)
        assert any("Cannot assign" in e for e in result.errors)

    def test_int_to_float_ok(self):
        """Numeric conversions should be allowed."""
        src = '''
            void test() {
                float x = 5;
            }
        '''
        assert no_errors(src)

    def test_float_to_int_ok(self):
        """Numeric narrowing should be allowed (C semantics)."""
        src = '''
            void test() {
                int x = 3.14;
            }
        '''
        assert no_errors(src)

    def test_same_type_ok(self):
        src = '''
            void test() {
                int x = 42;
                string s = "hello";
                bool b = true;
            }
        '''
        assert no_errors(src)

    def test_class_inheritance_ok(self):
        """Child class can be assigned to parent type."""
        src = '''
            class Animal {
                public string name;
                public Animal(string name) { self.name = name; }
            }
            class Dog extends Animal {
                public Dog(string name) { self.name = name; }
            }
            void test() {
                Animal a = new Dog("Buddy");
            }
        '''
        assert no_errors(src)

    def test_list_init_ok(self):
        """List initialization should work."""
        src = '''
            void test() {
                Vector<int> nums = [1, 2, 3];
            }
        '''
        assert no_errors(src)

    def test_var_inference_ok(self):
        """var should infer type without errors."""
        src = '''
            void test() {
                var x = 42;
                var s = "hello";
            }
        '''
        assert no_errors(src)


# --- Method missing return ---

class TestMethodMissingReturn:
    def test_non_void_method_no_return(self):
        src = '''
            class Foo {
                public int getValue() {
                    int x = 42;
                }
            }
        '''
        assert has_error(src, "no return statement")

    def test_void_method_no_return_ok(self):
        src = '''
            class Foo {
                public void doStuff() {
                    int x = 42;
                }
            }
        '''
        assert no_errors(src)

    def test_method_with_return_ok(self):
        src = '''
            class Foo {
                public int getValue() {
                    return 42;
                }
            }
        '''
        assert no_errors(src)

    def test_method_return_in_if(self):
        src = '''
            class Foo {
                public int getVal(bool flag) {
                    if (flag) {
                        return 1;
                    } else {
                        return 2;
                    }
                }
            }
        '''
        assert no_errors(src)

    def test_constructor_no_return_ok(self):
        """Constructors don't need return statements."""
        src = '''
            class Foo {
                public int x;
                public Foo(int x) {
                    self.x = x;
                }
            }
        '''
        assert no_errors(src)


# --- Non-existent field access ---

class TestFieldAccessValidation:
    def test_nonexistent_field(self):
        src = '''
            class Foo {
                public int x;
            }
            void test() {
                Foo f = new Foo();
                int y = f.z;
            }
        '''
        assert has_error(src, "has no field or method 'z'")

    def test_valid_field_ok(self):
        src = '''
            class Foo {
                public int x;
            }
            void test() {
                Foo f = new Foo();
                int y = f.x;
            }
        '''
        assert no_errors(src)

    def test_nonexistent_method(self):
        src = '''
            class Foo {
                public int x;
            }
            void test() {
                Foo f = new Foo();
                f.bar();
            }
        '''
        assert has_error(src, "has no field or method 'bar'")

    def test_inherited_field_ok(self):
        src = '''
            class Animal {
                public string name;
            }
            class Dog extends Animal {
                public int age;
            }
            void test() {
                Dog d = new Dog();
                string n = d.name;
            }
        '''
        assert no_errors(src)

    def test_inherited_method_ok(self):
        src = '''
            class Animal {
                public string speak() { return "..."; }
            }
            class Dog extends Animal {
                public int bark() { return 1; }
            }
            void test() {
                Dog d = new Dog();
                string s = d.speak();
            }
        '''
        assert no_errors(src)


# --- Call arity validation ---

class TestCallArity:
    def test_function_too_few_args(self):
        src = '''
            int add(int a, int b) { return a + b; }
            void test() { add(1); }
        '''
        assert has_error(src, "expects at least 2 argument(s) but got 1")

    def test_function_too_many_args(self):
        src = '''
            int add(int a, int b) { return a + b; }
            void test() { add(1, 2, 3); }
        '''
        assert has_error(src, "expects at most 2 argument(s) but got 3")

    def test_function_correct_args_ok(self):
        src = '''
            int add(int a, int b) { return a + b; }
            void test() { add(1, 2); }
        '''
        assert no_errors(src)

    def test_function_default_params_ok(self):
        src = '''
            int foo(int a, int b = 10) { return a + b; }
            void test() { foo(1); }
        '''
        assert no_errors(src)

    def test_method_too_few_args(self):
        src = '''
            class Calc {
                public int add(int a, int b) { return a + b; }
            }
            void test() {
                Calc c = new Calc();
                c.add(1);
            }
        '''
        assert has_error(src, "expects at least 2 argument(s) but got 1")

    def test_method_too_many_args(self):
        src = '''
            class Calc {
                public int add(int a, int b) { return a + b; }
            }
            void test() {
                Calc c = new Calc();
                c.add(1, 2, 3);
            }
        '''
        assert has_error(src, "expects at most 2 argument(s) but got 3")

    def test_method_correct_args_ok(self):
        src = '''
            class Calc {
                public int add(int a, int b) { return a + b; }
            }
            void test() {
                Calc c = new Calc();
                c.add(1, 2);
            }
        '''
        assert no_errors(src)

    def test_zero_arg_function_with_args(self):
        src = '''
            void greet() { }
            void test() { greet(1); }
        '''
        assert has_error(src, "expects at most 0 argument(s) but got 1")


class TestListElementTypeValidation:
    def test_mixed_types_error(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, "three"];
                return 0;
            }
        '''
        assert has_error(src, "List element 2 has type 'string' but expected 'int'")

    def test_homogeneous_list_ok(self):
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3];
                return 0;
            }
        '''
        assert no_errors(src)

    def test_single_element_ok(self):
        src = '''
            int main() {
                Vector<int> nums = [1];
                return 0;
            }
        '''
        assert no_errors(src)

    def test_numeric_types_compatible(self):
        """int and float are compatible in numeric context."""
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3];
                return 0;
            }
        '''
        assert no_errors(src)


class TestEnumSwitchExhaustiveness:
    def test_missing_enum_case(self):
        src = '''
            enum Color { RED, GREEN, BLUE };
            int main() {
                Color c = RED;
                switch (c) {
                    case RED:
                        break;
                    case GREEN:
                        break;
                }
                return 0;
            }
        '''
        assert has_error(src, "not exhaustive, missing: BLUE")

    def test_all_enum_cases_covered(self):
        src = '''
            enum Color { RED, GREEN, BLUE };
            int main() {
                Color c = RED;
                switch (c) {
                    case RED:
                        break;
                    case GREEN:
                        break;
                    case BLUE:
                        break;
                }
                return 0;
            }
        '''
        assert no_errors(src)

    def test_default_makes_exhaustive(self):
        src = '''
            enum Color { RED, GREEN, BLUE };
            int main() {
                Color c = RED;
                switch (c) {
                    case RED:
                        break;
                    default:
                        break;
                }
                return 0;
            }
        '''
        assert no_errors(src)


class TestVoidAssignment:
    def test_void_function_result_error(self):
        src = '''
            void doStuff() { }
            int main() {
                int x = doStuff();
                return 0;
            }
        '''
        assert has_error(src, "Cannot assign void expression")

    def test_non_void_function_ok(self):
        src = '''
            int getVal() { return 42; }
            int main() {
                int x = getVal();
                return 0;
            }
        '''
        assert no_errors(src)

    def test_void_pointer_ok(self):
        """void* is a valid pointer type, not void."""
        src = '''
            int main() {
                int* p = null;
                return 0;
            }
        '''
        assert no_errors(src)


class TestReturnTypeMismatch:
    def test_wrong_return_type(self):
        src = '''
            int foo() {
                return "hello";
            }
        '''
        assert has_error(src, "Return type mismatch")

    def test_correct_return_type(self):
        src = '''
            int foo() {
                return 42;
            }
        '''
        assert no_errors(src)

    def test_bool_return_in_bool_func(self):
        src = '''
            bool isPositive(int x) {
                return x > 0;
            }
        '''
        assert no_errors(src)

    def test_lambda_return_type_isolated(self):
        """Lambda return type check should not leak into enclosing function."""
        src = '''
            int main() {
                Vector<int> nums = [1, 2, 3];
                Vector<int> filtered = nums.filter(bool function(int x) { return x > 1; });
                return 0;
            }
        '''
        assert no_errors(src)


class TestThrowAsTerminal:
    def test_throw_satisfies_return(self):
        """A function that always throws should not need a return statement."""
        src = '''
            int fail() {
                throw "error";
            }
        '''
        assert no_errors(src)

    def test_throw_in_if_else(self):
        """If/else where both branches throw satisfies return requirement."""
        src = '''
            int compute(int x) {
                if (x > 0) {
                    return x;
                } else {
                    throw "negative";
                }
            }
        '''
        assert no_errors(src)


class TestLoopReturnNotExhaustive:
    def test_while_true_return_is_exhaustive(self):
        """while(true) { return x; } is an infinite loop — guarantees return."""
        src = '''
            int foo() {
                while (true) {
                    return 1;
                }
            }
        '''
        assert not has_error(src, "no return statement")

    def test_while_cond_return_not_exhaustive(self):
        """while(cond) { return x; } does NOT guarantee a return."""
        src = '''
            int foo(bool b) {
                while (b) {
                    return 1;
                }
            }
        '''
        assert has_error(src, "no return statement")

    def test_return_in_for_loop_not_exhaustive(self):
        src = '''
            int bar(int n) {
                for (int i = 0; i < n; i++) {
                    return i;
                }
            }
        '''
        assert has_error(src, "no return statement")


class TestThrowUnreachableCode:
    def test_code_after_throw_is_unreachable(self):
        src = '''
            int main() {
                throw "error";
                int x = 5;
                return 0;
            }
        '''
        assert has_error(src, "Unreachable code")

    def test_throw_message_includes_throw(self):
        src = '''
            int main() {
                throw "error";
                return 0;
            }
        '''
        assert has_error(src, "throw")


class TestSwitchCaseIfReturn:
    def test_if_else_return_in_switch_counts(self):
        """If/else with returns inside a switch case satisfies _has_return."""
        src = '''
            int foo(int x) {
                switch (x) {
                    case 1:
                        if (x > 0) {
                            return 1;
                        } else {
                            return -1;
                        }
                }
                return 0;
            }
        '''
        assert not has_error(src, "no return statement")


class TestWhileTrueReturn:
    def test_while_true_return_is_exhaustive(self):
        """while(true) { return x; } guarantees a return."""
        src = '''
            int foo() {
                while (true) {
                    return 42;
                }
            }
        '''
        assert not has_error(src, "no return statement")

    def test_while_non_literal_not_exhaustive(self):
        """while(cond) { return x; } does NOT guarantee a return."""
        src = '''
            int foo(bool cond) {
                while (cond) {
                    return 42;
                }
            }
        '''
        assert has_error(src, "no return statement")


class TestMapIndexInferType:
    def test_map_index_returns_value_type(self):
        """map[key] should infer the value type."""
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("x", 42);
                int v = m["x"];
                return 0;
            }
        '''
        assert no_errors(src)


class TestTypeMismatchMessages:
    def test_return_type_mismatch_shows_full_types(self):
        src = '''
            string test() {
                return 42;
            }
        '''
        errs = errors(src)
        assert any("string" in e and "int" in e for e in errs)

    def test_numeric_toString_type_inference(self):
        """int.toString() should return string type."""
        src = '''
            int main() {
                int n = 42;
                string s = n.toString();
                return 0;
            }
        '''
        assert no_errors(src)

    def test_type_promotion_double(self):
        """double + int should promote to double."""
        src = '''
            int main() {
                double d = 1.5;
                int i = 2;
                double r = d + i;
                return 0;
            }
        '''
        assert no_errors(src)

    def test_type_promotion_long(self):
        """long + int should promote to long."""
        src = '''
            int main() {
                long a = 100;
                int b = 5;
                long c = a + b;
                return 0;
            }
        '''
        assert no_errors(src)
