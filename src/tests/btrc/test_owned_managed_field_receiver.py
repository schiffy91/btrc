"""Runtime parity for managed stores through owned field receivers."""

from pathlib import Path

from src.tests.btrc.test_ownership_semantics_contract import _compile_reference_source
from src.tests.btrc.test_semantic_validation import _compile_source, _strict_build_and_run

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_owned_managed_field_receiver_is_released_once(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        #include <string.h>
        int itemDrops = 0;
        int holderDrops = 0;
        class Item {
            public string label;
            public Item(string label) { self.label = label; }
            public void __del__() { itemDrops++; }
        }
        class Holder {
            public Item item;
            public Holder() { self.item = new Item("initial"); }
            public void __del__() { holderDrops++; }
        }
        class Store {
            public Item item;
            public Store() { self.item = new Item("old"); }
            public Item get() { return self.item; }
        }
        Holder makeHolder() { return new Holder(); }
        int main() {
            Item replacement = new Item("replacement");
            makeHolder().item = replacement;
            assert(holderDrops == 1);
            assert(itemDrops == 1);

            Store values = new Store();
            values.get().label = "new";
            assert(strcmp(values.get().label, "new") == 0);
            return 0;
        }
    """
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-owned-managed-field")
    _strict_build_and_run(reference_source, tmp_path / "reference-owned-managed-field")
