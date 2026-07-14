"""Caller/callee ownership-transfer and borrowed-binding regressions."""

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _assert_rejected_by_both(
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


def test_consuming_call_rejects_borrowed_coalesce(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item { public Item() {} }
        void consume(Item value) { release value; }
        int main() {
            Item first = new Item();
            Item second = new Item();
            consume(first ?? second);
            return 0;
        }
    """
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        source,
        "must be a fresh caller-owned managed value",
    )


def test_consuming_call_promotes_mixed_owned_conditionals(
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
        void consume(Item value) { release value; }
        int main() {
            Item borrowed = new Item();
            consume(true ? new Item() : borrowed);
            assert(alive == 1);
            consume(false ? new Item() : borrowed);
            assert(alive == 1);
            return 0;
        }
    """
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_c, tmp_path / "selfhost-mixed-consume")
    _strict_build_and_run(reference_c, tmp_path / "reference-mixed-consume")


def test_fstring_cannot_replace_borrowed_parameter(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        void replace(string value) { value = f"owned-{value}"; }
        int main() { replace("borrowed"); return 0; }
    """
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        source,
        "Borrowed managed bindings cannot be rebound",
    )


def test_shorter_lived_owner_cannot_replace_borrowed_parameter(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item { public Item() {} }
        void inspect(Item borrowed) {
            Item owner = new Item();
            borrowed = owner;
        }
        int main() {
            Item item = new Item();
            inspect(item);
            return 0;
        }
    """
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        source,
        "Borrowed managed bindings cannot be rebound",
    )


def test_managed_static_local_is_rejected_until_lifetime_is_supported(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item { public Item() {} }
        int touch() {
            static Item item = null;
            return item == null ? 0 : 1;
        }
        int main() { return touch(); }
    """
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        source,
        "cannot use managed static-local storage",
    )


def test_managed_string_pointer_arithmetic_is_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        string tail() {
            string base = "abcdef".substring(0, 6);
            return base + 1;
        }
        int main() { return 0; }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "operator '+' is not defined" in selfhost.stderr.lower()
    assert "operator '+' is not defined" in reference.stderr.lower()


@pytest.mark.parametrize("operation", ("release", "delete"))
def test_managed_receiver_cannot_be_consumed(
    semantic_btrcc: Path,
    tmp_path: Path,
    operation: str,
) -> None:
    source = f"""
        class Item {{
            public Item() {{}}
            public void consume() {{ {operation} self; }}
        }}
        int main() {{ Item value = new Item(); value.consume(); return 0; }}
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "cannot" in selfhost.stderr.lower()
    assert "cannot" in reference.stderr.lower()


def test_conditional_parameter_consumption_is_rejected(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item { public Item() {} }
        void maybeConsume(Item value, bool flag) {
            if (flag) { release value; }
        }
        int main() { maybeConsume(new Item(), true); return 0; }
    """
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        source,
        "must be an unconditional leading release/delete",
    )


def test_raw_array_loop_binding_cannot_take_fresh_owner(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Item { public Item() {} }
        int main() {
            Item owner = new Item();
            Item values[1] = {owner};
            for value in values { value = new Item(); }
            return 0;
        }
    """
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        source,
        "Borrowed managed bindings cannot be rebound",
    )


def test_consuming_handoff_is_cleared_before_a_throwing_call(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Bomb {
            public Bomb() {}
            public void __del__() { throw "boom"; }
        }
        void consume(Bomb value) { release value; }
        int main() {
            try {
                consume(new Bomb());
            } catch (string error) {
                return error == "boom" ? 0 : 2;
            }
            return 1;
        }
    """
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_c, tmp_path / "selfhost-throwing-handoff")
    _strict_build_and_run(reference_c, tmp_path / "reference-throwing-handoff")
