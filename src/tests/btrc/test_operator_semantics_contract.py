"""Executable contracts for self-hosted typed operator semantics."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.btrc.test_type_identity_contract import (
    CC,
    REPO,
    _run,
)

FIXTURES = REPO / "src/tests/btrc/fixtures"
COMPILER_ENV = {**os.environ, "BTRC_HOME": str(REPO / "src")}


@pytest.fixture(scope="module")
def operator_compiler(semantic_btrcc: Path) -> Path:
    return semantic_btrcc


INVALID_OPERATORS = (
    (
        "TypedOperatorInvalidHashFnptr.btrc",
        "__btrc_hash does not support",
    ),
    (
        "TypedOperatorInvalidReferenceOrder.btrc",
        "operator '<' is not defined",
    ),
    (
        "TypedOperatorInvalidGenericOrder.btrc",
        "operator '<' is not defined",
    ),
    (
        "TypedOperatorInvalidGenericInheritance.btrc",
        "Generic class inheritance is not supported",
    ),
    (
        "TypedOperatorInvalidCharPointerPointer.btrc",
        "operator '==' is not defined",
    ),
    (
        "TypedOperatorMatchingGenericInheritance.btrc",
        "Generic class inheritance is not supported",
    ),
)


@pytest.mark.parametrize("frontend", ("python", "selfhost"))
def test_operator_owner_runtime_matches_both_frontends(
    operator_compiler: Path,
    tmp_path: Path,
    frontend: str,
) -> None:
    program = FIXTURES / "OperatorOwnerRuntime.btrc"
    c_path = tmp_path / f"operator_owner_runtime.{frontend}.c"
    if frontend == "python":
        compiled_source = _run(
            [
                # The reference compiler is invoked as a module, exactly as every
                # other test does: bin/btrcpy is an untracked build product that
                # `make clean` removes and a fresh checkout never has.
                sys.executable,
                "-m",
                "src.compiler.python.main",
                "--no-stdlib",
                "--strict-imports",
                "--no-cache",
                str(program),
                "-o",
                str(c_path),
            ],
            env=COMPILER_ENV,
            timeout=60,
        )
        assert compiled_source.returncode == 0, compiled_source.stderr
    else:
        compiled_source = _run(
            [
                str(operator_compiler),
                "--no-stdlib",
                "--strict-imports",
                str(program),
            ],
            env=COMPILER_ENV,
            timeout=60,
        )
        assert compiled_source.returncode == 0, compiled_source.stderr
        c_path.write_text(compiled_source.stdout)

    binary = tmp_path / f"operator_owner_runtime.{frontend}"
    compiled = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    run = _run([str(binary)], timeout=10)
    assert run.returncode == 0, run.stderr


@pytest.mark.parametrize("fixture_name, expected", INVALID_OPERATORS)
def test_invalid_typed_operators_fail_closed(
    operator_compiler: Path,
    fixture_name: str,
    expected: str,
) -> None:
    program = FIXTURES / fixture_name

    result = _run(
        [str(operator_compiler), "--no-stdlib", str(program)],
        env=COMPILER_ENV,
        timeout=30,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert expected in result.stderr


@pytest.mark.parametrize(
    "fixture_name",
    (
        "TypedOperatorDeadInvalidGeneric.btrc",
        "TypedOperatorCStringPointer.btrc",
        "TypedOperatorFnptrEquality.btrc",
    ),
)
def test_valid_generic_operator_specializations_compile_strictly(
    operator_compiler: Path,
    tmp_path: Path,
    fixture_name: str,
) -> None:
    program = FIXTURES / fixture_name
    emitted = _run(
        [str(operator_compiler), "--no-stdlib", str(program)],
        env=COMPILER_ENV,
        timeout=30,
    )
    assert emitted.returncode == 0, emitted.stderr

    c_path = tmp_path / f"{program.stem}.c"
    binary = tmp_path / program.stem
    c_path.write_text(emitted.stdout)
    compiled = _run(
        [
            *CC,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
    assert run.returncode == 0
