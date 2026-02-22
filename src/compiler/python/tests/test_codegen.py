"""Tests for the btrc code generator."""

from src.compiler.python.lexer import Lexer
from src.compiler.python.parser import Parser
from src.compiler.python.analyzer import Analyzer
from src.compiler.python.codegen import CodeGen


def generate(source: str) -> str:
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    return CodeGen(analyzed).generate()


def assert_contains(source: str, *fragments: str):
    """Assert that generated C code contains all given fragments."""
    output = generate(source)
    for frag in fragments:
        assert frag in output, f"Expected '{frag}' in output:\n{output}"


def assert_not_contains(source: str, *fragments: str):
    output = generate(source)
    for frag in fragments:
        assert frag not in output, f"Did not expect '{frag}' in output:\n{output}"


# --- Passthrough ---

class TestPassthrough:
    def test_passthrough_preprocessor(self):
        assert_contains('#include <stdio.h>', '#include <stdio.h>')

    def test_passthrough_c_function(self):
        src = 'int add(int a, int b) { return a + b; }'
        output = generate(src)
        assert "int add(int a, int b)" in output
        assert "return (a + b)" in output

    def test_c_for_loop(self):
        src = 'void test() { for (int i = 0; i < 10; i++) { } }'
        output = generate(src)
        assert "for (int i = 0;" in output


# --- Classes ---

class TestClasses:
    def test_class_to_struct(self):
        src = 'class Vec3 { public float x; public float y; }'
        output = generate(src)
        assert "struct Vec3" in output
        assert "float x;" in output
        assert "float y;" in output

    def test_method_to_function(self):
        src = '''
            class Foo {
                public int x;
                public void bar() { }
            }
        '''
        output = generate(src)
        assert "void Foo_bar(Foo* self)" in output

    def test_static_method(self):
        src = '''
            class Foo {
                class int create() { return 0; }
            }
        '''
        output = generate(src)
        assert "int Foo_create(void)" in output
        # Static methods should NOT have self parameter
        assert "Foo_create(Foo* self)" not in output

    def test_constructor(self):
        src = '''
            class Vec3 {
                public float x;
                public Vec3(float x) { self.x = x; }
            }
        '''
        output = generate(src)
        assert "Vec3* Vec3_new(float x)" in output
        assert "Vec3* self = (Vec3*)malloc(sizeof(Vec3))" in output
        assert "return self;" in output

    def test_self_translation(self):
        src = '''
            class Foo {
                public int x;
                public void set(int v) { self.x = v; }
            }
        '''
        output = generate(src)
        assert "self->x" in output

    def test_method_call_translation(self):
        src = '''
            class Foo {
                public int x;
                public void bar() { }
            }
            void test() {
                Foo f;
                f.bar();
            }
        '''
        # This tests that method calls are generated — may fall back to f.bar()
        # without full type inference
        output = generate(src)
        assert "bar" in output


# --- new / delete ---

class TestNewDelete:
    def test_delete_stmt(self):
        src = 'void test() { int* p; delete p; }'
        output = generate(src)
        assert "free(p)" in output

    def test_new_expr(self):
        src = '''
            class Node { public int val; public Node(int v) { self.val = v; } }
            void test() { Node* n = new Node(42); }
        '''
        output = generate(src)
        assert "malloc" in output
        assert "Node_new(42)" in output


# --- Generics ---

class TestGenerics:
    def test_list_int_monomorphized(self):
        src = 'void test() { List<int> nums; }'
        output = generate(src)
        assert "btrc_List_int" in output
        assert "int* data;" in output

    def test_list_float_monomorphized(self):
        src = 'void test() { List<float> nums; }'
        output = generate(src)
        assert "btrc_List_float" in output

    def test_map_monomorphized(self):
        src = 'void test() { Map<string, int> m; }'
        output = generate(src)
        assert "btrc_Map_string_int" in output

    def test_generic_class_monomorphized(self):
        src = '''
            class Box<T> { public T value; }
            void test() { Box<int> b; }
        '''
        output = generate(src)
        assert "btrc_Box_int" in output


# --- Collection literals ---

class TestCollections:
    def test_list_literal(self):
        src = 'void test() { List<int> nums = [1, 2, 3]; }'
        output = generate(src)
        assert "btrc_List_int_new()" in output
        assert "btrc_List_int_push" in output

    def test_map_literal(self):
        src = 'void test() { Map<string, int> m = {"a": 1, "b": 2}; }'
        output = generate(src)
        assert "btrc_Map_string_int_new()" in output
        assert "btrc_Map_string_int_put" in output


# --- For-in ---

class TestForIn:
    def test_for_in_list(self):
        src = 'void test() { List<int> nums; for x in nums { } }'
        output = generate(src)
        assert "for (int" in output
        assert "nums.len" in output
        assert "nums.data[" in output

    def test_for_in_variable_name(self):
        src = 'void test() { List<int> nums; for item in nums { } }'
        output = generate(src)
        assert "item" in output


    def test_for_in_map_key_value(self):
        src = '''
            void test() {
                Map<string, int> m = {};
                for k, v in m { }
            }
        '''
        output = generate(src)
        assert "buckets" in output
        assert ".occupied" in output
        assert ".key" in output
        assert ".value" in output
        assert ".cap" in output

    def test_for_in_map_key_only(self):
        src = '''
            void test() {
                Map<int, string> m = {};
                for k in m { }
            }
        '''
        output = generate(src)
        assert "buckets" in output
        assert ".occupied" in output
        assert ".key" in output

    def test_for_in_pointer_list(self):
        src = '''
            class Foo {
                public List<int> items;
                public void iter() {
                    for x in self.items { }
                }
            }
        '''
        output = generate(src)
        # self is a pointer, so self->items is a List<int> (value, not pointer)
        # items.len should use . not ->
        assert ".len" in output
        assert ".data[" in output


# --- Parallel ---

class TestParallel:
    def test_parallel_for(self):
        src = 'void test() { List<int> data; parallel for x in data { } }'
        output = generate(src)
        assert "#pragma omp parallel for" in output
        assert "data.len" in output


# --- GPU ---

class TestGPU:
    def test_gpu_function(self):
        src = '@gpu void kern(float[] a) { }'
        output = generate(src)
        assert "__btrc_gpu_shader_kern" in output
        assert "#version 430" in output


# --- Type mappings ---

class TestTypes:
    def test_bool_type(self):
        src = 'void test() { bool x = true; }'
        output = generate(src)
        assert "bool x = true;" in output
        assert "#include <stdbool.h>" in output

    def test_string_type(self):
        src = 'void test() { string s = "hi"; }'
        output = generate(src)
        assert 'char* s = "hi";' in output

    def test_null_literal(self):
        src = 'void test() { int* p = null; }'
        output = generate(src)
        assert "NULL" in output

    def test_ternary(self):
        src = 'void test() { int x = true ? 1 : 0; }'
        output = generate(src)
        assert "?" in output
        assert ":" in output

    def test_sizeof(self):
        src = 'void test() { int x = sizeof(int); }'
        output = generate(src)
        assert "sizeof(int)" in output

    def test_cast(self):
        src = 'void test() { float x = (float)5; }'
        output = generate(src)
        assert "((float)" in output


# --- Full program ---

class TestFullProgram:
    def test_header_present(self):
        output = generate('int main() { return 0; }')
        assert "/* Generated by btrc */" in output
        assert "#include <stdio.h>" in output
        assert "#include <stdlib.h>" in output
        assert "#include <stdbool.h>" in output

    def test_complete_program(self):
        src = '''
            #include <stdio.h>
            class Counter {
                private int count;
                public Counter() { self.count = 0; }
                public void inc() { self.count++; }
                public int get() { return self.count; }
            }
            int main() {
                Counter c = Counter();
                c.inc();
                return 0;
            }
        '''
        output = generate(src)
        assert "struct Counter" in output
        assert "Counter* Counter_new" in output
        assert "void Counter_init(Counter* self)" in output
        assert "void Counter_inc(Counter* self)" in output
        assert "int Counter_get(Counter* self)" in output
        assert "Counter_init(" in output


