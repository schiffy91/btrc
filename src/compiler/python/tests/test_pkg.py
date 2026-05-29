"""Unit tests for the package manager (pkg.py)."""

import json
import os

from src.compiler.python import pkg


def test_find_manifest_walks_up(tmp_path):
    root = tmp_path / "proj"
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / "btrc.toml").write_text("[package]\nname = 'p'\n")
    assert pkg.find_manifest(str(sub)) == str(root / "btrc.toml")


def test_find_manifest_none(tmp_path):
    d = tmp_path / "nowhere"
    d.mkdir()
    assert pkg.find_manifest(str(d)) is None


def test_resolve_path_dep_writes_lock(tmp_path):
    dep = tmp_path / "mathx"
    (dep / "src").mkdir(parents=True)
    (dep / "src" / "mathx.btrc").write_text("class Mathx {}\n")
    (dep / "btrc.toml").write_text("[package]\nname = 'mathx'\n")

    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\nmathx = { path = "../mathx" }\n')

    resolved = pkg.resolve(str(app / "btrc.toml"))
    assert "mathx" in resolved
    assert os.path.isdir(resolved["mathx"]["path"])
    lock = json.loads((app / "btrc.lock").read_text())
    assert lock["packages"]["mathx"]["path"] == resolved["mathx"]["path"]


def test_resolve_uses_existing_lock(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\nx = { path = "../x" }\n')
    (app / "btrc.lock").write_text(
        json.dumps({"packages": {"x": {"path": "/pinned/location"}}})
    )
    resolved = pkg.resolve(str(app / "btrc.toml"))
    assert resolved["x"]["path"] == "/pinned/location"  # lock wins over manifest


def test_package_import_paths(tmp_path):
    dep = tmp_path / "mathx"
    (dep / "src").mkdir(parents=True)
    (dep / "src" / "mathx.btrc").write_text("class Mathx {}\n")
    (dep / "src" / "vec.btrc").write_text("class Vec {}\n")
    pkg._PACKAGES = {"mathx": {"path": str(dep)}}
    try:
        assert pkg.package_import_paths("mathx")[0].endswith("src/mathx.btrc")
        assert pkg.package_import_paths("mathx.vec")[0].endswith("src/vec.btrc")
        assert pkg.package_import_paths("not_a_dep") == []
    finally:
        pkg._PACKAGES = {}
