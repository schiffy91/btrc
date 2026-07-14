"""Read/write protocol parity for indexed class instances."""

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import _compile_reference_source
from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


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


@pytest.mark.parametrize("operation", ("release", "delete"))
@pytest.mark.parametrize("target", ("holder.item", "store[0]"))
def test_consuming_ownership_ops_reject_virtual_targets(
    semantic_btrcc: Path,
    tmp_path: Path,
    operation: str,
    target: str,
) -> None:
    source = f"""
        class Item {{ public Item() {{}} }}
        class Holder {{
            private Item stored;
            public Holder(Item stored) {{ self.stored = stored; }}
            public Item item {{ get {{ return self.stored; }} }}
        }}
        class Store<T> {{
            private T stored;
            public Store(T stored) {{ self.stored = stored; }}
            public T get(int index) {{ return self.stored; }}
            public void set(int index, T value) {{ self.stored = value; }}
        }}
        int main() {{
            Item item = new Item();
            Holder holder = new Holder(item);
            Store<Item> store = new Store<Item>(item);
            {operation} {target};
            return 0;
        }}
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    diagnostic = "cannot target a property or protocol index"
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


@pytest.mark.parametrize("operation", ("release", "delete"))
def test_consuming_ownership_ops_reject_owned_receiver_fields(
    semantic_btrcc: Path,
    tmp_path: Path,
    operation: str,
) -> None:
    source = f"""
        class Item {{ public Item() {{}} }}
        class Holder {{
            public Item item;
            public Holder() {{ self.item = new Item(); }}
        }}
        Holder makeHolder() {{ return new Holder(); }}
        int main() {{ {operation} makeHolder().item; return 0; }}
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    diagnostic = "requires storage rooted in a stable owner"
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_delete_side_effectful_physical_lvalue_runs_once(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int indexCalls = 0;
        int nextIndex() { indexCalls++; return 0; }
        int main() {
            void* slots[1] = {malloc(4)};
            delete slots[nextIndex()];
            assert(indexCalls == 1);
            assert(slots[0] == null);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-delete-once")
    _strict_build_and_run(reference_source, tmp_path / "reference-delete-once")


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
