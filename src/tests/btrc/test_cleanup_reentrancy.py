"""Dual-compiler cleanup reentrancy regression coverage."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.runtime_ownership_harness import compile_reference_source
from src.tests.btrc.test_semantic_validation import REPO, _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
FIXTURE = REPO / "src/tests/btrc/fixtures/cleanup_reentrancy_runtime.btrc"
UNHANDLED_FIXTURE = REPO / "src/tests/btrc/fixtures/cleanup_unhandled_runtime.btrc"


def _strict_build_and_run(source: Path, output: Path, compiler: str) -> None:
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(output),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run(
        [str(output)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout == "PASS: cleanup reentrancy\n"


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
def test_throwing_cleanup_preserves_primary_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = FIXTURE.read_text()
    selfhost_result, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference_result, reference_c = compile_reference_source(
        tmp_path,
        source,
        "cleanup-reentrancy",
    )
    assert selfhost_result.returncode == 0, selfhost_result.stderr
    assert reference_result.returncode == 0, reference_result.stderr

    for compiler_name, generated in (
        ("selfhost", selfhost_c),
        ("reference", reference_c),
    ):
        emitted = generated.read_text()
        assert "__btrc_cleanup_top = base - 1;" in emitted
        assert "char primary_error[sizeof __btrc_error_msg];" in emitted
        assert "__btrc_run_cleanups(-1);" in emitted
        for c_compiler in COMPILERS:
            c_name = Path(c_compiler).name
            _strict_build_and_run(
                generated,
                tmp_path / f"{compiler_name}-{c_name}",
                c_compiler,
            )


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
def test_unhandled_throw_runs_level_minus_one_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = UNHANDLED_FIXTURE.read_text()
    selfhost_result, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference_result, reference_c = compile_reference_source(
        tmp_path,
        source,
        "cleanup-unhandled",
    )
    assert selfhost_result.returncode == 0, selfhost_result.stderr
    assert reference_result.returncode == 0, reference_result.stderr

    expected_error = "cleanup:3\ncleanup:2\ncleanup:1\nUnhandled exception: unhandled primary\n"
    for compiler_name, generated in (
        ("selfhost", selfhost_c),
        ("reference", reference_c),
    ):
        for c_compiler in COMPILERS:
            c_name = Path(c_compiler).name
            executable = tmp_path / f"unhandled-{compiler_name}-{c_name}"
            compiled = subprocess.run(
                [
                    c_compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
                    str(generated),
                    "-lm",
                    "-lpthread",
                    "-o",
                    str(executable),
                ],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=120,
            )
            assert compiled.returncode == 0, compiled.stderr
            executed = subprocess.run(
                [str(executable)],
                cwd=REPO,
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert executed.returncode == 1
            assert executed.stdout == ""
            assert executed.stderr == expected_error
