"""Ownership validation contracts for managed allocation shapes."""

import os
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)
REPO = Path(__file__).resolve().parents[3]
OWNERSHIP_RUNTIME = REPO / "src/tests/btrc/fixtures/managed_return_ownership_runtime.btrc"
GENERIC_LOCAL_RUNTIME = REPO / "src/tests/btrc/fixtures/generic_local_ownership_runtime.btrc"
SWITCH_CLEANUP_RUNTIME = REPO / "src/tests/btrc/fixtures/switch_managed_cleanup_runtime.btrc"


def _compile_reference_source(tmp_path: Path, source: str):
    program = tmp_path / "reference-ownership.btrc"
    generated = tmp_path / "reference-ownership.c"
    program.write_text(source)
    result = subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(program),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, generated


def test_delete_of_parameterized_generic_class_runs_strictly(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        #include <assert.h>

        int alive = 0;

        class Node<T> {
            public Node() { alive++; }
            public void __del__() { alive--; }
        }

        class Bag<T> {
            public void discard(Node<T> node) { delete node; }
        }

        int main() {
            Bag<int> bag = new Bag<int>();
            bag.discard(new Node<int>());
            assert(alive == 0);
            delete bag;
            return 0;
        }
    """
    result, generated = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_generated = _compile_reference_source(tmp_path, source)
    assert result.returncode == 0, result.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(generated, tmp_path / "generic-delete")
    _strict_build_and_run(
        reference_generated,
        tmp_path / "reference-generic-delete",
    )


def test_delete_of_bare_type_parameter_stays_rejected(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        class Bag<T> {
            public void discard(T value) { delete value; }
        }
        int main() { return 0; }
    """
    result, _ = _compile_source(semantic_btrcc, tmp_path, source)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "delete requires a concrete allocation type" in result.stderr


def test_generic_scalar_result_is_not_misclassified_as_owned(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <stdlib.h>
        #define ABS_VALUE(value) abs(value)

        class Values<T> {
            public T value;
            public T get(int index) {
                (void)index;
                return self.value;
            }
        }
        class Reader<T> {
            public int read(Values<T> values) {
                return ABS_VALUE(values[0]);
            }
        }
        int main() {
            Values<int> values = new Values<int>();
            values.value = -42;
            Reader<int> reader = new Reader<int>();
            int result = reader.read(values);
            delete reader;
            delete values;
            return result == 42 ? 0 : 1;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-generic-scalar")
    _strict_build_and_run(reference_source, tmp_path / "reference-generic-scalar")


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        (
            "class Item { public Item() {} } int main() { (int, Item) value = (1, new Item()); return 0; }",
            "shallow aggregate",
        ),
        (
            "class Item { public Item() {} } "
            "struct Slot { Item value; }; "
            "int main() { Slot slot = {new Item()}; return 0; }",
            "shallow aggregate",
        ),
        (
            "class Item { public Item() {} } "
            "enum class Payload { Some(Item value), None } "
            "int main() { Payload value = Payload.Some(new Item()); return 0; }",
            "rich-enum payload",
        ),
        (
            "class Item { public Item() {} } "
            "struct Slot { Item value; }; "
            "int main() { Item owner = new Item(); Slot slot = {owner}; "
            "slot.value = new Item(); return 0; }",
            "shallow aggregate",
        ),
    ],
)
def test_shallow_aggregate_temporaries_fail_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_shallow_aggregates_accept_prebound_borrowed_references(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        #include <assert.h>
        class Item {
            public int id;
            public Item(int id) { self.id = id; }
        }
        struct Slot { Item value; };
        enum class Payload { Some(Item value), None }
        int main() {
            Item owner = new Item(7);
            (int, Item) tupleValue = (1, owner);
            (int, (Item, int)) nestedTuple = (2, (owner, 3));
            Slot slot = {owner};
            Payload payload = Payload.Some(owner);
            assert(tupleValue._1 == owner);
            assert(nestedTuple._1._0 == owner);
            assert(slot.value == owner);
            assert(payload.data.Some.value == owner);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-borrowed")
    _strict_build_and_run(reference_source, tmp_path / "reference-borrowed")


def test_omitted_owned_rich_enum_default_fails_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        string makeText() { return "a".toUpper(); }
        enum class Payload { Some(string value = makeText()) }
        int main() {
            Payload value = Payload.Some();
            return 0;
        }
    """
    selfhost, _selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _reference_source = _compile_reference_source(tmp_path, source)
    diagnostic = "Omitted default for rich-enum payload 'Payload.Some.value' produces a caller-owned temporary"

    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_borrowed_rich_enum_default_remains_valid_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        #include <string.h>
        enum class Payload { Some(string value = "safe") }
        int main() {
            Payload value = Payload.Some();
            assert(strcmp(value.data.Some.value, "safe") == 0);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-borrowed-default")
    _strict_build_and_run(reference_source, tmp_path / "reference-borrowed-default")


def test_generic_simple_enum_tostring_has_typed_forward_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        enum Color { RED, BLUE };
        class Labeler<T> {
            public int labelLength(Color value) {
                return value.toString().length();
            }
        }
        int main() {
            Labeler<int> labeler = new Labeler<int>();
            assert(labeler.labelLength(RED) == 3);
            delete labeler;
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-enum-forward")
    _strict_build_and_run(reference_source, tmp_path / "reference-enum-forward")


def test_managed_return_and_call_ownership_has_runtime_parity(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = OWNERSHIP_RUNTIME.read_text()
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-managed-returns")
    _strict_build_and_run(reference_source, tmp_path / "reference-managed-returns")


def test_generic_method_locals_have_runtime_ownership_parity(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = GENERIC_LOCAL_RUNTIME.read_text()
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-generic-local-ownership")
    _strict_build_and_run(reference_source, tmp_path / "reference-generic-local-ownership")


def test_switch_control_cleanup_has_runtime_parity(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = SWITCH_CLEANUP_RUNTIME.read_text()
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-switch-cleanup")
    _strict_build_and_run(reference_source, tmp_path / "reference-switch-cleanup")


def test_unmanaged_c_call_operands_do_not_require_arc_types(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        #include <assert.h>
        #include <stdio.h>
        class Reporter<T> {
            public void report(T marker) {
                assert(sizeof(marker) != (size_t)0);
                fprintf(stderr, "%s", "");
            }
        }
        int main() {
            Reporter<int> reporter = new Reporter<int>();
            reporter.report(1);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-c-operands")
    _strict_build_and_run(reference_source, tmp_path / "reference-c-operands")


def test_owned_call_receiver_field_assignment_has_runtime_parity(semantic_btrcc: Path, tmp_path: Path) -> None:
    source = """
        class Flag {
            public bool value;
            public Flag() { self.value = false; }
        }
        Flag makeFlag() { return new Flag(); }
        int main() {
            makeFlag().value = true;
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-owned-lvalue")
    _strict_build_and_run(reference_source, tmp_path / "reference-owned-lvalue")


@pytest.mark.parametrize(
    "returned",
    (
        "true ? local : local",
        "(Item)local",
        "local = local",
    ),
)
def test_borrowed_property_getter_rejects_nested_local_escape(
    semantic_btrcc: Path,
    tmp_path: Path,
    returned: str,
) -> None:
    source = f"""
        class Item {{ public Item() {{}} }}
        class Box {{
            public Item invalid {{
                get {{
                    Item local = new Item();
                    return {returned};
                }}
            }}
        }}
        int main() {{ return 0; }}
    """
    selfhost, _selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _reference_source = _compile_reference_source(tmp_path, source)
    diagnostic = "borrowed property getter cannot return"
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr
