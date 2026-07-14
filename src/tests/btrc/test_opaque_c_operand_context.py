"""Opaque C operands inherit safe sequencing storage from their context."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.tests.btrc.test_mutex_value_contract import (
    COMPILERS,
    _compile_pair,
    _strict_matrix,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).with_name("fixtures") / "opaque_c_operand_context_runtime.btrc"

pytestmark = pytest.mark.skipif(
    not COMPILERS,
    reason="requires GCC or Clang with strict C11 support",
)


def _assert_contextual_temporary(
    generated: str,
    macro: str,
    c_type: str,
) -> None:
    assignment = re.search(
        rf"\b(__btrc_(?:call_)?operand_\d+)\s*=\s*{re.escape(macro)}\b",
        generated,
    )
    assert assignment is not None, f"{macro} was not sequenced exactly once"
    name = assignment.group(1)
    declaration = re.compile(rf"\b(?:volatile\s+)?{re.escape(c_type)}\s+{re.escape(name)}\s*;")
    assert declaration.search(generated), f"{macro} did not inherit contextual storage type {c_type}"
    assert generated.count(macro) == 2, f"expected one definition and one evaluation of {macro}"


def test_opaque_c_operands_keep_context_and_single_evaluation(
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
        _assert_contextual_temporary(
            generated,
            "OPAQUE_SIGNED_VALUE",
            "long long",
        )
        _assert_contextual_temporary(
            generated,
            "OPAQUE_UNSIGNED_VALUE",
            "unsigned long long",
        )
        _assert_contextual_temporary(
            generated,
            "OPAQUE_POINTER_VALUE",
            "int*",
        )
        _assert_contextual_temporary(
            generated,
            "OPAQUE_WIDE_ADDEND",
            "long long",
        )
        _assert_contextual_temporary(
            generated,
            "OPAQUE_FLAGS",
            "unsigned int",
        )
        _assert_contextual_temporary(
            generated,
            "OPAQUE_POINTER_OFFSET",
            "ptrdiff_t",
        )
        _strict_matrix(artifact, tmp_path)