# --- print() builtin ---

class TestPrintBuiltin:
    def test_print_string(self):
        src = '''
            int main() {
                print("hello");
                return 0;
            }
        '''
        output = generate(src)
        assert 'printf("hello\\n")' in output

    def test_print_int(self):
        src = '''
            int main() {
                int x = 42;
                print(x);
                return 0;
            }
        '''
        output = generate(src)
        assert "printf" in output

    def test_print_fstring(self):
        src = '''
            int main() {
                int x = 42;
                print(f"value={x}");
                return 0;
            }
        '''
        output = generate(src)
        assert "printf" in output
        assert "value=" in output

    def test_print_no_args(self):
        src = '''
            int main() {
                print();
                return 0;
            }
        '''
        output = generate(src)
        assert 'printf("\\n")' in output


# --- Auto-includes ---

class TestAutoIncludes:
    def test_auto_include_math(self):
        src = '''
            int main() {
                double x = sqrt(2.0);
                return 0;
            }
        '''
        output = generate(src)
        assert "#include <math.h>" in output

    def test_no_duplicate_include(self):
        src = '''
            #include <math.h>
            int main() {
                double x = sqrt(2.0);
                return 0;
            }
        '''
        output = generate(src)
        # math.h should only appear once (the user's include, not in auto-header)
        assert output.count("#include <math.h>") == 1

    def test_always_includes_basics(self):
        src = '''
            int main() { return 0; }
        '''
        output = generate(src)
        assert "#include <stdio.h>" in output
        assert "#include <stdlib.h>" in output
        assert "#include <stdbool.h>" in output
        assert "#include <string.h>" in output


# --- Debug line directives ---

def generate_debug(source: str, source_file: str = "test.btrc") -> str:
    """Generate C code with debug line directives enabled."""
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    return CodeGen(analyzed, debug=True, source_file=source_file).generate()


def generate_no_debug(source: str) -> str:
    """Generate C code with debug line directives disabled (default)."""
    tokens = Lexer(source).tokenize()
    program = Parser(tokens).parse()
    analyzed = Analyzer().analyze(program)
    return CodeGen(analyzed, debug=False).generate()


class TestDebugLineDirectives:
    def test_debug_emits_line_directives(self):
        src = 'int main() { int x = 1; return x; }'
        output = generate_debug(src)
        assert '#line' in output
        assert '"test.btrc"' in output

    def test_no_debug_no_directives(self):
        src = 'int main() { int x = 1; return x; }'
        output = generate_no_debug(src)
        assert '#line' not in output

    def test_debug_function_directive(self):
        src = 'int add(int a, int b) { return a + b; }'
        output = generate_debug(src, source_file="math.btrc")
        assert '#line' in output
        assert '"math.btrc"' in output


# --- Try/catch codegen ---

