"""Addresses cannot escape computed fields or temporary managed owners."""

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import _compile_reference_source
from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

TEMPORARY_ADDRESS_CASES = (
    ("list-literal", "int main() { int* address = &[1, 2].len; return 0; }"),
    (
        "returned-string",
        'string makeText() { return "abc"; } int main() { char* address = &makeText()[0]; return 0; }',
    ),
    ("string-concat", 'int main() { char* address = &("a" + "b")[0]; return 0; }'),
    ("f-string", 'int main() { int value = 1; char* address = &f"{value}"[0]; return 0; }'),
    (
        "ownership-erasing-cast",
        'string makeText() { return "abc"; } int main() { char* address = &((char*)makeText())[0]; return 0; }',
    ),
    (
        "managed-operator-result",
        """
        class Item {
            public int value;
            public Item() { self.value = 0; }
            public Item __add__(Item other) { return new Item(); }
        }
        int main() {
            Item first = new Item();
            Item second = new Item();
            int* address = &(first + second).value;
            return 0;
        }
        """,
    ),
    (
        "virtual-index-assignment-result",
        """
        class Item { public int field; public Item() { self.field = 0; } }
        class Store<T> {
            private T stored;
            public Store(T stored) { self.stored = stored; }
            public T get(int index) { return self.stored; }
            public void set(int index, T value) { self.stored = value; }
        }
        int main() {
            Store<Item> store = new Store<Item>(new Item());
            int* address = &(store[0] = new Item()).field;
            return 0;
        }
        """,
    ),
    (
        "virtual-property-assignment-result",
        """
        class Item { public int field; public Item() { self.field = 0; } }
        class Holder { public Item item { get; set; } }
        int main() {
            Holder holder = new Holder();
            int* address = &(holder.item = new Item()).field;
            return 0;
        }
        """,
    ),
)


@pytest.mark.parametrize(
    ("_case", "source"),
    TEMPORARY_ADDRESS_CASES,
    ids=[case[0] for case in TEMPORARY_ADDRESS_CASES],
)
def test_temporary_managed_projection_addresses_are_rejected_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    _case: str,
    source: str,
) -> None:
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "Unary operator '&'" in selfhost.stderr
    assert "Unary operator '&'" in reference.stderr
    assert "char_destroy" not in selfhost.stdout
    assert not selfhost_source.exists()
    assert not reference_source.exists()


@pytest.mark.parametrize(
    "operation",
    ("text.len = 0;", "text.len++;", "int* address = &text.len;"),
    ids=("assignment", "increment", "address"),
)
def test_string_method_names_are_not_field_storage(
    semantic_btrcc: Path,
    tmp_path: Path,
    operation: str,
) -> None:
    source = f'int main() {{ string text = "abc"; {operation} return 0; }}'
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "no field" in selfhost.stderr.lower()
    assert "no field" in reference.stderr.lower()


def test_address_of_unresolved_call_result_is_rejected_before_type_inference(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = "int main() { int* address = &foreignValue(); return 0; }"
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "Unary operator '&'" in selfhost.stderr
    assert "Unary operator '&'" in reference.stderr
