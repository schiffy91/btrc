"""Function, constructor, method, and callback arguments are type checked."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<call-types>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program).errors


def _has(errors: list[str], text: str) -> bool:
    return any(text.lower() in error.lower() for error in errors)


def test_function_argument_type_mismatch_is_rejected():
    errors = _errors('void take(int value) {} void run() { take("bad"); }')
    assert _has(errors, "expects 'int' but got 'string'")


def test_constructor_argument_type_mismatch_is_rejected():
    errors = _errors("""
        class Item { public Item(int value) {} }
        void run() { Item item = Item("bad"); }
    """)
    assert _has(errors, "expects 'int' but got 'string'")


def test_instance_method_argument_type_mismatch_is_rejected():
    errors = _errors("""
        class Item { public void set(int value) {} }
        void run() { Item item = Item(); item.set("bad"); }
    """)
    assert _has(errors, "expects 'int' but got 'string'")


def test_static_method_missing_arity_and_type_are_rejected():
    errors = _errors("""
        class Math { class int add(int left, int right) { return left + right; } }
        void run() {
            Math.nope();
            Math.add(1);
            Math.add("bad", 2);
        }
    """)
    assert _has(errors, "no class method 'nope'")
    assert _has(errors, "expects at least 2 argument")
    assert _has(errors, "expects 'int' but got 'string'")


def test_named_arguments_bind_to_their_declared_parameters():
    valid = _errors("""
        void write(int count, string text) {}
        void run() { write(text="ok", count=2); }
    """)
    assert valid == []

    invalid = _errors("""
        void write(int count, string text) {}
        void run() { write(text=1, count=2); }
    """)
    assert _has(invalid, "argument 'text'")


def test_function_pointer_argument_type_mismatch_is_rejected():
    errors = _errors("""
        int identity(int value) { return value; }
        void run() {
            __fn_ptr<int, int> callback = identity;
            callback("bad");
        }
    """)
    assert _has(errors, "expects 'int' but got 'string'")


def test_function_pointer_typedefs_are_callable_in_every_storage_position():
    errors = _errors("""
        typedef __fn_ptr<int, int> Unary;
        int increment(int value) { return value + 1; }
        class Callbacks {
            public Unary instance;
            class Unary shared = increment;
            public Unary property { get; set; }
            public Callbacks(Unary callback) {
                self.instance = callback;
                self.property = callback;
            }
        }
        void run() {
            Unary local = increment;
            Callbacks callbacks = Callbacks(local);
            int a = local(8);
            int b = callbacks.instance(9);
            int c = callbacks.property(10);
            int d = Callbacks.shared(11);
        }
    """)
    assert errors == []


def test_function_pointer_typedef_calls_preserve_signature_diagnostics():
    errors = _errors("""
        typedef __fn_ptr<int, int> Unary;
        int increment(int value) { return value + 1; }
        class Callbacks { public Unary callback; }
        void run() {
            Unary local = increment;
            Callbacks callbacks = Callbacks();
            local();
            local("bad");
            local(value=1);
            callbacks.callback("bad");
            string invalid = local(1);
        }
    """)
    assert _has(errors, "expects 1 argument(s) but got 0")
    assert sum("expects 'int' but got 'string'" in error for error in errors) >= 2
    assert _has(errors, "function-pointer calls do not support named arguments")
    assert _has(errors, "Cannot assign 'int' to variable 'invalid' of type 'string'")


def test_pointer_to_function_pointer_is_not_directly_callable():
    errors = _errors("""
        void run() {
            __fn_ptr<int, int>* indirect;
            indirect(1);
        }
    """)
    assert _has(errors, "is not callable")


def test_declared_collection_name_does_not_make_a_data_field_callable():
    errors = _errors("""
        class Map<K, V> { public int size; }
        void run() {
            Map<int, int> values = new Map<int, int>();
            values.size();
        }
    """)
    assert _has(errors, "is not callable")


def test_method_dispatch_mode_is_enforced_at_the_call_site():
    errors = _errors("""
        class Item {
            public void instanceOnly() {}
            class void classOnly() {}
        }
        void run() {
            Item item = Item();
            Item.instanceOnly();
            item.classOnly();
            item.missing();
        }
    """)
    assert _has(errors, "not a class method")
    assert _has(errors, "class method 'classOnly' must be called on 'Item'")
    assert _has(errors, "has no field or method 'missing'")


def test_string_runtime_methods_enforce_shared_signatures():
    errors = _errors("""
        void run() {
            string value = "abc";
            value.substring(1);
            value.contains();
            value.contains(1);
            value.len(1);
            value.noSuchMethod();
            value.join(",");
        }
    """)
    assert _has(errors, "String.substring()' expects 2 argument")
    assert _has(errors, "String.contains()' expects 1 argument")
    assert _has(errors, "expects 'string' but got 'int'")
    assert _has(errors, "String.len()' expects 0 argument")
    assert _has(errors, "String has no method 'noSuchMethod'")
    assert _has(errors, "String has no method 'join'")


def test_thread_mutex_and_scalar_methods_enforce_runtime_signatures():
    errors = _errors("""
        void run() {
            Thread<int> thread;
            Mutex<int> mutex;
            int value = 1;
            thread.join(1);
            mutex.get(1);
            mutex.set();
            mutex.set("bad");
            mutex.destroy(1);
            thread.noSuchMethod();
            mutex.noSuchMethod();
            value.toString(1);
            value.noSuchMethod();
        }
    """)
    assert _has(errors, "Thread.join()' expects 0 argument")
    assert _has(errors, "Mutex.get()' expects 0 argument")
    assert _has(errors, "Mutex.set()' expects 1 argument")
    assert _has(errors, "expects 'int' but got 'string'")
    assert _has(errors, "Mutex.destroy()' expects 0 argument")
    assert _has(errors, "Thread<T> has no method 'noSuchMethod'")
    assert _has(errors, "Mutex<T> has no method 'noSuchMethod'")
    assert _has(errors, "int.toString()' expects 0 argument")
    assert _has(errors, "Type 'int' has no method 'noSuchMethod'")


def test_thread_void_result_is_a_return_slot_not_object_storage():
    errors = _errors("""
        void run() {
            var thread = spawn(() => {});
            thread.join();
        }
    """)
    assert errors == []

    invalid = _errors("void run() { Vector<void> values; Mutex<void> lock; }")
    assert _has(invalid, "Generic argument 1 of Variable 'values'")
    assert _has(invalid, "Generic argument 1 of Variable 'lock'")


def test_rich_enum_variant_calls_are_source_order_independent_and_checked():
    valid = _errors("""
        void run() { Color value = Color.RGB(1, 2, 3); }
        enum class Color { RGB(int red, int green, int blue) }
    """)
    assert valid == []

    errors = _errors("""
        void run() {
            Color good = Color.RGB(1, 2, 3);
            Color shortCall = Color.RGB(1);
            Color wrongType = Color.Named(2);
            Color unknown = Color.Missing();
        }
        enum class Color {
            RGB(int red, int green, int blue),
            Named(string name)
        }
    """)
    assert _has(errors, "Color.RGB()' expects at least 3 argument")
    assert _has(errors, "Color.Named()' expects 'string' but got 'int'")
    assert _has(errors, "has no variant 'Missing'")