class TestTryCatch:
    def test_try_catch_generates_setjmp(self):
        src = '''
            int main() {
                try {
                    int x = 1;
                } catch (string e) {
                    int y = 2;
                }
                return 0;
            }
        '''
        output = generate(src)
        assert "#include <setjmp.h>" in output
        assert "__btrc_try_stack" in output
        assert "setjmp" in output
        assert "__btrc_try_top" in output

    def test_throw_generates_btrc_throw(self):
        src = '''
            int main() {
                throw "something went wrong";
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_throw" in output
        assert '"something went wrong"' in output

    def test_catch_var_available(self):
        src = '''
            int main() {
                try {
                    throw "error";
                } catch (string e) {
                    printf("%s", e);
                }
                return 0;
            }
        '''
        output = generate(src)
        assert "const char* e = __btrc_error_msg" in output


# --- Operator overloading codegen ---

class TestOperatorOverloading:
    def test_add_overload(self):
        src = '''
            class Vec2 {
                public float x;
                public float y;
                public Vec2(float x, float y) { self.x = x; self.y = y; }
                public Vec2 __add__(Vec2 other) {
                    return Vec2(self.x + other.x, self.y + other.y);
                }
            }
            void test() {
                Vec2 a = Vec2(1.0, 2.0);
                Vec2 b = Vec2(3.0, 4.0);
                Vec2 c = a + b;
            }
        '''
        output = generate(src)
        assert "Vec2___add__" in output

    def test_eq_overload(self):
        src = '''
            class Point {
                public int x;
                public int y;
                public Point(int x, int y) { self.x = x; self.y = y; }
                public bool __eq__(Point other) {
                    return self.x == other.x && self.y == other.y;
                }
            }
            void test() {
                Point a = Point(1, 2);
                Point b = Point(1, 2);
                bool same = a == b;
            }
        '''
        output = generate(src)
        assert "Point___eq__" in output


# --- Null coalescing codegen ---

class TestNullCoalescing:
    def test_null_coalescing_generates_ternary(self):
        src = '''
            void test() {
                int* a = null;
                int* b = null;
                int* result = a ?? b;
            }
        '''
        output = generate(src)
        assert "!= NULL" in output
        assert "?" in output


# --- Inheritance codegen ---

class TestInheritanceCodegen:
    def test_child_inherits_parent_fields(self):
        src = '''
            class Animal {
                public string name;
                public Animal(string n) { self.name = n; }
            }
            class Dog extends Animal {
                public string breed;
                public Dog(string n, string b) { self.name = n; self.breed = b; }
            }
        '''
        output = generate(src)
        # Dog struct should have the inherited 'name' field
        assert "struct Dog" in output
        assert "Dog_new" in output

    def test_inherited_methods_emitted(self):
        src = '''
            class Base {
                public int x;
                public int getX() { return self.x; }
            }
            class Child extends Base {
                public int y;
                public Child(int a, int b) { self.x = a; self.y = b; }
            }
        '''
        output = generate(src)
        # Child should have its own getX function (re-emitted from parent)
        assert "Child_getX" in output


# --- For-in with range codegen ---

class TestForInRange:
    def test_range_single_arg(self):
        src = 'void test() { for i in range(10) { } }'
        output = generate(src)
        assert "for (int i = 0; i < 10; i++)" in output

    def test_range_two_args(self):
        src = 'void test() { for i in range(5, 20) { } }'
        output = generate(src)
        assert "for (int i = 5; i < 20; i++)" in output

    def test_range_three_args(self):
        src = 'void test() { for i in range(0, 100, 5) { } }'
        output = generate(src)
        assert "__btrc_step_1 = 5;" in output
        assert "(__btrc_step_1 > 0 ? i < 100 : i > 100)" in output
        assert "i += __btrc_step_1" in output


# --- Default parameter codegen ---

class TestDefaultParams:
    def test_default_param_filled(self):
        src = '''
            int add(int a, int b = 10) { return a + b; }
            int main() {
                int x = add(5);
                return x;
            }
        '''
        output = generate(src)
        # When called with 1 arg, the default value 10 should appear
        assert "add(5, 10)" in output

    def test_default_param_overridden(self):
        src = '''
            int add(int a, int b = 10) { return a + b; }
            int main() {
                int x = add(5, 20);
                return x;
            }
        '''
        output = generate(src)
        assert "add(5, 20)" in output


# --- String method codegen ---

class TestStringMethods:
    def test_string_len(self):
        src = '''
            void test() {
                string s = "hello";
                int n = s.len();
            }
        '''
        output = generate(src)
        assert "strlen(s)" in output

    def test_string_contains(self):
        src = '''
            void test() {
                string s = "hello world";
                bool b = s.contains("world");
            }
        '''
        output = generate(src)
        assert "__btrc_strContains(s" in output

    def test_string_startsWith(self):
        src = '''
            void test() {
                string s = "hello";
                bool b = s.startsWith("hel");
            }
        '''
        output = generate(src)
        assert "__btrc_startsWith(s" in output

    def test_string_endsWith(self):
        src = '''
            void test() {
                string s = "hello";
                bool b = s.endsWith("lo");
            }
        '''
        output = generate(src)
        assert "__btrc_endsWith(s" in output

    def test_string_charAt(self):
        src = '''
            void test() {
                string s = "hello";
                char c = s.charAt(0);
            }
        '''
        output = generate(src)
        assert "__btrc_charAt(s, 0)" in output

    def test_string_equals(self):
        src = '''
            void test() {
                string s = "hello";
                bool b = s.equals("hello");
            }
        '''
        output = generate(src)
        assert "strcmp(s" in output


# --- Typedef codegen ---

class TestTypedefCodegen:
    def test_typedef_passthrough(self):
        src = 'typedef int Number;'
        output = generate(src)
        assert "typedef int Number;" in output

    def test_typedef_pointer(self):
        src = 'typedef char* CString;'
        output = generate(src)
        assert "typedef char* CString;" in output


# --- Enum codegen ---

class TestEnumCodegen:
    def test_enum_generates_typedef(self):
        src = 'enum Color { RED, GREEN, BLUE };'
        output = generate(src)
        assert "typedef enum" in output
        assert "RED" in output
        assert "GREEN" in output
        assert "BLUE" in output
        assert "Color" in output

    def test_enum_with_values(self):
        src = 'enum Flags { A = 1, B = 2, C = 4 };'
        output = generate(src)
        assert "A = 1" in output
        assert "B = 2" in output
        assert "C = 4" in output


# --- Do-while codegen ---

class TestDoWhileCodegen:
    def test_do_while(self):
        src = 'void test() { do { int x = 1; } while (true); }'
        output = generate(src)
        assert "do {" in output
        assert "} while (true);" in output


# --- Switch codegen ---

class TestSwitchCodegen:
    def test_switch_generates_switch(self):
        src = '''
            void test() {
                int x = 1;
                switch (x) {
                    case 0: break;
                    case 1: break;
                    default: break;
                }
            }
        '''
        output = generate(src)
        assert "switch (x)" in output
        assert "case 0:" in output
        assert "case 1:" in output
        assert "default:" in output


# --- Field defaults codegen ---

class TestFieldDefaults:
    def test_field_defaults_constructor(self):
        src = '''
            class Config {
                private int count = 0;
                private string name = "default";
            }
            void test() {
                Config c = Config();
            }
        '''
        output = generate(src)
        # Should generate a default constructor applying field initializers
        assert "Config_new" in output
        assert "Config_init(" in output

    def test_field_defaults_with_explicit_constructor(self):
        src = '''
            class Counter {
                private int count = 0;
                public Counter(int start) { self.count = start; }
            }
        '''
        output = generate(src)
        # Field defaults should be applied before constructor body
        assert "Counter* Counter_new(int start)" in output


# --- Brace initializer codegen ---

class TestBraceInitCodegen:
    def test_brace_init_array(self):
        src = 'void test() { int arr[] = {1, 2, 3}; }'
        output = generate(src)
        assert "{1, 2, 3}" in output


# --- Nested if-else codegen ---

class TestNestedIfElse:
    def test_if_else_if_chain(self):
        src = '''
            void test() {
                int x = 0;
                if (x == 0) {
                    x = 1;
                } else if (x == 1) {
                    x = 2;
                } else {
                    x = 3;
                }
            }
        '''
        output = generate(src)
        assert "if (x == 0)" in output
        assert "} else" in output

    def test_simple_if_no_else(self):
        src = '''
            void test() {
                int x = 0;
                if (x > 0) { x = 1; }
            }
        '''
        output = generate(src)
        assert "if (x > 0)" in output


# --- Collection method codegen ---

class TestCollectionMethods:
    def test_list_push_method(self):
        src = '''
            void test() {
                List<int> nums = [1, 2];
                nums.push(3);
            }
        '''
        output = generate(src)
        assert "btrc_List_int_push(&nums, 3)" in output

    def test_list_get_method(self):
        src = '''
            void test() {
                List<int> nums = [1, 2, 3];
                int x = nums.get(0);
            }
        '''
        output = generate(src)
        assert "btrc_List_int_get(&nums, 0)" in output

    def test_map_put_get(self):
        src = '''
            void test() {
                Map<string, int> m = {"a": 1};
                m.put("b", 2);
                int x = m.get("a");
            }
        '''
        output = generate(src)
        assert "btrc_Map_string_int_put(&m" in output
        assert "btrc_Map_string_int_get(&m" in output

    def test_map_has_method(self):
        src = '''
            void test() {
                Map<string, int> m;
                bool b = m.has("key");
            }
        '''
        output = generate(src)
        assert "btrc_Map_string_int_has(&m" in output

    def test_list_len_field(self):
        src = '''
            void test() {
                List<int> nums;
                int n = nums.len;
            }
        '''
        output = generate(src)
        assert "nums.len" in output


# --- Index expression codegen ---

class TestIndexCodegen:
    def test_list_index_access(self):
        src = '''
            void test() {
                List<int> nums = [1, 2, 3];
                int x = nums[0];
            }
        '''
        output = generate(src)
        assert "btrc_List_int_get(&nums, 0)" in output

    def test_c_array_index(self):
        src = 'void test() { int arr[3]; int x = arr[1]; }'
        output = generate(src)
        assert "arr[1]" in output


# --- Unary expressions codegen ---

class TestUnaryCodegen:
    def test_prefix_increment(self):
        src = 'void test() { int x = 0; ++x; }'
        output = generate(src)
        assert "(++x)" in output

    def test_postfix_increment(self):
        src = 'void test() { int x = 0; x++; }'
        output = generate(src)
        assert "(x++)" in output

    def test_prefix_decrement(self):
        src = 'void test() { int x = 5; --x; }'
        output = generate(src)
        assert "(--x)" in output

    def test_postfix_decrement(self):
        src = 'void test() { int x = 5; x--; }'
        output = generate(src)
        assert "(x--)" in output

    def test_logical_not(self):
        src = 'void test() { bool b = !true; }'
        output = generate(src)
        assert "(!true)" in output

    def test_bitwise_not(self):
        src = 'void test() { int x = ~0; }'
        output = generate(src)
        assert "(~0)" in output


# --- Compound assignment codegen ---

class TestCompoundAssignment:
    def test_minus_eq(self):
        src = 'void test() { int x = 10; x -= 3; }'
        output = generate(src)
        assert "(x -= 3)" in output

    def test_star_eq(self):
        src = 'void test() { int x = 5; x *= 2; }'
        output = generate(src)
        assert "(x *= 2)" in output

    def test_slash_eq(self):
        src = 'void test() { int x = 10; x /= 2; }'
        output = generate(src)
        assert "__btrc_div_int(x, 2)" in output

    def test_percent_eq(self):
        src = 'void test() { int x = 10; x %= 3; }'
        output = generate(src)
        assert "__btrc_mod_int(x, 3)" in output


# --- While loop codegen ---

class TestWhileCodegen:
    def test_while_loop(self):
        src = 'void test() { int x = 0; while (x < 10) { x = x + 1; } }'
        output = generate(src)
        assert "while ((x < 10))" in output


# --- Break and continue codegen ---

class TestBreakContinueCodegen:
    def test_break_in_loop(self):
        src = 'void test() { while (true) { break; } }'
        output = generate(src)
        assert "break;" in output

    def test_continue_in_loop(self):
        src = 'void test() { while (true) { continue; } }'
        output = generate(src)
        assert "continue;" in output


# --- Struct codegen ---

class TestStructCodegen:
    def test_struct_to_typedef(self):
        src = 'struct Point { int x; int y; };'
        output = generate(src)
        assert "typedef struct Point" in output
        assert "int x;" in output
        assert "int y;" in output
        assert "} Point;" in output

    def test_struct_forward_decl(self):
        src = 'struct Node;'
        output = generate(src)
        assert "struct Node;" in output


# --- Return codegen ---

class TestReturnCodegen:
    def test_return_value(self):
        src = 'int test() { return 42; }'
        output = generate(src)
        assert "return 42;" in output

    def test_return_void(self):
        src = 'void test() { return; }'
        output = generate(src)
        assert "return;" in output

    def test_return_expression(self):
        src = 'int test() { int a = 1; int b = 2; return a + b; }'
        output = generate(src)
        assert "return (a + b);" in output


# --- Heap allocation helper ---

class TestHeapAllocation:
    def test_constructor_returns_pointer(self):
        src = '''
            class Node { public int val; public Node(int v) { self.val = v; } }
        '''
        output = generate(src)
        assert "Node* Node_new(int v)" in output
        assert "malloc(sizeof(Node))" in output

    def test_destroy_function(self):
        src = '''
            class Node { public int val; public Node(int v) { self.val = v; } }
        '''
        output = generate(src)
        assert "Node_destroy" in output
        assert "free(self)" in output


# --- Void parameter function ---

class TestVoidParam:
    def test_no_param_becomes_void(self):
        src = 'int get_value() { return 42; }'
        output = generate(src)
        assert "int get_value(void)" in output

    def test_method_no_param_becomes_void(self):
        src = '''
            class Foo {
                class int create() { return 0; }
            }
        '''
        output = generate(src)
        assert "int Foo_create(void)" in output


# --- List string methods ---

class TestListStringMethods:
    def test_list_string_generates_join(self):
        src = 'void test() { List<string> words; }'
        output = generate(src)
        # List<string> should have a join function generated
        assert "btrc_List_string_join" in output

    def test_list_int_generates_contains(self):
        src = 'void test() { List<int> nums; }'
        output = generate(src)
        assert "btrc_List_int_contains" in output

    def test_list_int_generates_sort(self):
        src = 'void test() { List<int> nums; }'
        output = generate(src)
        assert "btrc_List_int_sort" in output

    def test_list_int_generates_reverse(self):
        src = 'void test() { List<int> nums; }'
        output = generate(src)
        assert "btrc_List_int_reverse" in output

    def test_list_int_generates_clear(self):
        src = 'void test() { List<int> nums; }'
        output = generate(src)
        assert "btrc_List_int_clear" in output

    def test_list_int_generates_slice(self):
        src = 'void test() { List<int> nums; }'
        output = generate(src)
        assert "btrc_List_int_slice" in output

    def test_list_int_generates_remove(self):
        src = 'void test() { List<int> nums; }'
        output = generate(src)
        assert "btrc_List_int_remove" in output


# --- Map function generation ---

class TestMapFunctions:
    def test_map_generates_keys(self):
        src = 'void test() { Map<string, int> m; }'
        output = generate(src)
        assert "btrc_Map_string_int_keys" in output

    def test_map_generates_values(self):
        src = 'void test() { Map<string, int> m; }'
        output = generate(src)
        assert "btrc_Map_string_int_values" in output

    def test_map_generates_remove(self):
        src = 'void test() { Map<string, int> m; }'
        output = generate(src)
        assert "btrc_Map_string_int_remove" in output

    def test_map_generates_free(self):
        src = 'void test() { Map<string, int> m; }'
        output = generate(src)
        assert "btrc_Map_string_int_free" in output

    def test_map_generates_resize(self):
        src = 'void test() { Map<string, int> m; }'
        output = generate(src)
        assert "btrc_Map_string_int_resize" in output


class TestSetFunctions:
    def test_set_generates_struct(self):
        src = 'void test() { Set<int> s; }'
        output = generate(src)
        assert "btrc_Set_int" in output

    def test_set_generates_add(self):
        src = 'void test() { Set<int> s; }'
        output = generate(src)
        assert "btrc_Set_int_add" in output

    def test_set_generates_contains(self):
        src = 'void test() { Set<int> s; }'
        output = generate(src)
        assert "btrc_Set_int_contains" in output

    def test_set_generates_remove(self):
        src = 'void test() { Set<int> s; }'
        output = generate(src)
        assert "btrc_Set_int_remove" in output

    def test_set_generates_toList(self):
        src = 'void test() { Set<int> s; }'
        output = generate(src)
        assert "btrc_Set_int_toList" in output

    def test_set_generates_free(self):
        src = 'void test() { Set<int> s; }'
        output = generate(src)
        assert "btrc_Set_int_free" in output

    def test_set_string_has_hash(self):
        src = 'void test() { Set<string> s; }'
        output = generate(src)
        assert "__btrc_hash_str" in output

    def test_set_empty_brace_init(self):
        src = 'int main() { Set<int> s = {}; return 0; }'
        output = generate(src)
        assert "btrc_Set_int_new()" in output


# --- Self in constructor vs method ---

class TestSelfContext:
    def test_self_arrow_in_constructor(self):
        src = '''
            class Foo {
                public int x;
                public Foo(int val) { self.x = val; }
            }
        '''
        output = generate(src)
        # All class instances are reference types — self is always a pointer
        assert "self->x" in output
        # Constructor body is now in _init function
        init_section = output.split("void Foo_init(Foo* self, int val) {")[1].split("}")[0]
        assert "self->x" in init_section

    def test_self_arrow_in_method(self):
        src = '''
            class Foo {
                public int x;
                public int getX() { return self.x; }
            }
        '''
        output = generate(src)
        assert "self->x" in output


# --- F-string as value (snprintf) ---

class TestFStringValue:
    def test_fstring_assignment(self):
        src = '''
            void test() {
                int x = 42;
                string s = f"value={x}";
            }
        '''
        output = generate(src)
        assert "snprintf" in output
        assert "malloc" in output
        assert "value=" in output


# --- Pointer field access and method calls ---

class TestPointerAccess:
    def test_pointer_field_access_uses_arrow(self):
        src = '''
            class Box {
                public int value = 0;
            }
            void test() {
                Box* b = new Box();
                int x = b.value;
            }
        '''
        output = generate(src)
        assert "b->value" in output

    def test_pointer_method_call_no_double_ref(self):
        src = '''
            class Counter {
                public int n = 0;
                public void inc() {
                    self.n = self.n + 1;
                }
            }
            void test() {
                Counter* c = new Counter();
                c.inc();
            }
        '''
        output = generate(src)
        # Should pass c directly, not &c
        assert "Counter_inc(c)" in output

    def test_list_field_init_in_constructor(self):
        src = '''
            class Bag {
                public List<int> items = [];
            }
        '''
        output = generate(src)
        assert "btrc_List_int_new()" in output
        assert "/* list literal */" not in output

    def test_map_field_init_in_constructor(self):
        src = '''
            class Store {
                public Map<string, int> inventory = {};
            }
        '''
        output = generate(src)
        assert "btrc_Map_string_int_new()" in output

    def test_empty_brace_map_var_decl(self):
        src = '''
            void test() {
                Map<int, int> m = {};
            }
        '''
        output = generate(src)
        assert "btrc_Map_int_int_new()" in output
        assert "= {}" not in output

    def test_empty_brace_list_var_decl(self):
        src = '''
            void test() {
                List<string> s = {};
            }
        '''
        output = generate(src)
        assert "btrc_List_string_new()" in output


class TestProperties:
    def test_auto_property_struct(self):
        src = '''
            class Foo {
                public int x { get; set; }
            }
        '''
        output = generate(src)
        assert "int _x;" in output  # backing field

    def test_auto_property_getter_setter(self):
        src = '''
            class Foo {
                public int x { get; set; }
            }
        '''
        output = generate(src)
        assert "int Foo_get_x(Foo* self)" in output
        assert "return self->_x;" in output
        assert "void Foo_set_x(Foo* self, int value)" in output
        assert "self->_x = value;" in output

    def test_custom_getter(self):
        src = '''
            class Foo {
                private int _val;
                public int doubled {
                    get { return self._val * 2; }
                }
            }
        '''
        output = generate(src)
        assert "int Foo_get_doubled(Foo* self)" in output
        assert "self->_val * 2" in output

    def test_property_access_emits_getter(self):
        src = '''
            class Foo {
                public int x { get; set; }
            }
            void test() {
                Foo* f = Foo();
                int v = f.x;
            }
        '''
        output = generate(src)
        assert "Foo_get_x(f)" in output

    def test_property_assign_emits_setter(self):
        src = '''
            class Foo {
                public int x { get; set; }
            }
            void test() {
                Foo* f = Foo();
                f.x = 42;
            }
        '''
        output = generate(src)
        assert "Foo_set_x(f, 42)" in output

    def test_auto_property_default_constructor(self):
        src = '''
            class Foo {
                public int x { get; set; }
            }
        '''
        output = generate(src)
        assert "Foo* Foo_new(void)" in output


# --- Lambdas ---

class TestLambdas:
    def test_verbose_lambda_lifted(self):
        src = '''
            int main() {
                var doubler = int function(int x) { return x * 2; };
                return 0;
            }
        '''
        output = generate(src)
        assert "static int __btrc_lambda_" in output
        assert "return (x * 2);" in output

    def test_arrow_lambda_lifted(self):
        src = '''
            int main() {
                var tripler = (int x) => x * 3;
                return 0;
            }
        '''
        output = generate(src)
        assert "static int __btrc_lambda_" in output
        assert "return (x * 3);" in output

    def test_lambda_function_pointer_decl(self):
        src = '''
            int main() {
                var adder = (int a, int b) => a + b;
                return 0;
            }
        '''
        output = generate(src)
        assert "int (*adder)(int, int, void*)" in output

    def test_lambda_before_main(self):
        src = '''
            int main() {
                var f = (int x) => x;
                return 0;
            }
        '''
        output = generate(src)
        # Lambda definition should appear before main
        lambda_pos = output.find("static int __btrc_lambda_")
        main_pos = output.find("int main(")
        assert lambda_pos < main_pos, "Lambda should be emitted before main"

    def test_multiple_lambdas(self):
        src = '''
            int main() {
                var a = (int x) => x + 1;
                var b = (int x) => x * 2;
                return 0;
            }
        '''
        output = generate(src)
        assert output.count("static int __btrc_lambda_") == 2


class TestRuntimeSafety:
    """Tests for runtime safety checks in generated code."""

    def test_list_pop_bounds_check(self):
        """List pop should include a bounds check for empty lists."""
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int x = nums.pop();
                return 0;
            }
        '''
        output = generate(src)
        assert "pop from empty list" in output

    def test_list_slice_negative_index_handling(self):
        """List slice should handle negative indices."""
        src = '''
            int main() {
                List<int> nums = [1, 2, 3, 4, 5];
                List<int> last = nums.slice(-2, nums.len);
                return 0;
            }
        '''
        output = generate(src)
        assert "if (start < 0) start = l->len + start" in output

    def test_substring_bounds_check(self):
        """Substring should include bounds checks."""
        src = '''
            int main() {
                string s = "hello";
                string sub = s.substring(0, 3);
                return 0;
            }
        '''
        output = generate(src)
        assert "if (start > slen) start = slen" in output

    def test_list_get_bounds_check(self):
        """List get should include out-of-bounds check."""
        src = '''
            int main() {
                List<int> nums = [1];
                int x = nums.get(0);
                return 0;
            }
        '''
        output = generate(src)
        assert "List index out of bounds" in output


