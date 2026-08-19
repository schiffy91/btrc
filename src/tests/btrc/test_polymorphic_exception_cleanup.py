"""Exception cleanup must follow the concrete ARC type in both compilers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.runtime.generated import RUNTIME_HELPER_ROWS
from src.tests.btrc.runtime_ownership_harness import (
    compile_reference_source,
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_semantic_validation import REPO, _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = REPO / "src/tests/btrc/fixtures/polymorphic_exception_cycle_cleanup_runtime.btrc"
STRICT_COMPILERS = tuple(compiler for name in ("gcc", "clang") if (compiler := shutil.which(name)) is not None)


def test_both_cleanup_runtimes_dispatch_through_concrete_arc_metadata() -> None:
    helpers = {row.name: row for row in RUNTIME_HELPER_ROWS}
    cleanup = helpers["__btrc_run_cleanup_guarded"]

    assert "__btrc_arc_release(object, &type);" in cleanup.c_source
    assert "if (entry.visit)" not in cleanup.c_source
    assert "__btrc_arc_release_acyclic" not in cleanup.c_source
    assert "__btrc_arc_release" in cleanup.depends_on
    assert "__btrc_arc_release_acyclic" not in cleanup.depends_on


@pytest.mark.skipif(
    not STRICT_COMPILERS,
    reason="requires a hosted strict C11 compiler",
)
def test_polymorphic_exception_cleanup_collects_runtime_subclass_cycles(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = FIXTURE.read_text()
    selfhost_result, selfhost_generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference_result, reference_generated = compile_reference_source(
        tmp_path,
        source,
        "polymorphic-exception-cleanup",
    )
    assert selfhost_result.returncode == 0, selfhost_result.stderr
    assert reference_result.returncode == 0, reference_result.stderr

    for frontend, generated in (
        ("selfhost", selfhost_generated),
        ("reference", reference_generated),
    ):
        for compiler in STRICT_COMPILERS:
            executable = tmp_path / f"{frontend}-polymorphic-cleanup-{Path(compiler).name}"
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
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


def test_polymorphic_exception_cleanup_is_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    toolchain = require_sanitizers(tmp_path)
    source = FIXTURE.read_text()
    selfhost_result, selfhost_generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference_result, reference_generated = compile_reference_source(
        tmp_path,
        source,
        "polymorphic-exception-cleanup-sanitized",
    )
    assert selfhost_result.returncode == 0, selfhost_result.stderr
    assert reference_result.returncode == 0, reference_result.stderr

    for frontend, generated in (
        ("selfhost", selfhost_generated),
        ("reference", reference_generated),
    ):
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-polymorphic-cleanup-sanitized",
            toolchain,
        )
