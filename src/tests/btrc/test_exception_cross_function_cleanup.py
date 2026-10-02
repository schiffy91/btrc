"""Managed ownership across exception unwinds that cross C function frames."""

from pathlib import Path

from src.tests.btrc.runtime_ownership_harness import (
    compile_reference_source,
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.selfhost_snippet_harness import REPO, compile_source, strict_build_and_run

FIXTURE = REPO / "src/tests/btrc/fixtures/ExceptionCrossFunctionCleanupRuntime.btrc"


def _compile_both(semantic_btrcc: Path, tmp_path: Path):
    source = FIXTURE.read_text()
    selfhost, selfhost_source = compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = compile_reference_source(tmp_path, source, "exception-cross-function-cleanup")
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    emitted = selfhost_source.read_text()
    assert "typedef void* (*__btrc_cleanup_take_fn)(void*);" in emitted
    assert "Token* volatile* typed_slot" in emitted
    assert "__btrc_register_cleanup(((void*)(&" in emitted
    assert "void** ptr_ref" not in emitted
    return selfhost_source, reference_source


def test_cross_function_exception_cleanup_is_exact_once(semantic_btrcc: Path, tmp_path: Path) -> None:
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    strict_build_and_run(selfhost_source, tmp_path / "selfhost-cross-function-cleanup")
    strict_build_and_run(reference_source, tmp_path / "reference-cross-function-cleanup")


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
