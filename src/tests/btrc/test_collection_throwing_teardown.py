"""Exception-safe explicit teardown contracts for stdlib collections."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.collection_teardown_harness import (
    compile_stdlib_pair,
    run_strict_matrix,
)
from src.tests.btrc.runtime_ownership_harness import (
    SanitizerToolchain,
    require_sanitizers,
    sanitized_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")
CASES = (
    "collection_throwing_vector_runtime.btrc",
    "collection_throwing_array_runtime.btrc",
    "collection_throwing_map_runtime.btrc",
    "collection_throwing_set_runtime.btrc",
    "collection_throwing_list_runtime.btrc",
)


@pytest.fixture(scope="module")
def compiled_cases(
    semantic_btrcc: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, tuple[Path, tuple[tuple[str, Path], ...]]]:
    compiled = {}
    for fixture_name in CASES:
        output = tmp_path_factory.mktemp(Path(fixture_name).stem)
        artifacts = compile_stdlib_pair(
            semantic_btrcc,
            output,
            FIXTURES / fixture_name,
        )
        compiled[fixture_name] = output, artifacts
    return compiled


@pytest.fixture(scope="module")
def sanitizer_toolchain(
    tmp_path_factory: pytest.TempPathFactory,
) -> SanitizerToolchain:
    return require_sanitizers(tmp_path_factory.mktemp("collection-teardown-san"))


@pytest.mark.parametrize("fixture_name", CASES)
def test_throwing_free_is_strict_and_has_dual_frontend_parity(
    compiled_cases: dict[str, tuple[Path, tuple[tuple[str, Path], ...]]],
    fixture_name: str,
) -> None:
    output, artifacts = compiled_cases[fixture_name]
    run_strict_matrix(artifacts, output)


@pytest.mark.parametrize("fixture_name", CASES)
def test_throwing_free_is_sanitizer_clean(
    compiled_cases: dict[str, tuple[Path, tuple[tuple[str, Path], ...]]],
    sanitizer_toolchain: SanitizerToolchain,
    fixture_name: str,
) -> None:
    # LeakSanitizer is disabled by the shared portable harness. The fixtures
    # prove logical reclamation with counters and cleared backing topology;
    # ASan/UBSan still detect double-free, use-after-free, and invalid access.
    output, artifacts = compiled_cases[fixture_name]
    for frontend, generated in artifacts:
        sanitized_build_and_run(
            generated,
            output / f"{frontend}-{Path(fixture_name).stem}-san",
            sanitizer_toolchain,
        )
