"""First-class ARC-node contracts for ``Mutex<T>``."""

from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import (
    COMPILERS,
    REPO,
    _build_and_run,
    _compile_pair,
    _strict_matrix,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires a pthread C11 compiler",
)


def test_selfhost_mutex_transport_storage_resolves_active_specialization() -> None:
    source = (REPO / "src/compiler/btrc/ir/lowering/concurrency.btrc").read_text().expandtabs(4)
    start = source.index("    public string threadResultStorageC(")
    end = source.index("\n    }", start)
    storage = source[start:end]

    assert "self.cTypes.resolveBodyType(" in storage
    assert "self.context.activeTypeMap" in storage
    assert "TypeShape.copy(concreteType)" in storage
    assert "TypeShape.copy(resultType)" not in storage


def _optimization_matrix(compiled, tmp_path):
    for compiler in COMPILERS:
        for level in range(4):
            output = tmp_path / (f"{compiled[0]}-{Path(compiler).name}-O{level}")
            _build_and_run(
                compiled[1],
                output,
                compiler,
                (f"-O{level}",),
            )


def test_mutex_receiver_and_argument_evaluation_is_source_ordered(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int main() {
            Mutex<int> left = Mutex(1);
            Mutex<int> right = Mutex(2);
            (left = right).set(left.get());
            assert(right.get() == 2);
            left.destroy();
            right.destroy();
            return 0;
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "mutex-call-order",
    )
    for artifact in compiled:
        _optimization_matrix(artifact, tmp_path)


def test_mutex_inside_generic_methods_preserves_payload_ownership(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int alive = 0;

        class Item {
            public int id;
            public Item(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
        }

        class Harness<T> {
            public Harness() {}
            public T roundtrip(T input) {
                Mutex<T> value = Mutex(input);
                T snapshot = value.get();
                value.set(input);
                value.destroy();
                return snapshot;
            }
        }

        void exerciseManaged() {
            Harness<Item> harness = new Harness<Item>();
            Item source = new Item(7);
            Item snapshot = harness.roundtrip(source);
            assert(snapshot.id == 7);
            assert(alive == 1);
        }

        int main() {
            Harness<int> integers = new Harness<int>();
            assert(integers.roundtrip(42) == 42);
            exerciseManaged();
            assert(alive == 0);
            return 0;
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "mutex-generic-method",
    )
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)
