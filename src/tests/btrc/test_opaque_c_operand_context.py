"""Opaque C operands retain their native types across ordered boundaries."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import (
    COMPILERS,
    _compile_pair,
    _strict_matrix,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).with_name("fixtures") / "opaque_c_operand_context_runtime.btrc"
LEADING_FIXTURE = Path(__file__).with_name("fixtures") / "opaque_c_operand_leading_invalid.btrc"
CALL_LEADING_FIXTURE = Path(__file__).with_name("fixtures") / "opaque_c_call_leading_invalid.btrc"
READ_LEADING_FIXTURE = Path(__file__).with_name("fixtures") / "opaque_c_operand_read_invalid.btrc"

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires GCC or Clang with strict C11 support",
)


def _assert_inline_once(generated: str, macro: str) -> None:
    assert not re.search(
        rf"\b__btrc_(?:call_)?operand_\d+\s*=\s*{re.escape(macro)}\b",
        generated,
    ), f"opaque value {macro} was materialized through an invented C type"
    assert generated.count(macro) == 2, f"expected one definition and one evaluation of {macro}"


def _assert_contextually_typed_once(generated: str, macro: str, c_type: str) -> None:
    operand = r"__btrc_(?:call_)?operand_\d+"
    assert re.search(rf"\b{re.escape(c_type)}\s+{operand}\s*;", generated)
    assert re.search(rf"\b{operand}\s*=\s*{re.escape(macro)}\b", generated)
    assert generated.count(macro) == 2, f"expected one definition and one evaluation of {macro}"


def test_opaque_c_operands_preserve_type_and_single_evaluation(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURE.read_text(),
        "opaque-c-operand-context",
    )
    for artifact in compiled:
        generated = artifact[1].read_text()
        for macro in (
            "OPAQUE_SIGNED_VALUE",
            "OPAQUE_POINTER_VALUE",
            "OPAQUE_WIDE_ADDEND",
            "OPAQUE_FLAGS",
            "OPAQUE_POINTER_OFFSET",
            "OPAQUE_ADVERSARIAL_WIDE",
            "OPAQUE_LITERAL_WIDE",
            "OPAQUE_DEPENDENT_VALUE",
        ):
            _assert_inline_once(generated, macro)
        # fputs has an exact hosted ABI contract, so its second operand is no
        # longer untyped: materializing it as the declared FILE* parameter type
        # is the same conversion the C call performs and preserves ordering.
        _assert_contextually_typed_once(generated, "OPAQUE_STREAM", "FILE*")
        _strict_matrix(artifact, tmp_path)


def test_native_field_macro_boundary_requires_explicit_type_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <termios.h>
        int main() {
            struct termios attributes;
            attributes.c_lflag = attributes.c_lflag | ECHO;
            return 0;
        }
    """
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "opaque C operand at" in result.stderr
        assert "operator '|'" in result.stderr
        assert "cast it explicitly" in result.stderr


def test_typed_native_field_macro_boundary_runs_strictly_in_both_frontends(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <termios.h>
        int main() {
            struct termios attributes;
            attributes.c_lflag = (tcflag_t)ECHO | (tcflag_t)ECHONL;
            attributes.c_lflag = (tcflag_t)attributes.c_lflag
                & ~((tcflag_t)ECHO | (tcflag_t)ECHONL);
            return attributes.c_lflag == (tcflag_t)0 ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "typed-native-field-macro-boundary",
    ):
        generated = artifact[1].read_text()
        assert re.search(
            r"\btcflag_t\s+__btrc_(?:call_)?operand_\d+\s*;",
            generated,
        )
        _strict_matrix(artifact, tmp_path)


@pytest.mark.parametrize(
    ("fixture", "context"),
    [
        (LEADING_FIXTURE, "operator '>'"),
        (READ_LEADING_FIXTURE, "operator '=='"),
        (CALL_LEADING_FIXTURE, "call arguments"),
    ],
)
def test_leading_opaque_c_operand_requires_an_explicit_type(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture: Path,
    context: str,
) -> None:
    source = fixture.read_text()
    selfhost, _ = _compile_source(semantic_btrcc, tmp_path, source)
    reference, _ = _compile_reference_source(tmp_path, source)
    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "opaque C operand at" in result.stderr
        assert "precedes an ordered sibling" in result.stderr
        assert context in result.stderr
        assert "cast it explicitly" in result.stderr
