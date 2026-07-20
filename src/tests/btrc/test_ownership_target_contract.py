"""Ownership operations require stable, physical target slots."""

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import _compile_reference_source
from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize("operation", ("keep", "release", "delete"))
@pytest.mark.parametrize("target", ("holder.item", "store[0]"))
def test_ownership_ops_reject_virtual_targets(
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


@pytest.mark.parametrize("operation", ("keep", "release", "delete"))
def test_ownership_ops_reject_owned_receiver_fields(
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
