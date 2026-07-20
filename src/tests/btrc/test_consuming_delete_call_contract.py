"""A delete-consuming parameter accepts only a fresh caller-owned value."""

from pathlib import Path

from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def test_delete_consumer_rejects_a_borrowed_local(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item { public Item() {} }
        void consume(Item value) { delete value; }
        int main() {
            Item owner = new Item();
            consume(owner);
            return 0;
        }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    diagnostic = "must be a fresh caller-owned managed value"
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_delete_consumer_accepts_a_fresh_owner(
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
        void consume(Item value) { delete value; }
        int main() {
            consume(new Item());
            assert(alive == 0);
            return 0;
        }
    """
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_c, tmp_path / "selfhost-fresh-delete")
    _strict_build_and_run(reference_c, tmp_path / "reference-fresh-delete")
