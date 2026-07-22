"""Structural generic field and method inference contracts."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<generic-inference>").tokenize()).parse()
    return Analyzer().analyze(program)


def test_nested_generic_field_substitutes_recursively():
    result = _analyze("""
        class Box<T> { public Vector<T> items; }
        void run() {
            Box<int> box;
            Vector<int> items = box.items;
        }
    """)
    assert result.errors == []


def test_generic_assignment_retains_substituted_member_storage_types():
    result = _analyze("""
        class Values<T> {
            public T value;
            public T[] data;
            public T[] view { get; set; }
        }
        void run() {
            int backing[2] = {1, 2};
            Values<int> values = new Values<int>();
            values.value = -42;
            values.data = backing;
            values.view = backing;
        }
    """)
    assert result.errors == []


def test_generic_constructor_call_infers_class_arguments_from_parameters():
    result = _analyze("""
        class Box<T> {
            public T value;
            public Box(T value) { self.value = value; }
            public Box<T> copy() { return Box(self.value); }
        }
        void run() {
            var box = Box(1);
            Box<int> copy = box.copy();
        }
    """)
    assert result.errors == []
    box = result.program.declarations[1].body.statements[0]
    assert box.type.base == "Box"
    assert [argument.base for argument in box.type.generic_args] == ["int"]


def test_nullable_type_parameter_accepts_the_unlifted_parameter_in_template():
    result = _analyze("""
        class Box<T> {
            public T? value;
            public void set(T value) { self.value = value; }
            public T? get() { return self.value; }
        }
        void run() { Box<string> box = new Box<string>(); box.set("ok"); }
    """)
    assert result.errors == []


def test_raw_pointer_to_type_parameter_does_not_inherit_nullable_lift_semantics():
    result = _analyze("""
        class Box<T> {
            public T* value;
            public void set(T value) { self.value = value; }
        }
    """)
    assert any("cannot persist a managed value as a raw representation" in error for error in result.errors)


def test_named_arguments_drive_generic_method_inference_by_name():
    result = _analyze("""
        class Picker {
            public U choose<U>(int count, U value) { return value; }
        }
        void run() {
            Picker picker = Picker();
            string value = picker.choose(value="ok", count=1);
        }
    """)
    assert result.errors == []
    instances = result.generic_method_instances[("Picker", "choose")]
    assert instances[0][1][0].base == "string"


def test_conflicting_repeated_generic_bindings_are_rejected():
    result = _analyze("""
        class Picker {
            public U choose<U>(U first, U second) { return first; }
        }
        void run() {
            Picker picker = Picker();
            picker.choose(1, "not-an-int");
        }
    """)
    assert any("cannot infer consistent type arguments" in error.lower() for error in result.errors)


def test_single_uppercase_class_name_is_a_concrete_method_argument():
    result = _analyze("""
        class T {}
        class Picker {
            public U identity<U>(U value) { return value; }
        }
        void run() {
            Picker picker = Picker();
            T value = T();
            T result = picker.identity(value);
        }
    """)
    assert result.errors == []
    instances = result.generic_method_instances[("Picker", "identity")]
    assert instances[0][1][0].base == "T"
