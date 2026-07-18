"""Strict-C contracts for bounded structured-expression emission."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_fixture_pair,
    run_strict_pair,
)
from src.tests.btrc.string_coercion_harness import compile_pair
from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _compiler_environment,
)
from src.tests.btrc.test_mutex_value_contract import COMPILERS, REPO

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURE = Path(__file__).parents[1] / "classes" / "test_instance_method_chain.btrc"
MAX_LOGICAL_LINE = 1024
NDEBUG_SOURCE = """
    #include <assert.h>

    int observations = 0;

    bool observe() {
        observations += 1;
        return true;
    }

    class Checker<T> {
        public T value;

        public Checker(T value) {
            self.value = value;
        }

        public int verify() {
            assert(observe());
            return observations;
        }
    }

    int main() {
        Checker<int> checker = new Checker<int>(7);
        if (checker.verify() != 1 || observations != 1) { return 2; }
        printf("PASS: assert_ndebug_evaluation\\n");
        return 0;
    }
"""


def _logical_lines(source: str) -> list[str]:
    """Apply C's backslash-newline splicing to measure logical lines."""
    logical = []
    pending = ""
    for physical in source.splitlines():
        if physical.endswith("\\"):
            pending += physical[:-1]
            continue
        logical.append(pending + physical)
        pending = ""
    if pending:
        logical.append(pending)
    return logical


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_deep_method_chain_has_bounded_strict_c11_output(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(semantic_btrcc, tmp_path, FIXTURE)
    for _frontend, generated in compiled:
        source = generated.read_text()
        assert max(map(len, _logical_lines(source))) <= MAX_LOGICAL_LINE
        assert "bool __btrc_assert_condition_" in source
    run_strict_pair(compiled, tmp_path)


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_assert_argument_runs_once_under_ndebug_in_generic_methods(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_pair(
        semantic_btrcc,
        tmp_path,
        NDEBUG_SOURCE,
        "assert-ndebug-evaluation",
        include_stdlib=False,
    )
    for frontend, generated in compiled:
        source = generated.read_text()
        assert "bool __btrc_assert_condition_" in source
        for compiler in COMPILERS:
            executable = tmp_path / f"{frontend}-{Path(compiler).name}-ndebug"
            environment = _compiler_environment(compiler)
            build = subprocess.run(
                [
                    compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-DNDEBUG",
                    "-O2",
                    str(generated),
                    "-pthread",
                    "-lm",
                    "-o",
                    str(executable),
                ],
                cwd=REPO,
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
            )
            assert build.returncode == 0, build.stderr
            run = subprocess.run(
                [str(executable)],
                cwd=REPO,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert run.returncode == 0, run.stderr
            assert run.stdout == "PASS: assert_ndebug_evaluation\n"
