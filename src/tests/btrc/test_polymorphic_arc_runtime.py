"""Runtime ownership remains concrete across statically dispatched base types."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from src.tests.btrc.runtime_ownership_harness import (
    compile_reference_source,
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import REPO, _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = REPO / "src/tests/btrc/fixtures/polymorphic_arc_runtime.btrc"
STRICT_COMPILERS = tuple(compiler for name in ("gcc", "clang") if (compiler := shutil.which(name)) is not None)


def _compile_both(semantic_btrcc: Path, tmp_path: Path):
    source = FIXTURE.read_text()
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
        no_stdlib=False,
    )
    reference, reference_source = compile_reference_source(
        tmp_path,
        source,
        "polymorphic-arc",
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_source, reference_source


def _strict_build_and_run(
    compiler: str,
    generated: Path,
    executable: Path,
) -> None:
    build = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(generated),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stderr
    run = subprocess.run(
        [str(executable)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stderr


def test_polymorphic_owners_destroy_and_visit_concrete_values(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    selfhost_source, reference_source = _compile_both(
        semantic_btrcc,
        tmp_path,
    )
    assert STRICT_COMPILERS, "strict C compiler required"
    for compiler in STRICT_COMPILERS:
        name = Path(compiler).name
        _strict_build_and_run(
            compiler,
            selfhost_source,
            tmp_path / f"selfhost-polymorphic-{name}",
        )
        _strict_build_and_run(
            compiler,
            reference_source,
            tmp_path / f"reference-polymorphic-{name}",
        )


def test_polymorphic_owners_are_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    require_sanitizers(tmp_path)
    selfhost_source, reference_source = _compile_both(
        semantic_btrcc,
        tmp_path,
    )
    sanitized_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-polymorphic-san",
    )
    sanitized_build_and_run(
        reference_source,
        tmp_path / "reference-polymorphic-san",
    )
