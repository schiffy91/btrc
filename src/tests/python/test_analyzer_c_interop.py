"""C interop typing for arrays, pointers, and opaque scalar typedefs."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<c-interop>").tokenize()).parse()
    return Analyzer().analyze(program)


def test_fixed_array_decays_to_pointer_argument():
    result = _analyze("""
        void consume(int* values) {}
        void run() { int values[2]; consume(values); }
    """)
    assert result.errors == []


def test_address_of_infers_pointer_type_for_call_validation():
    result = _analyze("""
        void write(int* value) {}
        void run() { int value = 0; write(&value); }
    """)
    assert result.errors == []


def test_opaque_c_scalar_typedef_supports_integral_operations():
    result = _analyze("""
        void run() {
            ssize_t count = 1;
            char buffer[4];
            if (count > (ssize_t)0) { buffer[count] = 'x'; }
            count++;
        }
    """)
    assert result.errors == []


def test_explicit_c_enum_supports_integer_backed_operations():
    result = _analyze("""
        void run(enum Color color) {
            int total = 0;
            if (color == 1) { total += color; }
        }
    """)
    assert result.errors == []


def test_native_enum_supports_its_integer_backed_contract():
    result = _analyze("""
        enum Color { Red, Green };
        int increment(Color color) { return color + 1; }
        void run(Color color) {
            int total = 0;
            if (color == 1) { total += color; }
        }
    """)
    assert result.errors == []


def test_pointer_arithmetic_and_difference_are_valid():
    result = _analyze("""
        void run() {
            char* begin;
            char* end;
            char* next = begin + 1;
            long distance = end - begin;
        }
    """)
    assert result.errors == []


def test_char_array_interoperates_with_string_parameters():
    result = _analyze("""
        void consume(string value) {}
        void run() { char buffer[16]; consume(buffer); }
    """)
    assert result.errors == []


def test_integer_suffixes_preserve_wide_unsigned_types():
    result = _analyze("""
        void run() {
            var signedWide = 1LL;
            var unsignedWide = 1ULL;
        }
    """)
    function = result.program.declarations[0]
    assert function.body.statements[0].type.base == "long long"
    assert function.body.statements[1].type.base == "unsigned long long"


def test_generic_self_and_interface_signatures_substitute_parameters():
    result = _analyze("""
        interface Iterable<T> { T iterGet(int index); }
        class Values<K, V> implements Iterable {
            public K iterGet(int index) { K value; return value; }
            public Values<K, V> selfValue() { return self; }
        }
    """)
    assert result.errors == []


def test_generic_type_parameter_allows_runtime_ownership_operation():
    result = _analyze("""
        class Values<T> {
            public void retain(T value) { keep value; release value; }
        }
    """)
    assert result.errors == []


def test_generic_type_parameter_rejects_conditional_borrow_consumption():
    result = _analyze("""
        class Values<T> {
            public void releaseMaybe(T value, bool condition) {
                if (condition) { release value; }
            }
        }
    """)
    assert any("unconditional leading release/delete" in error for error in result.errors)


def test_nullable_references_share_their_nonnullable_c_value_shape():
    result = _analyze("""
        class Node {}
        void takeText(string text) {}
        void takeNode(Node node) {}
        void run(string? text, Node? node) {
            if (text != null) { takeText(text); }
            if (node != null) { takeNode(node); }
        }
    """)
    assert result.errors == []


def test_fixed_array_accepts_contextual_list_initializer():
    result = _analyze("void run() { int values[1] = [0]; }")
    assert result.errors == []


def test_native_struct_field_type_is_available_to_typed_updates():
    result = _analyze("""
        struct Point { int x; int y; };
        void run() { struct Point point = {1, 2}; point.x += 1; }
    """)

    assert result.errors == []
    function = result.program.declarations[1]
    update = function.body.statements[1].expr
    assert result.node_types[id(update.target)].base == "int"
