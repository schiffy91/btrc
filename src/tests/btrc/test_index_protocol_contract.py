"""Read/write protocol parity for indexed class instances."""

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import _compile_reference_source
from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

MALFORMED_PROTOCOLS = (
    ("getter-arity", "public int get(int first, int second) { return 0; }", "int value = item[0];"),
    ("static-getter", "class int get(int index) { return 0; }", "int value = item[0];"),
    ("setter-arity", "public void set(int value) {}", "item[0] = 1;"),
    ("setter-return", "public int set(int index, int value) { return 0; }", "item[0] = 1;"),
    (
        "value-mismatch",
        "public int get(int index) { return 0; } public void set(int index, string value) {}",
        "item[0] += 1;",
    ),
    (
        "index-mismatch",
        "public int get(int index) { return 0; } public void set(string index, int value) {}",
        "item[0] = 1;",
    ),
)


def test_ordinary_class_index_protocol_has_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        class Slots {
            private int stored;
            public Slots(int value) { self.stored = value; }
            public int get(int index) { return self.stored + index; }
            public void set(int index, int value) { self.stored = value - index; }
        }
        int main() {
            Slots slots = new Slots(1);
            slots[2] = 5;
            slots[2] += 4;
            slots[2]++;
            assert(slots[2] == 10);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-ordinary-index")
    _strict_build_and_run(reference_source, tmp_path / "reference-ordinary-index")


def test_write_only_index_protocol_accepts_direct_setter(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Sink<T> {
            public Sink() {}
            public void set(int index, T value) {}
        }
        int main() {
            Sink<int> sink = new Sink<int>();
            sink[0] = 9;
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-write-only-index")
    _strict_build_and_run(reference_source, tmp_path / "reference-write-only-index")


@pytest.mark.parametrize(
    ("_case", "members", "operation"),
    MALFORMED_PROTOCOLS,
    ids=[case[0] for case in MALFORMED_PROTOCOLS],
)
def test_malformed_index_protocol_signatures_are_rejected_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    _case: str,
    members: str,
    operation: str,
) -> None:
    source = f"class Item {{ {members} }} int main() {{ Item item = new Item(); {operation} return 0; }}"
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0


@pytest.mark.parametrize(
    ("member", "operation"),
    (
        ("private int get(int index) { return index; }", "int value = item[0];"),
        ("private void set(int index, int value) {}", "item[0] = 1;"),
    ),
    ids=("private-getter", "private-setter"),
)
def test_private_index_protocol_methods_require_owner_access(
    semantic_btrcc: Path,
    tmp_path: Path,
    member: str,
    operation: str,
) -> None:
    source = f"class Item {{ {member} }} int main() {{ Item item = new Item(); {operation} return 0; }}"
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "private" in selfhost.stderr.lower()
    assert "private" in reference.stderr.lower()


def test_void_pointer_returns_and_index_getters_are_values(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        void* empty() { return null; }
        class Slots {
            public void* get(int index) { return null; }
        }
        int main() {
            Slots slots = new Slots();
            assert(empty() == null);
            assert(slots[0] == null);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-void-pointer-index")
    _strict_build_and_run(reference_source, tmp_path / "reference-void-pointer-index")


def test_inferred_generic_class_receiver_remains_indexable(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        class Store<T> {
            private T stored;
            public Store(T stored) { self.stored = stored; }
            public T get(int index) { return self.stored; }
            public void set(int index, T value) { self.stored = value; }
        }
        int main() {
            var store = new Store<int>(7);
            assert(store[0] == 7);
            store[0] = 9;
            assert(store[0] == 9);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-inferred-generic-index")
    _strict_build_and_run(reference_source, tmp_path / "reference-inferred-generic-index")


def test_extra_raw_class_indirection_does_not_use_index_protocol(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Store {
            public int get(int index) { return index; }
            public void set(int index, int value) {}
        }
        int main() {
            var slots = (Store**)malloc(sizeof(void*));
            slots[0] = null;
            delete slots;
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-raw-class-index")
    _strict_build_and_run(reference_source, tmp_path / "reference-raw-class-index")


@pytest.mark.parametrize(
    "operation",
    ("int value = sink[0];", "sink[0]++;", "int* value = &sink[0];"),
)
def test_write_only_index_protocol_rejects_reads(
    semantic_btrcc: Path,
    tmp_path: Path,
    operation: str,
) -> None:
    source = f"""
        class Sink<T> {{
            public Sink() {{}}
            public void set(int index, T value) {{}}
        }}
        int main() {{
            Sink<int> sink = new Sink<int>();
            {operation}
            return 0;
        }}
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "indexed getter" in selfhost.stderr
    assert "indexed getter" in reference.stderr


def test_tuple_dynamic_index_is_rejected_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = "int main() { var pair = (1, 2); return pair[0]; }"
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "index" in selfhost.stderr.lower()
    assert "index" in reference.stderr.lower()


def test_address_of_managed_protocol_result_projection_is_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item {
            public int value;
            public Item(int value) { self.value = value; }
        }
        class Store<T> {
            private T stored;
            public Store(T stored) { self.stored = stored; }
            public T get(int index) { return self.stored; }
            public void set(int index, T value) { self.stored = value; }
        }
        int main() {
            Store<Item> store = new Store<Item>(new Item(7));
            int* address = &store[0].value;
            return 0;
        }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "Unary operator '&'" in selfhost.stderr
    assert "Unary operator '&'" in reference.stderr


@pytest.mark.parametrize("mutation", ("store[0] = 2;", "store[0]++;"))
def test_const_protocol_receiver_mutation_is_rejected_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    mutation: str,
) -> None:
    source = f"""
        class Store<T> {{
            private T stored;
            public Store(T stored) {{ self.stored = stored; }}
            public T get(int index) {{ return self.stored; }}
            public void set(int index, T value) {{ self.stored = value; }}
        }}
        int main() {{
            const Store<int> store = new Store<int>(1);
            {mutation}
            return 0;
        }}
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "const" in selfhost.stderr.lower()
    assert "const" in reference.stderr.lower()


def test_explicit_function_address_keeps_function_pointer_type(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int answer() { return 42; }
        int main() {
            var callback = &answer;
            assert(callback() == 42);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-function-address")
    _strict_build_and_run(reference_source, tmp_path / "reference-function-address")
