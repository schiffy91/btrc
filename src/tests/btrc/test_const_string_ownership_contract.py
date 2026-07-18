"""Const strings keep their qualifier through ownership lowering."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_fixture_pair,
    run_strict_pair,
)
from src.tests.btrc.test_mutex_value_contract import COMPILERS

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).parents[1] / "basics" / "test_const_qualifier.btrc"


def _validate_stdout(output: str) -> None:
    assert output == "PASS: test_const_qualifier\n"


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_const_string_ownership_is_dual_frontend_strict_c11(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(semantic_btrcc, tmp_path, FIXTURE)
    for _frontend, generated in compiled:
        source = generated.read_text()
        assert re.search(r"\bconst char\*(?: volatile)? greeting = ", source)
        assert "__btrc_string_retain(const char* value)" in source
        assert re.search(
            r"const char\* __btrc_scope_released_\d+ = greeting;",
            source,
        )
        assert not re.search(
            r"(?<!const )char\* __btrc_scope_released_\d+ = greeting;",
            source,
        )
    run_strict_pair(
        compiled,
        tmp_path,
        validate_stdout=_validate_stdout,
    )
