"""Borrowed ownership contracts for lifted lambda bindings."""

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
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert "Borrowed managed" in selfhost.stderr
    assert "Borrowed managed" in reference.stderr


def test_lambda_capture_cannot_take_ownership_on_rebind(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        """
        class Item { public Item() {} }
        int main() {
            Item value = new Item();
            var replace = () => { value = new Item(); };
            return 0;
        }
        """,
    )


@pytest.mark.parametrize("operation", ("release", "delete"))
@pytest.mark.parametrize("binding", ("capture", "parameter"))
def test_lambda_borrowed_binding_cannot_be_consumed(
    semantic_btrcc: Path,
    tmp_path: Path,
    operation: str,
    binding: str,
) -> None:
    if binding == "capture":
        declaration = "Item value = new Item();"
        callback = f"var drop = () => {{ {operation} value; }};"
    else:
        declaration = ""
        callback = (
            f"var drop = (Item value) => {{ {operation} value; }};"
        )
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        f"""
        class Item {{ public Item() {{}} }}
        int main() {{
            {declaration}
            {callback}
            return 0;
        }}
        """,
    )


def test_borrowed_capture_rebind_stays_raw_with_same_named_global(
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

        Item? value = null;
        void verifyGlobal() { assert(value == null); }

        int main() {
            verifyGlobal();
            Item value = new Item(1);
            Item other = new Item(2);
            var replace = () => { value = other; };
            replace();
            assert(alive == 2);
            return 0;
        }
    """
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
        tmp_path / "selfhost-lambda-borrow",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-lambda-borrow",
    )


def test_inline_lambda_infers_generic_method_return_type(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        class Holder<T> {
            public T value;
            public Holder(T value) { self.value = value; }
            public U transform<U>(__fn_ptr<U, T> fn) {
                return fn(self.value);
            }
        }

        int main() {
            Holder<int> holder = new Holder<int>(21);
            int doubled = holder.transform((int value) => value * 2);
            assert(doubled == 42);
            return 0;
        }
    """
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
        tmp_path / "selfhost-generic-lambda",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-generic-lambda",
    )
