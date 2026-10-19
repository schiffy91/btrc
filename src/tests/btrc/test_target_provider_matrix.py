"""The 11-row provider matrix through btrc, record for record with the reference.

platform-target-contract.md section 5.3's parity variant: btrc's package
resolver (ProviderMatrixDriver, over the frontend's own Packages.btrc and
Resolver.btrc) resolves every program of the matrix on every row of
targets.toml, and each resolution -- the loaded sources, the selected
providers, the plan's packages and every selected native declaration and
binding, or the module with no provider for the row -- equals the reference
resolver's. The reference half and the inventory comparison are
src/tests/python/test_target_provider_matrix.py.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from src.tests.python.provider_matrix_fixtures import (
    EXPECTED_REFUSALS,
    PROBE_FOREIGN,
    REPO,
    ROWS,
    MatrixClassifier,
    ProviderMatrix,
    ReferenceResolver,
    Resolution,
    SelfhostResolver,
    foreign_probe,
)

DRIVER = REPO / "src/tests/btrc/fixtures/ProviderMatrixDriver.btrc"
LABELS = tuple(ROWS)


@pytest.fixture(scope="module")
def matrix_driver(selfhost_driver) -> Path:
    return selfhost_driver(DRIVER, compile_flags=("-pedantic-errors",))


@pytest.fixture(scope="module")
def frontends(tmp_path_factory, matrix_driver: Path):
    reference = ProviderMatrix(tmp_path_factory.mktemp("reference-matrix"))
    selfhost = ProviderMatrix(tmp_path_factory.mktemp("selfhost-matrix"))
    return reference, ReferenceResolver(reference), selfhost, SelfhostResolver(selfhost, matrix_driver)


def differences(expected: dict[str, Resolution], actual: dict[str, Resolution]) -> list[str]:
    """Each program and field where btrc's resolution differs from the reference's."""

    found = [f"{key}: only the reference resolved it" for key in sorted(set(expected) - set(actual))]
    found += [f"{key}: only btrc resolved it" for key in sorted(set(actual) - set(expected))]
    for key in sorted(set(expected) & set(actual)):
        for item in fields(Resolution):
            left, right = getattr(expected[key], item.name), getattr(actual[key], item.name)
            if left == right:
                continue
            if isinstance(left, tuple):
                found.append(
                    f"{key}.{item.name}: reference only {sorted(set(left) - set(right))}, "
                    f"btrc only {sorted(set(right) - set(left))}"
                )
            else:
                found.append(f"{key}.{item.name}: reference {left!r}, btrc {right!r}")
    return found


@pytest.mark.parametrize("label", LABELS)
def test_both_frontends_resolve_the_row_record_for_record(frontends, label: str) -> None:
    reference, python, selfhost, btrc = frontends
    actual = selfhost.row(label, btrc)
    assert differences(reference.row(label, python), actual) == []
    classified = MatrixClassifier(selfhost.root).classify(label, actual)
    assert classified.foreign == []
    assert classified.refused == set(EXPECTED_REFUSALS)


@pytest.mark.parametrize("label", sorted(PROBE_FOREIGN))
def test_both_frontends_select_the_foreign_probe_alike(matrix_driver: Path, tmp_path: Path, label: str) -> None:
    reference_workspace, program = foreign_probe(tmp_path / "reference")
    selfhost_workspace, _program = foreign_probe(tmp_path / "selfhost")
    expected = ReferenceResolver(reference_workspace)([program], label)
    actual = SelfhostResolver(selfhost_workspace, matrix_driver)([program], label)
    assert differences(expected, actual) == []
    classified = MatrixClassifier(selfhost_workspace.root).classify(label, actual)
    assert sorted(classified.foreign) == sorted(f"{program.key}: {reason}" for reason in PROBE_FOREIGN[label])
