"""Executable contracts for self-hosted typed operator semantics."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_type_identity_contract import (
    CC,
    REPO,
    SELFHOST,
    _build_driver,
    _run,
)

FIXTURES = REPO / "src/tests/btrc/fixtures"


@pytest.fixture(scope="module")
def operator_compiler(tmp_path_factory) -> Path:
    output = tmp_path_factory.mktemp("selfhost-operator-compiler")
    return _build_driver(
        SELFHOST / "btrcc_main.btrc",
        output / "btrcc",
        output / "cache",
    )


INVALID_OPERATORS = (
    (
        "typed_operator_invalid_hash_fnptr.btrc",
        "__btrc_hash does not support",
    ),
    (
        "typed_operator_invalid_reference_order.btrc",
        "operator '<' is not defined",
    ),
    (
        "typed_operator_invalid_generic_order.btrc",
        "operator '<' is not defined",
    ),
    (
        "typed_operator_invalid_generic_inheritance.btrc",
        "Generic class inheritance is not supported",
    ),
    (
        "typed_operator_invalid_char_pointer_pointer.btrc",
        "operator '==' is not defined",
    ),
    (
        "typed_operator_matching_generic_inheritance.btrc",
        "Generic class inheritance is not supported",
    ),
)


@pytest.mark.parametrize("fixture_name, expected", INVALID_OPERATORS)
def test_invalid_typed_operators_fail_closed(
    operator_compiler: Path,
    fixture_name: str,
    expected: str,
) -> None:
    program = FIXTURES / fixture_name

    result = _run(
        [str(operator_compiler), "--no-stdlib", str(program)],
        timeout=30,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert expected in result.stderr


@pytest.mark.parametrize(
    "fixture_name",
    (
        "typed_operator_dead_invalid_generic.btrc",
        "typed_operator_c_string_pointer.btrc",
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
