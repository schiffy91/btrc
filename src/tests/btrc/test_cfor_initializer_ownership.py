"""Exact lexical ownership for ordinary C-style for initializers."""

from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_diagnostic_pair,
    compile_fixture_pair,
    run_strict_pair,
)
from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import REPO

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = REPO / "src/tests/btrc/fixtures/cfor_initializer_ownership_runtime.btrc"


def _compile_both(semantic_btrcc: Path, tmp_path: Path):
    return compile_fixture_pair(semantic_btrcc, tmp_path, FIXTURE)


def test_initializer_owners_release_exactly_once_on_every_exit(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    run_strict_pair(_compile_both(semantic_btrcc, tmp_path), tmp_path)


def test_initializer_owners_are_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    require_sanitizers(tmp_path)
    for frontend, generated in _compile_both(semantic_btrcc, tmp_path):
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-cfor-initializer-san",
        )


@pytest.mark.parametrize(
    "declaration, diagnostic",
    [
        (
            "static int index = 0",
            "C-style for initializer cannot use static or extern storage",
        ),
        (
            "extern int index",
            "C-style for initializer cannot use static or extern storage",
        ),
        (
            "int values[1] = {0}",
            "Expected SEMICOLON, got LBRACKET",
        ),
    ],
)
def test_unsupported_initializer_storage_fails_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    declaration: str,
    diagnostic: str,
) -> None:
    source = f"int main() {{ for ({declaration}; false; ) {{}} return 0; }}"
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert diagnostic in result.stderr
