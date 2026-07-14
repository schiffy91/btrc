"""Runtime ownership parity for constructors that throw during init."""

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

FIXTURE = REPO / "src/tests/btrc/fixtures/constructor_throw_ownership_runtime.btrc"


def _compile_both(semantic_btrcc: Path, tmp_path: Path):
    source = FIXTURE.read_text()
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_source = compile_reference_source(tmp_path, source, "constructor-throw")
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_source, reference_source


def test_throwing_constructors_release_partial_objects(semantic_btrcc: Path, tmp_path: Path) -> None:
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-constructor-throw")
    _strict_build_and_run(reference_source, tmp_path / "reference-constructor-throw")


def test_throwing_constructor_ownership_is_sanitizer_clean(semantic_btrcc: Path, tmp_path: Path) -> None:
    require_sanitizers(tmp_path)
    selfhost_source, reference_source = _compile_both(semantic_btrcc, tmp_path)
    sanitized_build_and_run(selfhost_source, tmp_path / "selfhost-constructor-throw-san")
    sanitized_build_and_run(reference_source, tmp_path / "reference-constructor-throw-san")