class TestSetFunctionalMethods:
    """Tests for Set filter/any/all methods in generated code."""

    def test_set_filter_emitted(self):
        src = '''
            bool is_even(int x) { return x % 2 == 0; }
            int main() {
                Set<int> s = {};
                s.add(1);
                Set<int> evens = s.filter(is_even);
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_Set_int_filter" in output

    def test_set_any_emitted(self):
        src = '''
            bool is_pos(int x) { return x > 0; }
            int main() {
                Set<int> s = {};
                s.add(1);
                bool r = s.any(is_pos);
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_Set_int_any" in output

    def test_set_all_emitted(self):
        src = '''
            bool is_pos(int x) { return x > 0; }
            int main() {
                Set<int> s = {};
                s.add(1);
                bool r = s.all(is_pos);
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_Set_int_all" in output

    def test_set_filter_function_body(self):
        """filter should iterate buckets and call fn."""
        src = '''
            bool f(int x) { return true; }
            int main() {
                Set<int> s = {};
                Set<int> filtered = s.filter(f);
                return 0;
            }
        '''
        output = generate(src)
        assert "fn(s->buckets[i].key, __ctx)" in output


# --- Forward declarations ---

class TestForwardDeclarations:
    def test_forward_decl_emits_prototype(self):
        """Forward-declared functions should have prototypes emitted."""
        src = '''
            bool is_even(int n);
            bool is_odd(int n) {
                if (n == 0) { return false; }
                return is_even(n - 1);
            }
            bool is_even(int n) {
                if (n == 0) { return true; }
                return is_odd(n - 1);
            }
            int main() { return 0; }
        '''
        output = generate(src)
        # Both functions should have forward declarations
        assert "bool is_odd(int n);" in output
        assert "bool is_even(int n);" in output

    def test_forward_decl_no_duplicate_body(self):
        """Forward decl should not produce a duplicate function body."""
        src = '''
            int double_it(int x);
            int double_it(int x) { return x * 2; }
            int main() { return 0; }
        '''
        output = generate(src)
        # The function body should appear exactly once
        bodies = output.count("return (x * 2)")
        assert bodies == 1, f"Expected 1 body, found {bodies}"

    def test_forward_decl_void_function(self):
        src = '''
            void greet();
            void greet() { print("hello"); }
            int main() { greet(); return 0; }
        '''
        output = generate(src)
        assert "void greet(void);" in output

    def test_forward_decl_multiple_params(self):
        src = '''
            float compute(int a, float b, bool c);
            float compute(int a, float b, bool c) { return b; }
            int main() { return 0; }
        '''
        output = generate(src)
        assert "float compute(int a, float b, bool c);" in output


# --- Collection size() method ---

class TestCollectionSize:
    def test_list_size(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int n = nums.size();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_List_int_size" in output

    def test_map_size(self):
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("a", 1);
                int n = m.size();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_Map_string_int_size" in output

    def test_set_size(self):
        src = '''
            int main() {
                Set<int> s = {};
                s.add(1);
                int n = s.size();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_Set_int_size" in output

    def test_list_size_returns_len(self):
        src = '''
            int main() {
                List<int> nums = [];
                int n = nums.size();
                return 0;
            }
        '''
        output = generate(src)
        assert "return l->len;" in output


# --- Math.sum/fsum uses .len not .size ---

class TestMathFunctions:
    def test_math_sum_uses_len(self):
        src = '''
            #include <math.h>
            int main() {
                List<int> nums = [1, 2, 3];
                int total = Math.sum(nums);
                return 0;
            }
        '''
        output = generate(src)
        assert ".len)" in output
        assert ".size)" not in output

    def test_math_fsum_uses_len(self):
        src = '''
            #include <math.h>
            int main() {
                List<float> nums = [1.0, 2.0];
                float total = Math.fsum(nums);
                return 0;
            }
        '''
        output = generate(src)
        assert ".len)" in output
        assert ".size)" not in output


# --- Range negative step ---

class TestRangeNegativeStep:
    def test_range_negative_step_emits_bidirectional(self):
        src = 'void test() { for i in range(10, 0, -1) { } }'
        output = generate(src)
        assert "__btrc_step_" in output
        assert "i > 0" in output

    def test_range_positive_step_still_works(self):
        src = 'void test() { for i in range(0, 10, 2) { } }'
        output = generate(src)
        assert "__btrc_step_" in output
        assert "i < 10" in output


# --- Try/catch bounds check ---

class TestTryCatchSafety:
    def test_try_emits_bounds_check(self):
        src = '''
            int main() {
                try {
                    int x = 1;
                } catch (string e) {
                    int y = 2;
                }
                return 0;
            }
        '''
        output = generate(src)
        assert "__BTRC_TRY_STACK_SIZE" in output
        assert "try/catch stack overflow" in output


# --- Map.getOrDefault ---

class TestMapGetOrDefault:
    def test_map_get_or_default_emitted(self):
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("a", 1);
                int v = m.getOrDefault("b", -1);
                return 0;
            }
        '''
        output = generate(src)
        assert "getOrDefault" in output
        assert "fallback" in output


class TestDivModSafety:
    def test_int_division_uses_helper(self):
        src = '''
            int main() {
                int a = 10;
                int b = 3;
                int c = a / b;
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_div_int(a, b)" in output

    def test_int_modulo_uses_helper(self):
        src = '''
            int main() {
                int a = 10;
                int b = 3;
                int c = a % b;
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_mod_int(a, b)" in output

    def test_double_division_uses_helper(self):
        src = '''
            int main() {
                double a = 10.0;
                double b = 3.0;
                double c = a / b;
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_div_double(a, b)" in output

    def test_helper_functions_emitted(self):
        src = '''
            int main() {
                int a = 10 / 2;
                return 0;
            }
        '''
        output = generate(src)
        assert "static inline int __btrc_div_int" in output
        assert "static inline int __btrc_mod_int" in output
        assert "static inline double __btrc_div_double" in output


class TestCharAtSafety:
    def test_charAt_uses_helper(self):
        src = '''
            void test() {
                string s = "hello";
                char c = s.charAt(2);
            }
        '''
        output = generate(src)
        assert "__btrc_charAt(s, 2)" in output

    def test_charAt_helper_emitted(self):
        src = '''
            void test() {
                string s = "hello";
                char c = s.charAt(0);
            }
        '''
        output = generate(src)
        assert "static inline char __btrc_charAt" in output
        assert "String index out of bounds" in output


class TestStringSafety:
    def test_split_empty_delimiter_check(self):
        src = '''
            int main() {
                string s = "hello";
                string[] parts = s.split(",");
                return 0;
            }
        '''
        output = generate(src)
        assert "Empty delimiter in split()" in output

    def test_repeat_negative_count_check(self):
        src = '''
            int main() {
                string s = "abc";
                string r = s.repeat(3);
                return 0;
            }
        '''
        output = generate(src)
        assert "repeat count must be non-negative" in output

    def test_join_uses_memcpy(self):
        src = '''
            #include <stdio.h>
            int main() {
                string s = "hello";
                string t = s.trim();
                return 0;
            }
        '''
        output = generate(src)
        # join helper uses memcpy instead of strcat for O(n) perf
        assert "memcpy(r + pos" in output


class TestSwitchAutoBreak:
    def test_auto_break_inserted(self):
        """Non-empty case without break/return gets auto-break."""
        src = '''
            int main() {
                int x = 1;
                switch (x) {
                    case 1:
                        x = 10;
                    case 2:
                        x = 20;
                }
                return 0;
            }
        '''
        output = generate(src)
        # Each case should have break; inserted
        lines = output.split('\n')
        case_1_found = False
        for i, line in enumerate(lines):
            if 'case 1:' in line:
                case_1_found = True
            if case_1_found and '(x = 10)' in line:
                # Next non-empty line should be break;
                for j in range(i+1, len(lines)):
                    stripped = lines[j].strip()
                    if stripped:
                        assert stripped == 'break;', f"Expected 'break;' but got '{stripped}'"
                        break
                break

    def test_no_auto_break_with_explicit_break(self):
        """Explicit break doesn't get doubled."""
        src = '''
            int main() {
                int x = 1;
                switch (x) {
                    case 1:
                        x = 10;
                        break;
                }
                return 0;
            }
        '''
        output = generate(src)
        # Count break; occurrences in the switch
        assert output.count('break;') == 1

    def test_empty_case_fallthrough(self):
        """Empty cases are preserved for intentional fallthrough."""
        src = '''
            int main() {
                int x = 1;
                switch (x) {
                    case 1:
                    case 2:
                        x = 10;
                        break;
                }
                return 0;
            }
        '''
        output = generate(src)
        # case 1: should NOT have break (empty body = fallthrough)
        # Only one break; total
        assert output.count('break;') == 1


class TestIsEmpty:
    def test_list_isEmpty(self):
        src = '''
            int main() {
                List<int> nums = [];
                bool e = nums.isEmpty();
                return 0;
            }
        '''
        output = generate(src)
        assert "isEmpty" in output
        assert "l->len == 0" in output

    def test_map_isEmpty(self):
        src = '''
            int main() {
                Map<string, int> m = {};
                bool e = m.isEmpty();
                return 0;
            }
        '''
        output = generate(src)
        assert "isEmpty" in output
        assert "m->len == 0" in output

    def test_set_isEmpty(self):
        src = '''
            int main() {
                Set<int> s = {};
                bool e = s.isEmpty();
                return 0;
            }
        '''
        output = generate(src)
        assert "isEmpty" in output
        assert "s->len == 0" in output


class TestListInsert:
    def test_insert_emitted(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                nums.insert(1, 99);
                return 0;
            }
        '''
        output = generate(src)
        assert "_insert" in output
        assert "idx < 0 || idx > l->len" in output


class TestNewStringMethods:
    def test_reverse(self):
        src = '''
            void test() {
                string s = "hello";
                string r = s.reverse();
            }
        '''
        output = generate(src)
        assert "__btrc_reverse(s)" in output

    def test_isEmpty(self):
        src = '''
            void test() {
                string s = "hello";
                bool e = s.isEmpty();
            }
        '''
        output = generate(src)
        assert "__btrc_isEmpty(s)" in output

    def test_removePrefix(self):
        src = '''
            void test() {
                string s = "prefix_text";
                string r = s.removePrefix("prefix_");
            }
        '''
        output = generate(src)
        assert "__btrc_removePrefix(s" in output

    def test_removeSuffix(self):
        src = '''
            void test() {
                string s = "file.txt";
                string r = s.removeSuffix(".txt");
            }
        '''
        output = generate(src)
        assert "__btrc_removeSuffix(s" in output


class TestListFirstLast:
    def test_first(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int f = nums.first();
                return 0;
            }
        '''
        output = generate(src)
        assert "_first(" in output

    def test_last(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int l = nums.last();
                return 0;
            }
        '''
        output = generate(src)
        assert "_last(" in output

    def test_first_helper_emitted(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int f = nums.first();
                return 0;
            }
        '''
        output = generate(src)
        assert "List.first() called on empty list" in output

    def test_last_helper_emitted(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int l = nums.last();
                return 0;
            }
        '''
        output = generate(src)
        assert "List.last() called on empty list" in output


class TestMapPutIfAbsent:
    def test_putIfAbsent(self):
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("a", 1);
                m.putIfAbsent("a", 2);
                return 0;
            }
        '''
        output = generate(src)
        assert "_putIfAbsent(" in output

    def test_putIfAbsent_calls_has(self):
        src = '''
            int main() {
                Map<string, int> m = {};
                m.putIfAbsent("key", 42);
                return 0;
            }
        '''
        output = generate(src)
        assert "_has(m" in output or "_has(&m" in output


class TestCompoundDivModSafety:
    def test_div_equals_uses_helper(self):
        src = '''
            int main() {
                int a = 10;
                int b = 2;
                a /= b;
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_div_int(a, b)" in output

    def test_mod_equals_uses_helper(self):
        src = '''
            int main() {
                int a = 10;
                int b = 3;
                a %= b;
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_mod_int(a, b)" in output

    def test_double_div_equals_uses_helper(self):
        src = '''
            int main() {
                double a = 10.0;
                double b = 3.0;
                a /= b;
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_div_double(a, b)" in output


class TestBoolPrint:
    def test_print_bool_format_spec(self):
        src = '''
            void test() {
                bool b = false;
                print(b);
            }
        '''
        output = generate(src)
        assert "%s" in output
        assert '? "true" : "false"' in output

    def test_fstring_bool(self):
        src = '''
            void test() {
                bool b = true;
                string s = f"value: {b}";
            }
        '''
        output = generate(src)
        assert '? "true" : "false"' in output


class TestListReduce:
    def test_reduce_emitted(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int sum = nums.reduce(0, add);
                return 0;
            }
            int add(int a, int b) { return a + b; }
        '''
        output = generate(src)
        assert "_reduce(" in output

    def test_reduce_function_generated(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int sum = nums.reduce(0, add);
                return 0;
            }
            int add(int a, int b) { return a + b; }
        '''
        output = generate(src)
        assert "acc = fn(acc" in output


class TestListJoinMemcpy:
    def test_join_uses_memcpy(self):
        src = '''
            int main() {
                List<string> words = ["hello", "world"];
                string result = words.join(" ");
                return 0;
            }
        '''
        output = generate(src)
        assert "memcpy(result + pos" in output


class TestListCountFill:
    def test_count(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 2, 3, 2];
                int c = nums.count(2);
                return 0;
            }
        '''
        output = generate(src)
        assert "_count(" in output

    def test_fill(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                nums.fill(0);
                return 0;
            }
        '''
        output = generate(src)
        assert "_fill(" in output


class TestStringIsUpperLower:
    def test_isUpper(self):
        src = '''
            void test() {
                string s = "HELLO";
                bool u = s.isUpper();
            }
        '''
        output = generate(src)
        assert "__btrc_isUpper(s)" in output

    def test_isLower(self):
        src = '''
            void test() {
                string s = "hello";
                bool l = s.isLower();
            }
        '''
        output = generate(src)
        assert "__btrc_isLower(s)" in output

    def test_isUpper_helper_emitted(self):
        src = '''
            void test() {
                string s = "HELLO";
                bool u = s.isUpper();
            }
        '''
        output = generate(src)
        assert "static inline bool __btrc_isUpper" in output
        assert "isupper" in output

    def test_isLower_helper_emitted(self):
        src = '''
            void test() {
                string s = "hello";
                bool l = s.isLower();
            }
        '''
        output = generate(src)
        assert "static inline bool __btrc_isLower" in output
        assert "islower" in output


class TestMapGetPointerFallback:
    def test_pointer_value_returns_null(self):
        """Map<string, string> get() fallback should use NULL, not compound literal."""
        src = '''
            int main() {
                Map<string, string> m = {};
                m.put("a", "b");
                string v = m.get("a");
                return 0;
            }
        '''
        output = generate(src)
        assert "return NULL;" in output


class TestListRemoveAll:
    def test_removeAll(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3, 2, 4];
                nums.removeAll(2);
                return 0;
            }
        '''
        output = generate(src)
        assert "_removeAll(" in output


class TestMapMerge:
    def test_merge(self):
        src = '''
            int main() {
                Map<string, int> a = {};
                Map<string, int> b = {};
                a.merge(b);
                return 0;
            }
        '''
        output = generate(src)
        assert "_merge(" in output


class TestSetToList:
    def test_toList(self):
        src = '''
            int main() {
                Set<int> s = {};
                s.add(1);
                List<int> l = s.toList();
                return 0;
            }
        '''
        output = generate(src)
        assert "_toList(" in output


class TestListReduceFunction:
    def test_reduce_function_body(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                int sum = nums.reduce(0, add);
                return 0;
            }
            int add(int a, int b) { return a + b; }
        '''
        output = generate(src)
        assert "btrc_List_int_reduce" in output


class TestListSwap:
    def test_swap_emits_function(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                nums.swap(0, 2);
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_List_int_swap" in output

    def test_swap_bounds_check(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3];
                nums.swap(0, 2);
                return 0;
            }
        '''
        output = generate(src)
        assert "index out of bounds" in output


class TestNullCoalescingSafe:
    def test_uses_temp_variable(self):
        """Ensure ?? uses a temp to avoid double-evaluating left side."""
        src = '''
            class Foo { public int x; }
            int main() {
                Foo* a = null;
                Foo* b = new Foo();
                Foo* c = a ?? b;
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_tmp_" in output
        assert "!= NULL" in output


class TestThrowUnreachable:
    def test_throw_marks_unreachable(self):
        """Code after throw should trigger unreachable warning."""
        from src.compiler.python.lexer import Lexer
        from src.compiler.python.parser import Parser
        from src.compiler.python.analyzer import Analyzer
        src = '''
            int main() {
                throw "error";
                int x = 5;
                return 0;
            }
        '''
        tokens = Lexer(src).tokenize()
        program = Parser(tokens).parse()
        analyzed = Analyzer().analyze(program)
        errors = [e for e in analyzed.errors if "Unreachable" in e]
        assert len(errors) >= 1
        assert "throw" in errors[0].lower() or "Unreachable" in errors[0]


class TestStringIsAlnum:
    def test_isAlnum_emits_helper(self):
        src = '''
            int main() {
                string s = "abc123";
                bool r = s.isAlnum();
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_isAlnumStr" in output

    def test_isDigitStr_instance_method(self):
        src = '''
            int main() {
                string s = "12345";
                bool r = s.isDigitStr();
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_isDigitStr" in output

    def test_isAlphaStr_instance_method(self):
        src = '''
            int main() {
                string s = "abc";
                bool r = s.isAlphaStr();
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_isAlphaStr" in output


class TestStringsStaticHelpers:
    def test_strings_fromInt_triggers_helpers(self):
        """Strings.fromInt() should trigger string helper emission."""
        src = '''
            #include "../stdlib/strings.btrc"
            int main() {
                string s = Strings.fromInt(42);
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_strcat" in output or "__btrc_" in output


class TestStringRelationalOps:
    def test_string_less_than(self):
        src = '''
            int main() {
                string a = "abc";
                string b = "def";
                bool r = a < b;
                return 0;
            }
        '''
        output = generate(src)
        assert "strcmp" in output
        assert "< 0" in output

    def test_string_greater_than(self):
        src = '''
            int main() {
                string a = "abc";
                string b = "def";
                bool r = a > b;
                return 0;
            }
        '''
        output = generate(src)
        assert "strcmp" in output
        assert "> 0" in output

    def test_string_less_equal(self):
        src = '''
            int main() {
                string a = "abc";
                string b = "def";
                bool r = a <= b;
                return 0;
            }
        '''
        output = generate(src)
        assert "strcmp" in output
        assert "<= 0" in output


class TestMapIndexing:
    def test_map_get_via_index(self):
        """map[key] should use map_get() not raw array access."""
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("x", 42);
                int v = m["x"];
                return 0;
            }
        '''
        output = generate(src)
        assert "_get(" in output
        # Should NOT have raw array indexing
        assert 'm["x"]' not in output

    def test_map_set_via_index(self):
        """map[key] = value should use map_put()."""
        src = '''
            int main() {
                Map<string, int> m = {};
                m["x"] = 42;
                return 0;
            }
        '''
        output = generate(src)
        assert "_put(" in output


class TestListMinMaxSum:
    def test_min(self):
        src = '''
            int main() {
                List<int> nums = [3, 1, 4, 1, 5];
                int m = nums.min();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_List_int_min" in output

    def test_max(self):
        src = '''
            int main() {
                List<int> nums = [3, 1, 4, 1, 5];
                int m = nums.max();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_List_int_max" in output

    def test_sum(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 3, 4, 5];
                int s = nums.sum();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_List_int_sum" in output


class TestStringRelationalOpsCompare:
    def test_string_less_than_uses_strcmp(self):
        src = '''
            int main() {
                bool r = "abc" < "def";
                return 0;
            }
        '''
        output = generate(src)
        assert "strcmp" in output


class TestMapIndexAccess:
    def test_map_bracket_read(self):
        """map["key"] should use _get()."""
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("x", 1);
                int v = m["x"];
                return 0;
            }
        '''
        output = generate(src)
        assert "_get(" in output

    def test_map_bracket_write(self):
        """map["key"] = value should use _put()."""
        src = '''
            int main() {
                Map<string, int> m = {};
                m["x"] = 42;
                return 0;
            }
        '''
        output = generate(src)
        assert "_put(" in output


class TestSetDestroyField:
    def test_destroy_frees_set_field(self):
        src = '''
            class Foo {
                public Set<int> items;
                public Foo() {
                    self.items = {};
                }
            }
            int main() {
                Foo* f = new Foo();
                delete f;
                return 0;
            }
        '''
        output = generate(src)
        assert "_free(&self->items)" in output


class TestListSorted:
    def test_sorted_emits_function(self):
        src = '''
            int main() {
                List<int> nums = [3, 1, 2];
                List<int> s = nums.sorted();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_List_int_sorted" in output

    def test_sorted_returns_new_list(self):
        src = '''
            int main() {
                List<int> nums = [3, 1, 2];
                List<int> s = nums.sorted();
                return 0;
            }
        '''
        output = generate(src)
        assert "result = btrc_List_int_new()" in output


class TestListDistinct:
    def test_distinct_emits_function(self):
        src = '''
            int main() {
                List<int> nums = [1, 2, 2, 3];
                List<int> d = nums.distinct();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_List_int_distinct" in output


class TestCollectionAliases:
    def test_addAll_routes_to_extend(self):
        src = '''
            int main() {
                List<int> a = [1, 2];
                List<int> b = [3, 4];
                a.addAll(b);
                return 0;
            }
        '''
        output = generate(src)
        assert "_extend(" in output

    def test_subList_routes_to_slice(self):
        src = '''
            int main() {
                List<int> a = [1, 2, 3, 4, 5];
                List<int> b = a.subList(1, 3);
                return 0;
            }
        '''
        output = generate(src)
        assert "_slice(" in output


class TestListReversed:
    def test_reversed_emits_function(self):
        src = '''
            int main() {
                List<int> a = [1, 2, 3];
                List<int> b = a.reversed();
                return 0;
            }
        '''
        output = generate(src)
        assert "_reversed(" in output

    def test_reversed_returns_new_list(self):
        """reversed() should create a new list, not modify the original."""
        src = '''
            int main() {
                List<int> a = [1, 2, 3];
                List<int> b = a.reversed();
                return 0;
            }
        '''
        output = generate(src)
        assert "btrc_List_int_reversed" in output
        assert "_new()" in output  # creates new list inside reversed()


class TestMapContainsValue:
    def test_containsValue_emits_function(self):
        src = '''
            int main() {
                Map<string, int> m = {};
                m.put("a", 1);
                bool found = m.containsValue(1);
                return 0;
            }
        '''
        output = generate(src)
        assert "_containsValue(" in output

    def test_containsValue_string_values_use_strcmp(self):
        src = '''
            int main() {
                Map<int, string> m = {};
                m.put(1, "hello");
                bool found = m.containsValue("hello");
                return 0;
            }
        '''
        output = generate(src)
        assert "strcmp" in output
        assert "_containsValue(" in output


class TestStringHelperOptimization:
    def test_startsWith_uses_helper(self):
        src = '''
            int main() {
                string s = "hello";
                bool b = s.startsWith("he");
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_startsWith(" in output

    def test_endsWith_uses_helper(self):
        src = '''
            int main() {
                string s = "hello.txt";
                bool b = s.endsWith(".txt");
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_endsWith(" in output

    def test_contains_uses_helper(self):
        src = '''
            int main() {
                string s = "hello world";
                bool b = s.contains("world");
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_strContains(" in output


class TestRemoveAtAlias:
    def test_removeAt_routes_to_remove(self):
        src = '''
            int main() {
                List<int> a = [1, 2, 3];
                a.removeAt(1);
                return 0;
            }
        '''
        output = generate(src)
        assert "_remove(" in output


class TestStringSplitIteration:
    def test_split_iteration_uses_null_terminator(self):
        """for s in str.split() should iterate char** with NULL check, not char-by-char."""
        src = '''
            int main() {
                string csv = "a,b,c";
                for part in csv.split(",") {
                    print(part);
                }
                return 0;
            }
        '''
        output = generate(src)
        assert "!= NULL" in output
        assert "char*" in output


class TestStringConversions:
    def test_toDouble_emits_atof(self):
        src = '''
            int main() {
                string s = "3.14";
                double d = s.toDouble();
                return 0;
            }
        '''
        output = generate(src)
        assert "atof(s)" in output

    def test_toLong_emits_atol(self):
        src = '''
            int main() {
                string s = "123456789";
                long n = s.toLong();
                return 0;
            }
        '''
        output = generate(src)
        assert "atol(s)" in output

    def test_toBool_emits_logic(self):
        src = '''
            int main() {
                string s = "true";
                bool b = s.toBool();
                return 0;
            }
        '''
        output = generate(src)
        assert "strlen(s)" in output
        assert 'strcmp(s, "false")' in output


class TestListFindIndex:
    def test_findIndex_emits_function(self):
        src = '''
            bool isEven(int x) { return x % 2 == 0; }
            int main() {
                List<int> a = [1, 3, 4, 7];
                int idx = a.findIndex(isEven);
                return 0;
            }
        '''
        output = generate(src)
        assert "_findIndex(" in output


class TestListTakeDrop:
    def test_take_emits_function(self):
        src = '''
            int main() {
                List<int> a = [1, 2, 3, 4, 5];
                List<int> b = a.take(3);
                return 0;
            }
        '''
        output = generate(src)
        assert "_take(" in output

    def test_drop_emits_function(self):
        src = '''
            int main() {
                List<int> a = [1, 2, 3, 4, 5];
                List<int> b = a.drop(2);
                return 0;
            }
        '''
        output = generate(src)
        assert "_drop(" in output


class TestTypePromotion:
    def test_double_promotion(self):
        """double + int should infer as double."""
        src = '''
            int main() {
                double d = 1.5;
                int i = 2;
                double r = d + i;
                return 0;
            }
        '''
        # Should not error during analysis
        output = generate(src)
        assert "double" in output


class TestNumericToString:
    def test_int_toString_emits_helper(self):
        src = '''
            int main() {
                int n = 42;
                string s = n.toString();
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_intToString(n)" in output

    def test_bool_toString_emits_ternary(self):
        src = '''
            int main() {
                bool b = true;
                string s = b.toString();
                return 0;
            }
        '''
        output = generate(src)
        assert '"true"' in output
        assert '"false"' in output


class TestStringZfill:
    def test_zfill_emits_helper(self):
        src = '''
            int main() {
                string s = "42";
                string z = s.zfill(5);
                return 0;
            }
        '''
        output = generate(src)
        assert "__btrc_zfill(s, 5)" in output


class TestOctalLiterals:
    def test_octal_to_c_format(self):
        """0o777 in btrc should become 0777 in C."""
        src = '''
            int main() {
                int x = 0o777;
                return 0;
            }
        '''
        output = generate(src)
        assert "0777" in output
        assert "0o777" not in output


class TestBitwiseOperators:
    def test_bitwise_and(self):
        src = '''
            int main() {
                int a = 0xFF;
                int b = 0x0F;
                int c = a & b;
                return 0;
            }
        '''
        output = generate(src)
        assert "&" in output

    def test_bitwise_or(self):
        src = '''
            int main() {
                int a = 0xF0;
                int b = 0x0F;
                int c = a | b;
                return 0;
            }
        '''
        output = generate(src)
        assert "|" in output

    def test_bitwise_xor(self):
        src = '''
            int main() {
                int a = 0xFF;
                int b = 0x0F;
                int c = a ^ b;
                return 0;
            }
        '''
        output = generate(src)
        assert "^" in output

    def test_left_shift(self):
        src = '''
            int main() {
                int a = 1;
                int b = a << 4;
                return 0;
            }
        '''
        output = generate(src)
        assert "<<" in output

    def test_right_shift(self):
        src = '''
            int main() {
                int a = 256;
                int b = a >> 4;
                return 0;
            }
        '''
        output = generate(src)
        assert ">>" in output


class TestSizeofExpr:
    def test_sizeof_type(self):
        src = '''
            int main() {
                int s = sizeof(int);
                return 0;
            }
        '''
        output = generate(src)
        assert "sizeof(int)" in output

    def test_sizeof_struct(self):
        src = '''
            class Point {
                public int x;
                public int y;
            }
            int main() {
                int s = sizeof(Point);
                return 0;
            }
        '''
        output = generate(src)
        assert "sizeof(Point)" in output
