"""Parity contracts for physical storage and virtual mutation targets."""

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import _compile_reference_source
from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_owned_receiver_nested_projection_assignment_has_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int destroyed = 0;
        struct Pair { int value; };
        class Holder {
            public Pair pair;
            public Holder() { self.pair = {0}; }
            public void __del__() {
                assert(self.pair.value == 7);
                destroyed++;
            }
        }
        Holder makeHolder() { return new Holder(); }
        int main() {
            makeHolder().pair.value = 7;
            assert(destroyed == 1);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-nested-owned-lvalue")
    _strict_build_and_run(reference_source, tmp_path / "reference-nested-owned-lvalue")


def test_owned_index_preserves_borrowed_receiver_evaluation_order(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int order = 0;
        class Lookup<K, V> {
            public V stored;
            public Lookup(V stored) { self.stored = stored; }
            public V get(K key) {
                assert(sizeof(key) != (size_t)0);
                return self.stored;
            }
            public void set(K key, V value) {
                assert(sizeof(key) != (size_t)0);
                self.stored = value;
            }
        }
        class Holder {
            private Lookup<string, int> stored;
            public Holder() { self.stored = new Lookup<string, int>(0); }
            public Lookup<string, int> receiver {
                get {
                    order = order * 10 + 1;
                    return self.stored;
                }
            }
        }
        string indexProbe() {
            order = order * 10 + 2;
            return "key";
        }
        int main() {
            Holder holder = new Holder();
            holder.receiver[indexProbe()] = 7;
            assert(order == 12);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-owned-index-order")
    _strict_build_and_run(reference_source, tmp_path / "reference-owned-index-order")


TARGET_SHAPES = (
    (
        "function_result",
        """
        struct Pair { int value; };
        Pair makePair() { return {0}; }
        int main() { MUTATION return 0; }
        """,
        "makePair().value",
    ),
    (
        "property_result",
        """
        struct Pair { int value; };
        class Holder {
            private Pair stored;
            public Holder() { self.stored = {0}; }
            public Pair pair { get { return self.stored; } }
        }
        int main() {
            Holder holder = new Holder();
            MUTATION
            return 0;
        }
        """,
        "holder.pair.value",
    ),
    (
        "protocol_result",
        """
        struct Pair { int value; };
        class Store<T> {
            private T stored;
            public Store(T stored) { self.stored = stored; }
            public T get(int index) { return self.stored; }
            public void set(int index, T value) { self.stored = value; }
        }
        int main() {
            Pair initial = {0};
            Store<Pair> store = new Store<Pair>(initial);
            MUTATION
            return 0;
        }
        """,
        "store[0].value",
    ),
    (
        "temporary_array",
        """
        struct Box { int values[2]; };
        Box makeBox() { return {{0, 1}}; }
        int main() { MUTATION return 0; }
        """,
        "makeBox().values[0]",
    ),
)

MUTATIONS = (
    ("assign", "TARGET = 1;", "Assignment target is not assignable"),
    ("compound", "TARGET += 1;", "Assignment target is not assignable"),
    ("prefix", "++TARGET;", "Unary operator '++'"),
    ("postfix", "TARGET++;", "Unary operator '++'"),
    ("address", "int* address = &TARGET;", "Unary operator '&'"),
)


@pytest.mark.parametrize(
    "shape,source,target",
    TARGET_SHAPES,
    ids=[shape[0] for shape in TARGET_SHAPES],
)
@pytest.mark.parametrize(
    "operation,mutation,diagnostic",
    MUTATIONS,
    ids=[mutation[0] for mutation in MUTATIONS],
)
def test_by_value_projection_mutation_is_rejected_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    shape: str,
    source: str,
    target: str,
    operation: str,
    mutation: str,
    diagnostic: str,
) -> None:
    del shape, operation
    program = source.replace("MUTATION", mutation.replace("TARGET", target))
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, program)
    reference, _ = _compile_reference_source(tmp_path, program)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_address_preserving_storage_controls_have_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        struct Box { int values[2]; };
        Box globalBox = {{0, 0}};
        Box* boxPointer() { return &globalBox; }
        int main() {
            Box local = {{1, 2}};
            local.values[0] = 3;
            boxPointer()->values[1] = 4;
            assert(local.values[0] == 3);
            assert(globalBox.values[1] == 4);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    expected_initializer = "static Box globalBox = {{0, 0}};"
    assert expected_initializer in selfhost_source.read_text()
    assert expected_initializer in reference_source.read_text()
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-addressable-controls")
    _strict_build_and_run(reference_source, tmp_path / "reference-addressable-controls")


def test_address_of_owned_temporary_projection_is_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item {
            public int value;
            public Item(int value) { self.value = value; }
        }
        Item makeItem() { return new Item(7); }
        int main() { int* address = &makeItem().value; return 0; }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "Unary operator '&'" in selfhost.stderr
    assert "Unary operator '&'" in reference.stderr


@pytest.mark.parametrize(
    "target",
    ("point.value", "outer.inner.value", "outer.values[0]"),
)
def test_const_receiver_chain_mutation_is_rejected_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    target: str,
) -> None:
    source = f"""
        struct Point {{ int value; }};
        struct Outer {{ Point inner; int values[2]; }};
        int main() {{
            const Point point = {{0}};
            const Outer outer = {{{{0}}, {{0, 1}}}};
            {target} = 7;
            return 0;
        }}
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "const" in selfhost.stderr.lower()
    assert "const" in reference.stderr.lower()


@pytest.mark.parametrize(
    "source,diagnostic",
    (
        ("int foo() { return 1; } int bar() { return 2; } void run() { foo = bar; }", "not assignable"),
        ("enum Color { RED, GREEN }; void run() { RED = GREEN; }", "not assignable"),
        ("enum Color { RED, GREEN }; void run() { Color* value = &RED; }", "Unary operator '&'"),
    ),
)
def test_nonstorage_designators_are_rejected_with_compiler_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr
