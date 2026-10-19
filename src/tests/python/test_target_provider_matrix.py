"""The 11-row provider matrix through the reference resolver (platform-target-contract.md section 5.3).

Every stdlib group manifest, every examples/ package and the native test
packages resolve on every row of targets.toml with every export imported. No
row may select a foreign record: a provider, native declaration or binding
under another operating system's platform directory, a framework or
Objective-C record where the row has none, or pkg-config on a mobile row.
The exports a missing provider leaves unresolved, and the platform-directory
exports a row cannot use, are the P0 inventory's unavailable cells, cell for
cell, for every configured module. btrc's half is
src/tests/btrc/test_target_provider_matrix.py.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.compiler.python.frontend.packages import PackageManifestReader, PackageManifestValidator
from src.tests.python.provider_matrix_fixtures import (
    EXPECTED_REFUSALS,
    PROBE_FOREIGN,
    REPO,
    ROWS,
    SLICE_ROWS,
    STDLIB,
    UI0_GROUPS,
    UNAVAILABLE_IMPLEMENTATIONS,
    InventoryCells,
    MatrixClassifier,
    ProviderMatrix,
    ReferenceResolver,
    foreign_probe,
)

LABELS = tuple(ROWS)
# Every stdlib native declaration and binding that selects every operating
# system, by (group, kind, package-relative value), with why it pulls no
# platform SDK into any row: section 5.3's audit of the empty os arrays,
# which also match ios and android.
PORTABLE_STDLIB_RECORDS = {
    ("COM", "source", "COMRuntime.c"): (
        "C11 and pthreads; it includes <windows.h> and <objbase.h> only under _WIN32, and elsewhere the "
        "program supplies CoInitializeEx and CoUninitialize, as the proxy COM fixtures do"
    ),
    ("COM", "binding", "COM.h"): "declares only the btrcCOM* runtime functions and includes no SDK header",
}


class ReferenceRows:
    """The reference matrix, each row resolved at most once per module."""

    def __init__(self, root: Path) -> None:
        self.matrix = ProviderMatrix(root)
        self.resolver = ReferenceResolver(self.matrix)
        self.rows: dict[str, dict] = {}

    def row(self, label: str) -> dict:
        if label not in self.rows:
            self.rows[label] = self.matrix.row(label, self.resolver)
        return self.rows[label]


@pytest.fixture(scope="module")
def reference(tmp_path_factory) -> ReferenceRows:
    return ReferenceRows(tmp_path_factory.mktemp("provider-matrix"))


@pytest.mark.parametrize("label", LABELS)
def test_no_row_selects_a_foreign_record(reference: ReferenceRows, label: str) -> None:
    classified = MatrixClassifier(reference.matrix.root).classify(label, reference.row(label))
    assert classified.foreign == []
    assert classified.refused == set(EXPECTED_REFUSALS)
    # Every row selects records of its own: the classification is not vacuous.
    assert classified.portable


def test_the_missing_set_is_the_inventory(reference: ReferenceRows) -> None:
    """Section 5.3: the matrix's missing and os-restricted exports are the
    inventory's unavailable cells for every configured module, and a row the
    inventory does not slice (linux, macos) misses nothing."""

    status = {label: reference.matrix.export_status(label, reference.row(label)) for label in LABELS}
    sliced = {label for labels in SLICE_ROWS.values() for label in labels}
    for label in sorted(set(LABELS) - sliced):
        assert [identifier for identifier, value in sorted(status[label].items()) if value == "missing"] == [], label
    exports = ProviderMatrix.stdlib_exports()
    configured = {
        identifier
        for identifier, (group, _spelled) in exports.items()
        if group not in UI0_GROUPS
        and (
            identifier in ProviderMatrix.provider_exports()
            or MatrixClassifier.platforms(tuple(identifier.split(".")[1:-1]))
            or any(status[label][identifier] == "missing" for label in LABELS)
        )
    }
    assert configured, "the stdlib configures at least one provider module"
    cells = InventoryCells.implementations()
    matrix, inventory = {}, {}
    for identifier in sorted(configured):
        for name, labels in SLICE_ROWS.items():
            unavailable = {status[label][identifier] != "resolved" for label in labels}
            assert len(unavailable) == 1, f"{identifier}: the rows of {name} disagree"
            matrix[identifier, name] = unavailable.pop()
            inventory[identifier, name] = cells[identifier, name] in UNAVAILABLE_IMPLEMENTATIONS
    assert {cell for cell, value in matrix.items() if value} == {cell for cell, value in inventory.items() if value}


def test_every_stdlib_record_that_selects_every_system_names_why() -> None:
    reader = PackageManifestReader()
    validator = PackageManifestValidator()
    portable = set()
    for path in sorted(STDLIB.rglob("btrc.toml")):
        manifest, _ = reader.read_document(str(path))
        name = validator.validate_identity(manifest, str(path))
        root = os.path.dirname(str(path))
        group = Path(root).relative_to(STDLIB).as_posix() or "."
        for declaration in validator.native(manifest, root, name, str(path)):
            if not declaration.operating_systems:
                value = (
                    os.path.relpath(declaration.value, root) if os.path.isabs(declaration.value) else declaration.value
                )
                portable.add((group, declaration.kind, Path(value).as_posix()))
        for binding in validator.bindings(manifest, root, name, str(path)):
            if not binding.operating_systems:
                portable.add((group, "binding", Path(os.path.relpath(binding.header, root)).as_posix()))
    assert portable == set(PORTABLE_STDLIB_RECORDS)


@pytest.mark.parametrize("label", sorted(PROBE_FOREIGN))
def test_a_resolved_header_under_another_platform_is_foreign(tmp_path: Path, label: str) -> None:
    workspace, program = foreign_probe(tmp_path)
    resolved = ReferenceResolver(workspace)([program], label)
    classified = MatrixClassifier(workspace.root).classify(label, resolved)
    assert sorted(classified.foreign) == sorted(f"{program.key}: {reason}" for reason in PROBE_FOREIGN[label])
    assert classified.portable, "the portable header stays portable"


AUDIO_LINUX = "repo:src/stdlib/Audio/Linux/AudioProvider.btrc"
# (row, kind, paths, language, name) and the reason the record is foreign, or None.
CAPABILITY_CASES = (
    ("macos-aarch64", "provider", (AUDIO_LINUX,), "", "", f"provider {AUDIO_LINUX} lives under a linux directory"),
    ("linux-x86_64", "provider", (AUDIO_LINUX,), "", "", None),
    ("windows-x86_64", "framework", (), "", "Foundation", "framework Foundation on a row without frameworks"),
    ("ios-aarch64", "framework", (), "", "Foundation", None),
    ("android-aarch64", "pkg-config", (), "", "zlib", "pkg-config zlib on android"),
    ("ios-aarch64-simulator", "pkg-config", (), "", "zlib", "pkg-config zlib on ios"),
    ("linux-aarch64", "pkg-config", (), "", "zlib", None),
    (
        "windows-aarch64-msvc",
        "binding",
        ("work:Api.btrc", "work:Api.h"),
        "objective-c",
        "",
        "objective-c binding work:Api.btrc on a row without Objective-C",
    ),
    (
        "android-x86_64",
        "source",
        ("work:Probe.mm",),
        "objective-c++",
        "",
        "objective-c++ source work:Probe.mm on a row without Objective-C",
    ),
    ("ios-aarch64", "source", ("work:Probe.mm",), "objective-c++", "", None),
)


@pytest.mark.parametrize(("label", "kind", "paths", "language", "name", "reason"), CAPABILITY_CASES)
def test_the_classifier_applies_each_row_capability(tmp_path: Path, label, kind, paths, language, name, reason) -> None:
    assert MatrixClassifier(tmp_path).foreign(label, kind, paths, language, name) == reason


def test_the_matrix_covers_every_manifest() -> None:
    programs = ProviderMatrix.all_programs()
    packages = {program.relative.split("/", 1)[1] for program in programs if program.key.startswith("package:")}
    for tree in ProviderMatrix.package_trees():
        for manifest in (REPO / tree).rglob("btrc.toml"):
            modules = {path.relative_to(REPO).as_posix() for path in manifest.parent.rglob("*.btrc")}
            assert modules and modules <= packages, manifest
    groups = {program.key.removeprefix("group:") for program in programs if program.key.startswith("group:")}
    assert groups == {path.parent.name for path in STDLIB.glob("*/btrc.toml")} | {"Root"}
    assert set(EXPECTED_REFUSALS) <= {program.key for program in programs}
