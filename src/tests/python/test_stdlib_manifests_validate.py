"""Every stdlib manifest validates in full, on every commit.

A compile finishes the native blocks of a stdlib package only when the program
reaches it, so an invalid block in an unreached package is diagnosed by no
compile. This test is where that validation now happens: it reads every
``btrc.toml`` under the stdlib and drives the same validator a reached package
gets, so the lazy contract never hides a broken manifest.
"""

from __future__ import annotations

import os
from pathlib import Path

from src.compiler.python.frontend.packages import (
    NativeLinkPlan,
    PackageManifestReader,
    PackageManifestValidator,
)

REPO = Path(__file__).resolve().parents[3]
STDLIB = REPO / "src" / "stdlib"


def _manifests() -> list[Path]:
    return sorted(STDLIB.rglob("btrc.toml"))


def test_every_stdlib_manifest_finishes_its_native_blocks_and_bindings() -> None:
    reader = PackageManifestReader()
    validator = PackageManifestValidator()
    manifests = _manifests()
    assert len(manifests) >= 17, manifests
    for path in manifests:
        manifest, _ = reader.read_document(str(path))
        name = validator.validate_identity(manifest, str(path))
        assert name.startswith(NativeLinkPlan.STDLIB_PACKAGE_PREFIX), (path, name)
        root = os.path.dirname(str(path))
        validator.dependencies(manifest, str(path))
        validator.native(manifest, root, name, str(path))
        validator.bindings(manifest, root, name, str(path))
        validator.exported_modules(manifest, str(path))


def test_unreached_stdlib_packages_are_not_finished_but_reached_ones_are(tmp_path: Path) -> None:
    """The lazy contract, stated: only packages owning a source pay for native validation."""

    plan = NativeLinkPlan(None, (), ())
    root = str(STDLIB)
    outside = tmp_path / "Program.btrc"
    outside.write_text("int main() { return 0; }\n")
    packages = plan._stdlib_packages(root, os.path.join(root, "btrc.toml"), [str(outside)])
    assert all(not package.native and not package.bindings for package in packages)
    gui_module = STDLIB / "GUI" / "GUI.btrc"
    packages = plan._stdlib_packages(root, os.path.join(root, "btrc.toml"), [str(gui_module)])
    by_name = {package.name: package for package in packages}
    assert by_name["btrc_stdlib_gui"].bindings, "the reached GUI package finishes its bindings"
    assert all(not package.bindings for name, package in by_name.items() if name != "btrc_stdlib_gui")
