"""Static-field reads and stores inside monomorphized generic methods."""

from pathlib import Path

from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_generic_method_lowers_scalar_and_managed_static_fields(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        int alive = 0;
        class Item {
            public int value;
            public Item(int value) { self.value = value; alive++; }
            public void __del__() { alive--; }
        }
        class Globals {
            class int calls = 0;
            class Item shared = null;
        }
        class Installer<T> {
            public Installer() {}
            public int install(Item value) {
                Globals.calls = Globals.calls + 1;
                Globals.shared = value;
                return Globals.calls;
            }
            public void clear() { Globals.shared = null; }
        }
        int main() {
            Installer<int> installer = Installer();
            assert(installer.install(new Item(1)) == 1);
            assert(alive == 1 && Globals.shared.value == 1);
            assert(installer.install(new Item(2)) == 2);
            assert(alive == 1 && Globals.shared.value == 2);
            installer.clear();
            assert(alive == 0 && Globals.shared == null);
            return 0;
        }
    """
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    emitted = selfhost_c.read_text()
    borrowed_store = next(
        line
        for line in emitted.splitlines()
        if "__btrc_store_value" in line and " = value)" in line and "Globals_shared" in line
    )
    assert "__btrc_arc_retain(" in borrowed_store
    assert "__btrc_arc_replace_edge" not in emitted
    _strict_build_and_run(selfhost_c, tmp_path / "selfhost-static-fields")
    _strict_build_and_run(reference_c, tmp_path / "reference-static-fields")


def test_static_managed_strong_slot_preserves_exact_ownership(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int alive = 0;
        int produced = 0;

        class Item {
            public int value;
            public Item(int value) { self.value = value; alive++; }
            public void __del__() { alive--; }
        }

        class Globals {
            class Item shared = null;
        }

        Item makeItem(int value) {
            produced++;
            return new Item(value);
        }

        int main() {
            Item first = new Item(1);
            Globals.shared = first;
            assert(alive == 1 && Globals.shared == first);

            Globals.shared = Globals.shared;
            assert(alive == 1 && Globals.shared == first);

            Globals.shared = makeItem(2);
            assert(produced == 1);
            assert(alive == 2 && Globals.shared.value == 2);

            assert((Globals.shared = makeItem(3)).value == 3);
            assert(produced == 2);
            assert(alive == 2 && Globals.shared.value == 3);

            Globals.shared = null;
            assert(alive == 1 && Globals.shared == null);
            delete first;
            assert(alive == 0);
            return 0;
        }
    """
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    emitted = selfhost_c.read_text()
    borrowed_store = next(
        line
        for line in emitted.splitlines()
        if "__btrc_store_value" in line and " = first)" in line and "Globals_shared" in line
    )
    self_store = next(
        line
        for line in emitted.splitlines()
        if "__btrc_store_value" in line and " = Globals_shared)" in line and "Globals_shared" in line
    )
    fresh_store = next(line for line in emitted.splitlines() if "makeItem(2)" in line)
    assert "__btrc_arc_retain(" in borrowed_store
    assert "__btrc_arc_retain(" in self_store
    assert "__btrc_arc_retain(" not in fresh_store
    assert emitted.count("makeItem(2)") == 1
    assert emitted.count("makeItem(3)") == 1
    assert "__btrc_arc_replace_edge" not in emitted
    _strict_build_and_run(selfhost_c, tmp_path / "selfhost-static-managed-strong-slot")
    _strict_build_and_run(reference_c, tmp_path / "reference-static-managed-strong-slot")
