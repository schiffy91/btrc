"""Canonical property storage and inheritance contracts for btrcc."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "class Value { public int _prop_item; public int item { get; set; } } int main() { return 0; }",
            "Instance storage name '_prop_item'",
        ),
        (
            "class Value { public int __rc; } int main() { return 0; }",
            "name '__rc' is reserved by C11",
        ),
        (
            "class Base { public int value; } "
            "class Child extends Base { public float value; } "
            "int main() { return 0; }",
            "Instance storage 'value'",
        ),
        (
            "class Base { public int value { get; set; } } "
            "class Child extends Base { public int _prop_value; } "
            "int main() { return 0; }",
            "Instance storage '_prop_value'",
        ),
        (
            "class Base { public int value { get; set; } } "
            "class Child extends Base { public int value { get; set; } } "
            "int main() { return 0; }",
            "Instance storage '_prop_value'",
        ),
        (
            "class Base { public int value { get { return 1; } } } "
            "class Child extends Base { public int value; } "
            "int main() { return 0; }",
            "inherited member of a different kind",
        ),
        (
            "class Left extends Right {} class Right extends Left {} int main() { return 0; }",
            "Class inheritance cycle",
        ),
        (
            "class Base { public int value { get { return 1; } } } "
            "class Child extends Base {} "
            "int Child_get_value(Child value) { return 0; } "
            "int main() { return 0; }",
            "Emitted C symbol 'Child_get_value'",
        ),
    ],
)
def test_storage_collisions_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert result.stdout == ""
    assert diagnostic in result.stderr


def test_custom_property_does_not_reserve_a_backing_name(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        class Value {
            public int _prop_item;
            public int item {
                get { return self._prop_item; }
                set { self._prop_item = value; }
            }
            public void write(int next) { self.item = next; }
            public int read() { return self.item; }
        }
        int main() {
            Value value = new Value();
            value.write(9);
            return value.read() == 9 ? 0 : 1;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr
    struct = result.stdout.split("struct Value {", 1)[1].split("};", 1)[0]
    assert struct.count("_prop_item") == 1
    _strict_build_and_run(generated, tmp_path / "custom-property")


def test_inherited_wrappers_and_managed_backing_run_strictly(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = (FIXTURES / "property_layout_runtime.btrc").read_text()
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr

    base_struct = result.stdout.split("struct Base {", 1)[1].split("};", 1)[0]
    child_struct = result.stdout.split("struct Child {", 1)[1].split("};", 1)[0]
    assert "int _prop_value;" in base_struct
    assert "Item* _prop_owned;" in base_struct
    assert "Item* _prop_guarded;" in base_struct
    assert "_prop_doubled" not in base_struct
    assert child_struct.index("_prop_value") < child_struct.index("extra")
    assert "int Child_get_value(Child* self)" in result.stdout
    assert "Base_get_value(((Base*)self))" in result.stdout
    assert "Base_set_owned(((Base*)self), value)" in result.stdout
    assert "&self->_prop_next" in result.stdout

    _strict_build_and_run(generated, tmp_path / "property-layout")


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "class Box<T> { public int _prop_value; "
            "public T value { get; set; } } "
            "int main() { Box<int> box = new Box<int>(); return 0; }",
            "Instance storage name '_prop_value'",
        ),
        (
            "class Base<T> { public T value { get; set; } } class Child<T> extends Base {} int main() { return 0; }",
            "Generic property inheritance is not supported: class 'Child' inherits property 'value'",
        ),
        (
            "class Box<T> { public T value { get; } } "
            "int main() { Box<int> box = new Box<int>(); "
            "box.value = 1; return 0; }",
            "Property 'value' has no setter",
        ),
        (
            "class Box<T> { public T value { get; set; } "
            "public T get_value() { return self.value; } } "
            "int main() { Box<int> box = new Box<int>(); return 0; }",
            "Emitted C symbol 'btrc_Box_int_get_value'",
        ),
    ],
)
def test_generic_property_shapes_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert result.stdout == ""
    assert diagnostic in result.stderr


def test_generic_properties_compile_strictly_and_run(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = (FIXTURES / "generic_property_layout_runtime.btrc").read_text()
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 0, result.stderr

    int_struct = result.stdout.split("struct btrc_Box_int {", 1)[1].split("};", 1)[0]
    item_struct = result.stdout.split("struct btrc_Box_Item_p1 {", 1)[1].split("};", 1)[0]
    assert "int _prop_automatic;" in int_struct
    assert "int customStorage;" in int_struct
    assert "int _prop_mixed;" in int_struct
    assert "_prop_custom" not in int_struct
    assert "Item* _prop_automatic;" in item_struct
    assert "Item* customStorage;" in item_struct
    assert "Item* _prop_mixed;" in item_struct
    assert "int btrc_Box_int_get_automatic(" in result.stdout
    assert "void btrc_Box_int_set_mixed(" in result.stdout
    assert "Item* btrc_Box_Item_p1_get_custom(" in result.stdout

    _strict_build_and_run(generated, tmp_path / "generic-property-layout")
    reference, reference_generated = _compile_reference_source(tmp_path, source)
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(
        reference_generated,
        tmp_path / "generic-property-layout-reference",
    )
