"""Executable ownership contracts for target-directed class-to-string coercion."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.string_coercion_harness import (
    assert_tracked_strict_pair,
)
from src.tests.btrc.test_mutex_value_contract import COMPILERS
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)
pytestmark = pytest.mark.skipif(not COMPILERS, reason="requires a C11 compiler")

FIXTURES = Path(__file__).with_name("fixtures")
RUNTIME_CASES = (
    ("string_coercion_storage_runtime.btrc", False, None),
    ("string_coercion_virtual_assignment_runtime.btrc", False, None),
    ("string_coercion_calls_runtime.btrc", False, "1015\n2015\n"),
    ("string_coercion_collections_runtime.btrc", True, None),
    ("string_coercion_exception_runtime.btrc", True, None),
)


@pytest.mark.parametrize(
    ("fixture_name", "include_stdlib", "expected_stdout"),
    RUNTIME_CASES,
)
def test_target_string_coercion_is_exactly_owned_across_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
    include_stdlib: bool,
    expected_stdout: str | None,
) -> None:
    assert_tracked_strict_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURES / fixture_name,
        include_stdlib=include_stdlib,
        expected_stdout=expected_stdout,
    )


@pytest.mark.parametrize(
    "source",
    (
        pytest.param(
            """
            class Label {
                public Label() {}
                public string toString() { return "global"; }
            }
            string globalLabel = new Label();
            int main() { return 0; }
            """,
            id="global",
        ),
        pytest.param(
            """
            class Label {
                public Label() {}
                public string toString() { return "static"; }
            }
            class Globals { class string label = new Label(); }
            int main() { return 0; }
            """,
            id="class-static",
        ),
    ),
)
def test_runtime_string_conversion_is_rejected_in_static_storage(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "initializer" in result.stderr.lower()
        assert "constant" in result.stderr.lower()


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        pytest.param(
            """
            class Label {
                public Label() {}
                public string toString() { return "source pointer"; }
            }
            int main() {
                Label** pointer = null;
                string text = pointer;
                return 0;
            }
            """,
            "Cannot assign",
            id="raw-class-pointer-source",
        ),
        pytest.param(
            """
            class Label {
                public Label() {}
                public string toString() { return "target pointer"; }
            }
            int main() {
                string* text = new Label();
                return 0;
            }
            """,
            "Cannot assign",
            id="raw-string-pointer-target",
        ),
        pytest.param(
            """
            class Label {
                public Label() {}
                public string toString() { return "array"; }
            }
            int main() {
                Label values[1];
                string text = values;
                return 0;
            }
            """,
            "Cannot assign",
            id="class-array",
        ),
    ),
)
def test_pointer_and_array_shapes_do_not_inherit_scalar_string_conversion(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert diagnostic in result.stderr


def test_converted_value_cannot_rebind_borrowed_string_parameter(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Label {
            public Label() {}
            public string toString() { return "borrowed"; }
        }
        void invalid(string borrowed, Label replacement) {
            borrowed = replacement;
        }
        int main() { return 0; }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "Borrowed managed bindings cannot be rebound" in result.stderr


def test_converted_value_cannot_hide_in_shallow_array_field(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Label {
            public Label() {}
            public string toString() { return "array"; }
        }
        int main() {
            string values[1] = [new Label()];
            return 0;
        }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    for result in (selfhost, reference):
        diagnostic = result.stderr.lower()
        assert result.returncode != 0
        assert "class-to-string" in diagnostic
        assert "shallow" in diagnostic
