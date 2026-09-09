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
            "GenericClosureOneLevel.btrc",
            ("btrc_Bag_int", "btrc_Node_int"),
        ),
        (
            "GenericClosureMultilevel.btrc",
            ("btrc_Outer_int", "btrc_Middle_int", "btrc_Leaf_int"),
        ),
        ("GenericClosureRecursive.btrc", ("btrc_Link_int",)),
        (
            "GenericClosureCycleRuntime.btrc",
            ("btrc_CycleLink_int",),
        ),
        (
            "GenericClosureConstructor.btrc",
            ("btrc_ConstructorSeed_int", "btrc_ConstructorLeaf_int"),
        ),
        (
            "GenericClosureField.btrc",
            ("btrc_FieldSeed_int", "btrc_FieldLeaf_int"),
        ),
        (
            "GenericClosureProperty.btrc",
            ("btrc_PropertySeed_int", "btrc_PropertyLeaf_int"),
        ),
        (
            "GenericClosureMethodBody.btrc",
            ("btrc_Factory_int", "btrc_Crate_int", "btrc_Crate_string"),
        ),
        (
            "CrossGenericConstructorRuntime.btrc",
            ("btrc_Maker_string", "btrc_Pair_string_int", "btrc_Empty_int"),
        ),
        (
            "GenericConstructorExpressionPositionsRuntime.btrc",
            ("btrc_Box_int", "btrc_Empty_int"),
        ),
        (
            "GenericCallTargetBindingRuntime.btrc",
            ("btrc_Sized_int", "btrc_Pair_Base_p1", "btrc_Factory_int"),
        ),
        (
            "GenericChainedMethodResultRuntime.btrc",
            ("btrc_Controller_Transport_p1",),
        ),
        (
            "GenericTypedefConstructorRuntime.btrc",
            ("btrc_Box_int",),
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

    if fixture_name == "GenericCallTargetBindingRuntime.btrc":
        emitted = selfhost_source.read_text()
        direct_size = next(line for line in emitted.splitlines() if "directBareSize =" in line)
        direct_pair = next(line for line in emitted.splitlines() if "directBarePair =" in line)
        assert "btrc_Sized_int_new(" in direct_size
        assert "btrc_Pair_Base_p1_new(" in direct_pair
        assert "__btrc_arc_retain(directBareSize)" not in emitted
        assert "__btrc_arc_retain(directBarePair)" not in emitted

    if fixture_name == "GenericChainedMethodResultRuntime.btrc":
        for emitted in (selfhost_source.read_text(), reference_source.read_text()):
            assert "ConfigureOutcome_succeeded(" in emitted
            assert ".succeeded()" not in emitted
            assert "__btrc_arc_release" in emitted

    if fixture_name == "GenericTypedefConstructorRuntime.btrc":
        for emitted in (selfhost_source.read_text(), reference_source.read_text()):
            constructor_line = next(line for line in emitted.splitlines() if "BoxAlias box =" in line)
            assert "btrc_Box_int_new(" in constructor_line
            assert "BoxAlias(" not in constructor_line

    _strict_build_and_run(selfhost_source, tmp_path / f"selfhost-{fixture.stem}")
    _strict_build_and_run(reference_source, tmp_path / f"python-{fixture.stem}")


def test_typedef_constructor_validates_the_specialized_signature(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / "GenericTypedefConstructorInvalid.btrc"
    selfhost, _selfhost_source = _compile_source(semantic_btrcc, tmp_path, fixture.read_text())
    reference, _reference_source = _compile_reference(tmp_path, fixture)

    assert selfhost.returncode != 0
    assert reference.returncode != 0
    for diagnostic in (selfhost.stderr, reference.stderr):
        assert "expects 'int' but got 'string'" in diagnostic


@pytest.mark.parametrize(
    "fixture_name, diagnostic",
    [
        (
            "GenericInheritanceChildUnsupported.btrc",
            "Generic class inheritance is not supported",
        ),
        (
            "GenericInheritanceParentUnsupported.btrc",
            "Generic class inheritance is not supported",
        ),
        (
            "GenericStaticFieldUnsupported.btrc",
            "is not supported on a generic class",
        ),
        (
            "GenericStaticMethodCallUnsupported.btrc",
            "has no specialization target",
        ),
        (
            "GenericStaticMethodValueUnsupported.btrc",
            "has no specialization target",
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


def test_static_properties_fail_closed_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / "StaticPropertyUnsupported.btrc"
    selfhost, _generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
    )
    reference, _reference_source = _compile_reference(tmp_path, fixture)

    for result in (selfhost, reference):
        assert result.returncode != 0
        assert "use a static field plus static methods" in result.stderr


def test_generic_method_tuple_and_complex_callee_run_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / "GenericMethodTupleRuntime.btrc"
    selfhost, selfhost_source = _compile_source(semantic_btrcc, tmp_path, fixture.read_text())
    reference, reference_source = _compile_reference(tmp_path, fixture)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-generic-tuple")
    _strict_build_and_run(reference_source, tmp_path / "python-generic-tuple")


def test_ordinary_static_calls_from_generic_methods_bind_without_receiver(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / "GenericOrdinaryStaticCallRuntime.btrc"
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        fixture.read_text(),
    )
    reference, reference_source = _compile_reference(tmp_path, fixture)

    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    for generated in (selfhost_source, reference_source):
        emitted = generated.read_text()
        assert "Tools_add(1, 4)" in emitted
        assert emitted.count("__btrc_default_Tools_add_2(") >= 2
        assert "Tools_add(Tools" not in emitted
    _strict_build_and_run(selfhost_source, tmp_path / "selfhost-generic-static")
    _strict_build_and_run(reference_source, tmp_path / "python-generic-static")


def test_generic_method_return_infers_from_inline_lambda_with_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    fixture = FIXTURES / "GenericMethodInlineLambdaRuntime.btrc"
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
            "GenericLambdaUnsupported.btrc",
            "Lambda expressions are not supported inside generic declarations",
        ),
        (
            "GenericSpawnUnsupported.btrc",
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
