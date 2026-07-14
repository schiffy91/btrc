"""Exact-once ownership contracts for managed ``for-in`` iterables."""

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

FIXTURE = REPO / "src/tests/btrc/fixtures/forin_owned_iterable_runtime.btrc"
BINDING_FIXTURE = REPO / "src/tests/btrc/fixtures/forin_managed_binding_runtime.btrc"
BORROWED_FIXTURE = REPO / "src/tests/btrc/fixtures/forin_borrowed_iterable_runtime.btrc"


def _compile_both(semantic_btrcc: Path, tmp_path: Path, fixture=FIXTURE):
    source = fixture.read_text()
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = compile_reference_source(tmp_path, source, "forin-owned-iterable")
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_source, reference_source


def test_fresh_forin_iterables_release_on_every_exit(semantic_btrcc: Path, tmp_path: Path) -> None:
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-forin-owned")
    _strict_build_and_run(reference_source, tmp_path / "reference-forin-owned")


def test_fresh_forin_iterables_are_sanitizer_clean(semantic_btrcc: Path, tmp_path: Path) -> None:
    require_sanitizers(tmp_path)
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    sanitized_build_and_run(selfhost_source, tmp_path / "selfhost-forin-owned-san")
    sanitized_build_and_run(reference_source, tmp_path / "reference-forin-owned-san")


def test_borrowed_forin_iterables_survive_destructive_body_effects(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path, BORROWED_FIXTURE)
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-forin-borrowed")
    _strict_build_and_run(reference_source, tmp_path / "reference-forin-borrowed")


def test_borrowed_forin_iterables_are_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    require_sanitizers(tmp_path)
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path, BORROWED_FIXTURE)
    sanitized_build_and_run(selfhost_source, tmp_path / "selfhost-forin-borrowed-san")
    sanitized_build_and_run(reference_source, tmp_path / "reference-forin-borrowed-san")


def test_managed_forin_bindings_release_on_every_exit(semantic_btrcc: Path, tmp_path: Path) -> None:
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path, BINDING_FIXTURE)
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-forin-bindings")
    _strict_build_and_run(reference_source, tmp_path / "reference-forin-bindings")


def test_managed_forin_bindings_are_sanitizer_clean(semantic_btrcc: Path, tmp_path: Path) -> None:
    require_sanitizers(tmp_path)
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path, BINDING_FIXTURE)
    sanitized_build_and_run(selfhost_source, tmp_path / "selfhost-forin-bindings-san")
    sanitized_build_and_run(reference_source, tmp_path / "reference-forin-bindings-san")
