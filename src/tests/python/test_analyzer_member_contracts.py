"""Interface, inherited-member, and property semantic contracts."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<member-contracts>").tokenize()).parse()
    return Analyzer().analyze(program).errors


def _program(source: str):
    return Parser(Lexer(source, "<member-contracts>").tokenize()).parse()


def _has(errors: list[str], text: str) -> bool:
    return any(text.lower() in error.lower() for error in errors)


def test_interface_methods_resolve_independent_of_declaration_order():
    errors = _errors("""
        interface Child extends Middle {}
        interface Middle extends Base {}
        interface Base { int required(); }
        class Incomplete implements Child {}
    """)
    assert _has(errors, "does not implement interface method 'required'")


def test_interface_inheritance_cycle_is_rejected():
    errors = _errors("""
        interface Left extends Right {}
        interface Right extends Left {}
    """)
    assert _has(errors, "circular interface inheritance")


def test_inherited_property_remains_visible():
    errors = _errors("""
        class Base { public int value { get; set; } }
        class Child extends Base {}
        int read(Child child) { child.value = 2; return child.value; }
    """)
    assert errors == []


def test_child_cannot_access_parent_private_members():
    errors = _errors("""
        class Base {
            private int secret;
            private int hidden() { return self.secret; }
        }
        class Child extends Base {
            public int leak() { return self.secret + self.hidden(); }
        }
    """)
    assert _has(errors, "private field 'secret'")
    assert _has(errors, "private method 'hidden'")


def test_qualified_member_access_rejects_wrong_storage_shape():
    errors = _errors("""
        class Base { class int inheritedStatic; }
        class Child extends Base { public int instanceValue; }
        int run() {
            Child child = Child();
            return Child.missing + Child.instanceValue
                + Child.inheritedStatic + child.inheritedStatic;
        }
    """)

    assert _has(errors, "has no static field or method 'missing'")
    assert _has(errors, "instance member 'instancevalue'")
    assert _has(errors, "has no static field or method 'inheritedstatic'")
    assert _has(errors, "has no field or method 'inheritedstatic'")


def test_local_can_shadow_type_name_without_changing_type_positions():
    errors = _errors("""
        class Box { public int value; }
        int read() {
            Box Box = Box();
            Box other = new Box();
            return Box.value + other.value;
        }
    """)

    assert errors == []


def test_qualified_rich_enum_variant_must_exist():
    errors = _errors("""
        enum class Color { Red, Blue }
        int run() {
            Color value = Color.Red;
            Color other = Color.Missing();
            return Color.Missing + value.missing;
        }
    """)

    assert _has(errors, "rich enum 'color' has no variant 'missing'")
    assert _has(errors, "rich enum 'color' has no field 'missing'")


def test_private_fields_and_properties_reject_reads_and_writes():
    errors = _errors("""
        class Secret {
            private int field;
            private int property { get; set; }
        }
        int read(Secret value) { return value.field + value.property; }
        void write(Secret value) {
            value.field = 1;
            value.property = 2;
        }
    """)

    assert sum("private field 'field'" in error.lower() for error in errors) == 2
    assert sum("private property 'property'" in error.lower() for error in errors) == 2


def test_explicit_property_bodies_obey_return_contracts():
    errors = _errors("""
        class Broken {
            public int missing { get { int value = 1; } }
            public int wrong { get { return "bad"; } }
            public int setter { set { return 1; } }
        }
    """)
    assert _has(errors, "does not return a value on every path")
    assert _has(errors, "return type mismatch")
    assert _has(errors, "cannot return a value")


def test_property_read_and_write_require_matching_accessor():
    errors = _errors("""
        class Accessors {
            public int readOnly { get; }
            public int writeOnly { set; }
        }
        int use(Accessors value) {
            value.readOnly = 1;
            return value.writeOnly;
        }
    """)
    assert _has(errors, "property 'readonly' has no setter")
    assert _has(errors, "property 'writeonly' has no getter")


def test_inherited_field_and_auto_property_storage_collisions_are_rejected():
    field_errors = _errors("""
        class Base { public int value; }
        class Child extends Base { public float value; }
    """)
    backing_errors = _errors("""
        class Base { public int value { get; set; } }
        class Child extends Base { public int _prop_value; }
    """)
    local_backing_errors = _errors("""
        class Value {
            public int _prop_item;
            public int item { get; set; }
        }
    """)

    assert _has(field_errors, "conflicts with inherited storage")
    assert _has(backing_errors, "conflicts with inherited storage")
    assert _has(local_backing_errors, "instance storage name '_prop_item'")


def test_pre_resolved_class_tables_are_not_merged_or_validated_twice():
    base = Analyzer().analyze(
        _program("""
            class Base { public int value; }
            class Child extends Base { public int extra; }
        """)
    )
    assert base.errors == []

    incremental = Analyzer()
    incremental.class_table = dict(base.class_table)
    result = incremental.analyze(_program("int main() { return 0; }"))

    assert not _has(result.errors, "conflicts with inherited storage")
    assert [name for name, _member in result.class_table["Child"].instance_storage] == [
        "value",
        "extra",
    ]


def test_inherited_auto_property_preserves_layout_and_emits_wrappers():
    generated = emit_c("""
        class Base { public int value { get; set; } }
        class Child extends Base { public int extra; }
        int main() {
            Child child = new Child();
            child.value = 7;
            return child.value - 7;
        }
    """)

    child_struct = generated.split("struct Child {", 1)[1].split("};", 1)[0]
    assert child_struct.index("int _prop_value;") < child_struct.index("int extra;")
    assert "int Child_get_value(Child* self)" in generated
    assert "return Base_get_value(((Base*)self));" in generated
    assert "Base_set_value(((Base*)self), value)" in generated
