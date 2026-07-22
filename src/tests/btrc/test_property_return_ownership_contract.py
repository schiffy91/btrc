"""Dual-frontend ownership contracts for custom property projections."""

from pathlib import Path

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _strict_dual_frontend_runtime(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    stem: str,
) -> None:
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(
        selfhost_source,
        tmp_path / f"selfhost-{stem}",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / f"reference-{stem}",
    )


def test_managed_custom_self_property_return_has_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int alive = 0;
        class Item {
            public Item() { alive++; }
            public void __del__() { alive--; }
        }
        class Owner {
            private Item stored;
            public Owner() { self.stored = new Item(); }
            public Item current { get { return self.stored; } }
            public Item read() { return self.current; }
        }
        int main() {
            {
                Owner owner = new Owner();
                {
                    Item item = owner.read();
                    assert(alive == 1);
                }
                assert(alive == 1);
            }
            assert(alive == 0);
            return 0;
        }
    """
    _strict_dual_frontend_runtime(
        semantic_btrcc,
        tmp_path,
        source,
        "managed-self-property",
    )


def test_generic_managed_custom_self_property_return_has_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int alive = 0;
        class Item {
            public Item() { alive++; }
            public void __del__() { alive--; }
        }
        class Owner<T> {
            private Item stored;
            public Owner() { self.stored = new Item(); }
            public Item current { get { return self.stored; } }
            public Item read() { return self.current; }
        }
        int main() {
            {
                Owner<int> owner = new Owner<int>();
                {
                    Item item = owner.read();
                    assert(alive == 1);
                }
                assert(alive == 1);
            }
            assert(alive == 0);
            return 0;
        }
    """
    _strict_dual_frontend_runtime(
        semantic_btrcc,
        tmp_path,
        source,
        "generic-managed-self-property",
    )


def test_super_properties_use_parent_accessors_with_runtime_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int alive = 0;
        class Item {
            public Item() { alive++; }
            public void __del__() { alive--; }
        }
        class BaseOwner {
            public Item stored;
            public int scalar;
            public Item current { get { return self.stored; } }
            public int answer { get { return self.scalar; } }
        }
        class ChildOwner extends BaseOwner {
            public ChildOwner() {
                self.stored = new Item();
                self.scalar = 42;
            }
            public Item readManaged() { return super.current; }
            public int readScalar() { return super.answer; }
        }
        int main() {
            {
                ChildOwner owner = new ChildOwner();
                assert(owner.readScalar() == 42);
                {
                    Item item = owner.readManaged();
                    assert(alive == 1);
                }
                assert(alive == 1);
            }
            assert(alive == 0);
            return 0;
        }
    """
    _strict_dual_frontend_runtime(
        semantic_btrcc,
        tmp_path,
        source,
        "super-properties",
    )
