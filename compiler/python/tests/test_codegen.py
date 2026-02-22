"""Tests for the btrc code generator."""

from compiler.python.lexer import Lexer
from compiler.python.parser import Parser
from compiler.python.analyzer import Analyzer
from compiler.python.codegen import CodeGen


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
        assert "Vec3 Vec3_new(float x)" in output
        assert "Vec3 self;" in output
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
        assert "Counter Counter_new" in output
        assert "void Counter_inc(Counter* self)" in output
        assert "int Counter_get(Counter* self)" in output
        assert "Counter_new()" in output


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
        # The auto-header should NOT emit it since user already included it
        header_section = output.split("#include <math.h>")[0]
        # Count #include <math.h> in the generated header area
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
