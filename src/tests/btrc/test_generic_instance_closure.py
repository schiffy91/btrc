"""Transitive generic-instance discovery parity and runtime contracts."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPO = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).with_name("fixtures")


def _compile_reference(tmp_path: Path, fixture: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    generated = tmp_path / f"python-{fixture.stem}.c"
    result = subprocess.run(
        [
            "python3",
            "-m",
            "src.compiler.python.main",
            str(fixture),
            "--no-stdlib",
            "--no-cache",
            "-o",
            str(generated),
        ],
        cwd=REPO,
        env={**os.environ, "BTRC_CACHE_DIR": str(tmp_path / "cache")},
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result, generated


@pytest.mark.parametrize(
    "fixture_name, symbols",
    [
        (
            "generic_closure_one_level.btrc",
            ("btrc_Bag_int", "btrc_Node_int"),
        ),
        (
            "generic_closure_multilevel.btrc",
            ("btrc_Outer_int", "btrc_Middle_int", "btrc_Leaf_int"),
        ),
        ("generic_closure_recursive.btrc", ("btrc_Link_int",)),
        (
            "generic_closure_cycle_runtime.btrc",
            ("btrc_CycleLink_int",),
        ),
        (
            "generic_closure_constructor.btrc",
            ("btrc_ConstructorSeed_int", "btrc_ConstructorLeaf_int"),
        ),
        (
            "generic_closure_field.btrc",
            ("btrc_FieldSeed_int", "btrc_FieldLeaf_int"),
        ),
        (
            "generic_closure_property.btrc",
            ("btrc_PropertySeed_int", "btrc_PropertyLeaf_int"),
        ),
        (
            "generic_closure_method_body.btrc",
            ("btrc_Factory_int", "btrc_Crate_int", "btrc_Crate_string"),
        ),
    ],
)
def test_transitive_generic_instances_match_and_run_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
    symbols: tuple[str, ...],
) -> None:
    fixture = FIXTURES / fixture_name
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, fixture.read_text())
    assert selfhost.returncode == 0, selfhost.stderr

    reference, reference_source = _compile_reference(tmp_path, fixture)
    assert reference.returncode == 0, reference.stderr

    for symbol in symbols:
        struct = f"struct {symbol} {{"
        assert selfhost.stdout.count(struct) == 1
        assert reference_source.read_text().count(struct) == 1

    _strict_build_and_run(selfhost_source, tmp_path / f"selfhost-{fixture.stem}")
    _strict_build_and_run(reference_source, tmp_path / f"python-{fixture.stem}")


@pytest.mark.parametrize(
    "fixture_name, diagnostic",
    [
        (
            "generic_inheritance_child_unsupported.btrc",
            "Generic class inheritance is not supported",
        ),
        (
            "generic_inheritance_parent_unsupported.btrc",
            "Generic class inheritance is not supported",
        ),
        (
            "generic_static_field_unsupported.btrc",
            "is not supported on a generic class",
        ),
    ],
)
def test_unsupported_generic_storage_and_inheritance_fail_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
    diagnostic: str,
) -> None:
    fixture = FIXTURES / fixture_name
    selfhost, _generated = _compile_source(semantic_btrcc, tmp_path, fixture.read_text())
    reference, _reference_source = _compile_reference(tmp_path, fixture)

    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr


def test_generic_method_tuple_and_complex_callee_run_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / "generic_method_tuple_runtime.btrc"
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, fixture.read_text())
    reference, reference_source = _compile_reference(tmp_path, fixture)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-generic-tuple")
    _strict_build_and_run(reference_source, tmp_path / "python-generic-tuple")


def test_generic_method_return_infers_from_inline_lambda_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / "generic_method_inline_lambda_runtime.btrc"
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
    )
    reference, reference_source = _compile_reference(tmp_path, fixture)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-generic-inline-lambda",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "python-generic-inline-lambda",
    )


@pytest.mark.parametrize(
    "fixture_name, diagnostic",
    [
        (
            "generic_lambda_unsupported.btrc",
            "Lambda expressions are not supported inside generic declarations",
        ),
        (
            "generic_spawn_unsupported.btrc",
            "spawn expressions are not supported inside generic declarations",
        ),
    ],
)
def test_unlowered_generic_callable_forms_fail_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    fixture_name: str,
    diagnostic: str,
) -> None:
    fixture = FIXTURES / fixture_name
    selfhost, _selfhost_source = _compile_source(semantic_btrcc, tmp_path, fixture.read_text())
    reference, _reference_source = _compile_reference(tmp_path, fixture)

    assert selfhost.returncode != 0
    assert reference.returncode != 0
    assert diagnostic in selfhost.stderr
    assert diagnostic in reference.stderr
