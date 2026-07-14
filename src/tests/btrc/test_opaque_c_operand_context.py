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
            "OPAQUE_STREAM",
            "OPAQUE_LITERAL_WIDE",
            "OPAQUE_DEPENDENT_VALUE",
        ):
            _assert_inline_once(generated, macro)
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
