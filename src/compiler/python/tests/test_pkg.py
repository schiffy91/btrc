"""Unit tests for the package manager (pkg.py)."""

import hashlib
import json
import os
import pathlib
import shutil
import subprocess

import pytest

from src.compiler.python import pkg
from src.compiler.python.pkg import IncludeResolutionError


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
    # Lock paths are relative to the lock file (reproducible across checkouts)
    # and stamped with the manifest's dependency-table hash.
    assert lock["packages"]["mathx"]["path"] == os.path.join("..", "mathx")
    assert lock["manifest_hash"] == pkg._deps_hash({"mathx": {"path": "../mathx"}})

    # A fresh resolve trusts the still-matching lock and resolves the relative
    # path back against the lock's own directory.
    again = pkg.resolve(str(app / "btrc.toml"))
    assert again["mathx"]["path"] == resolved["mathx"]["path"]


def test_resolve_uses_existing_lock(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\nx = { path = "../x" }\n')
    (app / "btrc.lock").write_text(json.dumps({
        "manifest_hash": pkg._deps_hash({"x": {"path": "../x"}}),
        "packages": {"x": {"path": "/pinned/location"}},
    }))
    resolved = pkg.resolve(str(app / "btrc.toml"))
    assert resolved["x"]["path"] == "/pinned/location"  # fresh lock wins


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


# --------------------------------------------------------------------------
# git cache keying (URL-distinct deps must not share a clone)
# --------------------------------------------------------------------------

def test_git_cache_key_includes_url(tmp_path, monkeypatch):
    """Same name+rev, different URLs -> distinct cache dirs (no network:
    pre-fabricate both clone dirs and assert the derived keys differ)."""
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    url_a = "https://a.example/netkit.git"
    url_b = "https://b.example/netkit.git"
    tag_a = hashlib.sha256(url_a.encode()).hexdigest()[:8]
    tag_b = hashlib.sha256(url_b.encode()).hexdigest()[:8]
    (tmp_path / "cache" / f"netkit-v1.0-{tag_a}" / ".git").mkdir(parents=True)
    (tmp_path / "cache" / f"netkit-v1.0-{tag_b}" / ".git").mkdir(parents=True)

    path_a = pkg._resolve_git("netkit", url_a, "v1.0")
    path_b = pkg._resolve_git("netkit", url_b, "v1.0")
    assert path_a != path_b
    assert tag_a in os.path.basename(path_a)
    assert tag_b in os.path.basename(path_b)


def _make_git_repo(root, marker):
    """Hermetic local git repo with one committed .btrc module."""
    root.mkdir(parents=True)
    (root / "lib.btrc").write_text(f"// {marker}\nint libfn() {{ return 1; }}\n")
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for cmd in (["git", "init", "--quiet", "-b", "main", "."],
                ["git", "add", "."],
                ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "init"]):
        subprocess.run(cmd, cwd=root, env=env, check=True, capture_output=True)
    return root


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_git_branch_dep_repinned_on_refresh(tmp_path, monkeypatch):
    """A branch rev is pinned by the first clone and advanced by --fetch."""
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    repo = _make_git_repo(tmp_path / "upstream", "rev one")
    url = repo.as_uri()  # hermetic local file:// URL — no network

    clone = pkg._resolve_git("dep", url, "main")
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()

    # Upstream advances; a plain resolve stays pinned...
    (repo / "lib.btrc").write_text("// rev two\nint libfn() { return 2; }\n")
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-c", "commit.gpgsign=false", "commit", "--quiet",
                    "-am", "two"], cwd=repo, env=env, check=True, capture_output=True)
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()
    pkg._resolve_git("dep", url, "main")
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()

    # ...and --fetch (refresh) re-pins to the new tip.
    pkg._resolve_git("dep", url, "main", refresh=True)
    assert "rev two" in (pathlib.Path(clone) / "lib.btrc").read_text()


