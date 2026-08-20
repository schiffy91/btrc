"""Borrowed managed bindings may follow only their own physical storage."""

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


_ITEM = """
    class Item {
        public int id;
        public Item? next;
        public Item? automatic { get; set; }
        public Item(int id, Item? next) {
            self.id = id;
            self.next = next;
            self.automatic = next;
        }
        public Item? custom { get { return self.next; } }
    }
"""


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


def test_parameter_and_capture_follow_own_physical_projection(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = f"""
        #include <assert.h>
        {_ITEM}

        void advanceField(Item? value, Item expected) {{
            value = value.next;
            assert(value == expected);
        }}

        void advanceAutomatic(Item? value, Item expected) {{
            value = value.automatic;
            assert(value == expected);
        }}

        int main() {{
            Item tail = new Item(2, null);
            Item head = new Item(1, tail);
            advanceField(head, tail);
            advanceAutomatic(head, tail);

            Item? fieldCapture = head;
            var followField = () => {{
                fieldCapture = fieldCapture.next;
                assert(fieldCapture == tail);
            }};
            followField();

            Item? automaticCapture = head;
            var followAutomatic = () => {{
                automaticCapture = automaticCapture.automatic;
                assert(automaticCapture == tail);
            }};
            followAutomatic();
            return 0;
        }}
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
        tmp_path / "selfhost-borrowed-projection",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-borrowed-projection",
    )


@pytest.mark.parametrize("binding", ("parameter", "capture"))
@pytest.mark.parametrize(
    "source_expression",
    (
        "value.custom",
        "other.next",
        "new Item(3, null)",
    ),
    ids=("custom-getter", "foreign-owner", "owned-result"),
)
def test_borrowed_projection_rejects_nonphysical_or_foreign_sources(
    semantic_btrcc: Path,
    tmp_path: Path,
    binding: str,
    source_expression: str,
) -> None:
    if binding == "parameter":
        body = f"""
            void reject(Item? value, Item other) {{
                value = {source_expression};
            }}
            int main() {{ return 0; }}
        """
    else:
        body = f"""
            int main() {{
                Item? value = null;
                Item other = new Item(2, null);
                var reject = () => {{ value = {source_expression}; }};
                return 0;
            }}
        """
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        _ITEM + body,
    )


def test_nested_lambda_block_validates_borrowed_capture_rebind(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = f"""
        {_ITEM}

        int main() {{
            Item? value = null;
            var outer = () => {{
                var inner = () => {{ value = value.custom; }};
            }};
            return 0;
        }}
    """
    _assert_rejected_by_both(
        semantic_btrcc,
        tmp_path,
        source,
    )
