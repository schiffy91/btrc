"""Managed ownership across exception unwinds that cross C function frames."""

from pathlib import Path

from src.tests.btrc.runtime_ownership_harness import (
    compile_reference_source,
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import (
    REPO,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = REPO / "src/tests/btrc/fixtures/exception_cross_function_cleanup_runtime.btrc"


def _compile_both(semantic_btrcc: Path, tmp_path: Path):
    source = FIXTURE.read_text()
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = compile_reference_source(tmp_path, source, "exception-cross-function-cleanup")
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_source, reference_source


def test_cross_function_exception_cleanup_is_exact_once(semantic_btrcc: Path, tmp_path: Path) -> None:
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-cross-function-cleanup")
    _strict_build_and_run(reference_source, tmp_path / "reference-cross-function-cleanup")


def test_cross_function_exception_cleanup_is_sanitizer_clean(semantic_btrcc: Path, tmp_path: Path) -> None:
    require_sanitizers(tmp_path)
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    sanitized_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-cross-function-cleanup-san",
    )
    sanitized_build_and_run(
        reference_source,
        tmp_path / "reference-cross-function-cleanup-san",
    )