def test_pinned_sha_never_refetched(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    sha = "a" * 40
    url = "https://x/y.git"
    tag = hashlib.sha256(url.encode()).hexdigest()[:8]
    (tmp_path / "cache" / f"dep-{sha}-{tag}" / ".git").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(pkg.subprocess, "run",
                        lambda cmd, *a, **k: calls.append(cmd))
    pkg._resolve_git("dep", url, sha, refresh=True)
    assert calls == []  # immutable rev: no fetch even on --fetch


# --------------------------------------------------------------------------
# lock invalidation + portability
# --------------------------------------------------------------------------

def test_lock_invalidated_when_manifest_deps_change(tmp_path):
    for name in ("alpha", "beta"):
        d = tmp_path / name
        d.mkdir()
        (d / f"{name}.btrc").write_text(f"class {name.title()} {{}}\n")
    app = tmp_path / "app"
    app.mkdir()
    manifest = app / "btrc.toml"

    manifest.write_text('[dependencies]\nalpha = { path = "../alpha" }\n')
    first = pkg.resolve(str(manifest))
    assert set(first) == {"alpha"}

    # Adding a dep must take effect WITHOUT --fetch.
    manifest.write_text('[dependencies]\nalpha = { path = "../alpha" }\n'
                        'beta = { path = "../beta" }\n')
    second = pkg.resolve(str(manifest))
    assert set(second) == {"alpha", "beta"}
    lock = json.loads((app / "btrc.lock").read_text())
    assert set(lock["packages"]) == {"alpha", "beta"}


def test_lock_paths_are_relative_and_portable(tmp_path):
    (tmp_path / "depx").mkdir()
    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\ndepx = { path = "../depx" }\n')
    pkg.resolve(str(app / "btrc.toml"))
    lock = json.loads((app / "btrc.lock").read_text())
    assert lock["packages"]["depx"]["path"] == os.path.join("..", "depx")
    assert not os.path.isabs(lock["packages"]["depx"]["path"])

    # Relocate the whole tree: the lock still resolves (no absolute paths).
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(str(tmp_path / "depx"), str(moved / "depx"))
    shutil.move(str(app), str(moved / "app"))
    resolved = pkg.resolve(str(moved / "app" / "btrc.toml"))
    assert resolved["depx"]["path"] == str(moved / "depx")


def test_lock_git_entries_have_no_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(pkg, "_resolve_git",
                        lambda n, u, r, refresh=False: str(tmp_path / "clone"))
    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text(
        '[dependencies]\nnet = { git = "https://x/n.git", rev = "v1" }\n')
    resolved = pkg.resolve(str(app / "btrc.toml"), refresh=True)
    assert resolved["net"]["path"] == str(tmp_path / "clone")
    lock = json.loads((app / "btrc.lock").read_text())
    # Machine-local clone paths never enter the lock; (url, rev) does.
    assert lock["packages"]["net"] == {"git": "https://x/n.git", "rev": "v1"}
    # Loading the lock re-derives the clone path from the cache.
    again = pkg.resolve(str(app / "btrc.toml"))
    assert again["net"]["path"] == str(tmp_path / "clone")


# --------------------------------------------------------------------------
# library errors must not kill the host process (CMP-13)
# --------------------------------------------------------------------------

def test_configure_for_raises_not_exits(tmp_path):
    (tmp_path / "btrc.toml").write_text(
        '[dependencies]\nbad = { version = "1.0" }\n')
    with pytest.raises(IncludeResolutionError) as exc:
        pkg.configure_for(str(tmp_path / "main.btrc"), refresh=True)
    assert not isinstance(exc.value, SystemExit)
    assert "package resolution failed" in str(exc.value)
    assert pkg._PACKAGES == {}  # no stale state after failure


def test_package_import_paths_raises_not_exits(tmp_path):
    root = tmp_path / "dep"
    root.mkdir()
    pkg._PACKAGES = {"dep": {"path": str(root)}}
    try:
        with pytest.raises(IncludeResolutionError, match="not found"):
            pkg.package_import_paths("dep.missing_module")
    finally:
        pkg._PACKAGES = {}


def test_error_is_canonical_frontend_exception():
    from src.compiler.python.frontend import (
        IncludeResolutionError as FrontendError,
    )
    assert FrontendError is IncludeResolutionError
