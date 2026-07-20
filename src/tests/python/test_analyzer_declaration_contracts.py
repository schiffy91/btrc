"""Declaration initializers, defaults, generic arity, and construction rules."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<declaration-contracts>").tokenize()).parse()
    return Analyzer().analyze(program).errors


def _has(errors: list[str], text: str) -> bool:
    return any(text.lower() in error.lower() for error in errors)


def test_field_initializer_must_match_declared_type():
    errors = _errors('class Item { public int count = "many"; }')
    assert _has(errors, "field 'item.count' expects 'int' but got 'string'")


def test_function_default_must_match_parameter_type():
    errors = _errors('void run(int count = "many") {}')
    assert _has(errors, "default for parameter 'count' expects 'int'")


def test_method_default_must_match_parameter_type():
    errors = _errors("""
        class Item { public void set(bool enabled = 42) {} }
    """)
    assert _has(errors, "default for parameter 'enabled' expects 'bool'")


def test_bare_generic_class_type_is_rejected():
    errors = _errors("class Box<T> {} void run() { Box value; }")
    assert _has(errors, "type 'box' expects 1 generic argument")


def test_non_generic_class_rejects_type_arguments():
    errors = _errors("class Item {} void run() { Item<int> value; }")
    assert _has(errors, "type 'item' expects 0 generic argument")


def test_new_cannot_instantiate_abstract_class():
    errors = _errors("""
        abstract class Shape { public abstract int area(); }
        void run() { Shape value = new Shape(); }
    """)
    assert _has(errors, "cannot instantiate abstract class 'shape'")


def test_top_level_declaration_kinds_cannot_share_a_name():
    errors = _errors("class Value {} void Value() {}")
    assert _has(errors, "declared as both class and function")


def test_property_names_cannot_collide_with_fields_or_methods():
    errors = _errors("""
        class Value {
            public int item;
            public void item() {}
            public int item { get { return 1; } }
        }
    """)
    assert _has(errors, "declared as both method and property")


def test_duplicate_property_and_interface_method_are_rejected():
    property_errors = _errors("""
        class Value {
            public int item { get { return 1; } }
            public int item { get { return 2; } }
        }
    """)
    interface_errors = _errors("interface Value { int get(); int get(); }")
    assert _has(property_errors, "duplicate property 'item'")
    assert _has(interface_errors, "duplicate method 'get' in interface")


def test_child_member_cannot_change_inherited_member_kind():
    errors = _errors("""
        class Base { public int value; }
        class Child extends Base {
            public int value { get { return 1; } }
        }
    """)
    assert _has(errors, "conflicts with an inherited member")


def test_extern_prototype_and_definition_are_compatible_in_both_orders():
    prototype_first = _errors("""
        extern int compute(int value = 3);
        int compute(int value) { return value; }
    """)
    definition_first = _errors("""
        int compute(int value) { return value; }
        extern int compute(int value = 3);
    """)

    assert prototype_first == []
    assert definition_first == []


def test_static_and_external_function_linkage_conflict():
    errors = _errors("""
        static int compute(int value);
        extern int compute(int value);
    """)

    assert _has(errors, "conflicting declarations for function 'compute'")


def test_repeated_defaults_compare_semantics_not_source_locations():
    same = _errors("""
        int compute(int value = 1 + 2);


        extern int compute(int value = 1 + 2);
    """)
    different = _errors("""
        int compute(int value = 1 + 2);
        extern int compute(int value = 1 + 3);
    """)

    assert same == []
    assert _has(different, "conflicting declarations for function 'compute'")
