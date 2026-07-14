"""Assignment target lifetime and source-order regressions."""

from pathlib import Path

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_assignment_targets_survive_destructive_rhs(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = r"""
        #include <assert.h>

        class Item {
            public int id;
            public Item(int id) { self.id = id; }
            public Item __add__(int delta) {
                return new Item(self.id + delta);
            }
        }

        class Holder {
            public Item item;
            public int scalar;
            public int value { get; set; }
            public Holder(int id) {
                self.item = new Item(id);
                self.scalar = id;
                self.value = id;
            }
        }

        class Bag {
            public int value;
            public Bag(int value) { self.value = value; }
            public int get(int index) { return self.value + index; }
            public void set(int index, int value) {
                self.value = value - index;
            }
            public int index() { return 0; }
        }

        int main() {
            Holder scalarHolder = new Holder(1);
            int scalarResult = (
                scalarHolder.scalar =
                    (scalarHolder = new Holder(2)).scalar
            );
            assert(scalarResult == 2);
            assert(scalarHolder.scalar == 2);

            Holder fieldHolder = new Holder(1);
            Item fieldResult = (
                fieldHolder.item =
                    (fieldHolder = new Holder(2)).item
            );
            assert(fieldResult.id == 2);

            Holder compoundHolder = new Holder(1);
            Item compoundResult = (
                compoundHolder.item +=
                    (compoundHolder = new Holder(2)).scalar
            );
            assert(compoundResult.id == 3);

            Item local = new Item(1);
            local += (local = new Item(2)).id;
            assert(local.id == 3);

            Holder propertyHolder = new Holder(1);
            int propertyResult = (
                propertyHolder.value =
                    (propertyHolder = new Holder(2)).value
            );
            assert(propertyResult == 2);

            Bag bag = new Bag(1);
            int indexedResult = (
                bag[0] = (bag = new Bag(2))[0]
            );
            assert(indexedResult == 2);
            assert(bag[0] == 2);

            Bag indexedTarget = new Bag(1);
            indexedTarget[(indexedTarget = new Bag(2)).index()] = 7;
            assert(indexedTarget[0] == 2);
            return 0;
        }
    """
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-assignment-lifetime",
        toolchain,
    )
    sanitized_build_and_run(
        reference_c,
        tmp_path / "reference-assignment-lifetime",
        toolchain,
    )


def test_compound_update_loads_before_mutating_rhs(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = "int main() { int value = 1; value += value++; return value == 2 ? 0 : 1; }"
    selfhost, selfhost_c = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    toolchain = require_sanitizers(tmp_path)
    sanitized_build_and_run(
        selfhost_c,
        tmp_path / "selfhost-compound-order",
        toolchain,
    )
    sanitized_build_and_run(
        reference_c,
        tmp_path / "reference-compound-order",
        toolchain,
    )
