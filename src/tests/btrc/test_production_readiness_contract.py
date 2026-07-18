"""Dual-compiler regressions for production-readiness audit boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import (
    compile_diagnostic_pair,
    compile_fixture_pair,
    run_strict_pair,
    run_tracked_fixture_pair,
)
from src.tests.btrc.test_mutex_value_contract import COMPILERS

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

FIXTURES = Path(__file__).with_name("fixtures")
PRINTF_RUNTIME = FIXTURES / "production_printf_runtime.btrc"
PRINTF_ORDER_RUNTIME = FIXTURES / "production_printf_order_runtime.btrc"
USER_PRINTF_ORDER_RUNTIME = FIXTURES / "production_user_printf_order_runtime.btrc"
RECEIVER_ORDER_RUNTIME = FIXTURES / "production_string_receiver_order_runtime.btrc"
GENERIC_FIELD_RUNTIME = FIXTURES / "production_generic_field_ownership_runtime.btrc"
GENERIC_DEFAULTS_RUNTIME = FIXTURES / "production_generic_defaults_runtime.btrc"
THROWING_CLEANUP_RUNTIME = FIXTURES / "production_throwing_cleanup_runtime.btrc"
STDLIB_STRING_RUNTIME = FIXTURES / "production_stdlib_string_safety_runtime.btrc"

EXPECTED_VALUES = "255 65535 true -5000000000 9000000000 17 <function> <tuple> <struct> Circle 1"
EXPECTED_FSTRING = "<|255|65535|true|-5000000000|9000000000|17|<function>|<tuple>|<struct>|Circle|1>"


def _validate_printf_output(stdout: str) -> None:
    lines = stdout.splitlines()
    assert len(lines) == 4
    assert lines[0] == ""
    assert lines[1] == EXPECTED_VALUES
    assert lines[2] and lines[2] not in {"(nil)", "(null)"}
    assert lines[3] == EXPECTED_FSTRING


def _validate_printf_order_output(stdout: str) -> None:
    assert stdout == "1 1\n2 2\n"


def _validate_stdlib_string_output(stdout: str) -> None:
    assert stdout == "\n"


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_nullable_print_and_variadic_values_are_dual_compiler_portable(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(semantic_btrcc, tmp_path, PRINTF_RUNTIME)
    run_strict_pair(compiled, tmp_path, validate_stdout=_validate_printf_output)


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_builtin_printf_arguments_are_dual_compiler_source_ordered(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(
        semantic_btrcc,
        tmp_path,
        PRINTF_ORDER_RUNTIME,
    )
    run_strict_pair(
        compiled,
        tmp_path,
        validate_stdout=_validate_printf_order_output,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_user_printf_shadowing_remains_dual_compiler_source_ordered(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(
        semantic_btrcc,
        tmp_path,
        USER_PRINTF_ORDER_RUNTIME,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_string_receiver_is_stabilized_before_mutating_arguments(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(
        semantic_btrcc,
        tmp_path,
        RECEIVER_ORDER_RUNTIME,
    )
    run_strict_pair(compiled, tmp_path)


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_resolved_generic_fields_own_class_string_and_mutex_values(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    run_tracked_fixture_pair(
        semantic_btrcc,
        tmp_path,
        GENERIC_FIELD_RUNTIME,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_rich_generic_defaults_initialize_and_release_in_both_compilers(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    run_tracked_fixture_pair(
        semantic_btrcc,
        tmp_path,
        GENERIC_DEFAULTS_RUNTIME,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_throwing_return_and_initialization_paths_reclaim_every_allocation(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    run_tracked_fixture_pair(
        semantic_btrcc,
        tmp_path,
        THROWING_CLEANUP_RUNTIME,
    )


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
def test_nullable_stdlib_string_paths_are_dual_compiler_strict_c11(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_fixture_pair(
        semantic_btrcc,
        tmp_path,
        STDLIB_STRING_RUNTIME,
        include_stdlib=True,
    )
    run_strict_pair(
        compiled,
        tmp_path,
        validate_stdout=_validate_stdlib_string_output,
    )


@pytest.mark.parametrize(
    ("source", "binding"),
    (
        pytest.param(
            "Mutex<int> globalGate; int main() { return 0; }",
            "globalGate",
            id="global",
        ),
        pytest.param(
            "int main() { static Mutex<int> staticGate; return 0; }",
            "staticGate",
            id="static-local",
        ),
        pytest.param(
            "class Owner { class Mutex<int> gate; } int main() { return 0; }",
            "Owner.gate",
            id="class-static",
        ),
        pytest.param(
            "int main() { extern Mutex<int> externalGate; return 0; }",
            "externalGate",
            id="extern",
        ),
        pytest.param(
            "typedef Mutex<int> Gate; Gate aliasedGate; int main() { return 0; }",
            "aliasedGate",
            id="typedef-global",
        ),
    ),
)
def test_static_duration_mutex_owners_fail_closed_in_both_analyzers(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    binding: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        diagnostic = result.stderr.lower()
        assert result.returncode != 0
        assert "cannot own a mutex handle" in diagnostic
        assert binding.lower() in diagnostic
