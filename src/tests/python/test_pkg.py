"""Unit tests for the package manager (pkg.py)."""

import json
import os
import pathlib
import shutil
import subprocess

import pytest

from src.compiler.python import cache_io, manifest_io, pkg, pkg_git
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


def test_package_timeout_becomes_resolution_error(tmp_path, monkeypatch):
    manifest = tmp_path / "btrc.toml"
    manifest.write_text('[dependencies]\ndep = { git = "https://example.invalid/dep.git" }\n')

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["git", "clone"], 300)

    monkeypatch.setattr(pkg, "_resolve_git", timeout)
    with pytest.raises(IncludeResolutionError, match="package resolution failed"):
        pkg.packages_for(str(tmp_path / "main.btrc"))


def test_package_manifest_read_is_bounded_and_utf8(tmp_path):
    manifest = tmp_path / "btrc.toml"
    manifest.write_bytes(b"#" * (manifest_io.MAX_MANIFEST_BYTES + 1))
    with pytest.raises(ValueError, match="exceeds"):
        pkg.resolve(str(manifest))

    manifest.write_bytes(b"[package]\nname = '\xff'\n")
    with pytest.raises(ValueError, match="not valid UTF-8"):
        pkg.resolve(str(manifest))


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
    assert lock["schema"] == pkg.LOCK_SCHEMA

    # A fresh resolve trusts the still-matching lock and resolves the relative
    # path back against the lock's own directory.
    again = pkg.resolve(str(app / "btrc.toml"))
    assert again["mathx"]["path"] == resolved["mathx"]["path"]


def test_resolve_uses_existing_lock(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\nx = { path = "../x" }\n')
    (app / "btrc.lock").write_text(
        json.dumps(
            {
                "manifest_hash": pkg._deps_hash({"x": {"path": "../x"}}),
                "packages": {"x": {"path": "/pinned/location"}},
                "schema": pkg.LOCK_SCHEMA,
            }
        )
    )
    resolved = pkg.resolve(str(app / "btrc.toml"))
    assert resolved["x"]["path"] == "/pinned/location"  # fresh lock wins


def test_package_import_paths(tmp_path):
    dep = tmp_path / "mathx"
    (dep / "src").mkdir(parents=True)
    (dep / "src" / "mathx.btrc").write_text("class Mathx {}\n")
    (dep / "src" / "vec.btrc").write_text("class Vec {}\n")
    with pkg.package_context({"mathx": {"path": str(dep)}}):
        assert pkg.package_import_paths("mathx")[0].endswith("src/mathx.btrc")
        assert pkg.package_import_paths("mathx.vec")[0].endswith("src/vec.btrc")
        assert pkg.package_import_paths("not_a_dep") == []


# --------------------------------------------------------------------------
# git cache keying (URL-distinct deps must not share a clone)
# --------------------------------------------------------------------------


def test_git_cache_identity_includes_exact_url_and_ref():
    """The identity hashes exact bytes, including formerly-colliding refs."""
    url_a = "https://a.example/netkit.git"
    url_b = "https://b.example/netkit.git"
    identity = pkg_git.cache_identity
    assert identity("netkit", url_a, "v1.0") != identity("netkit", url_b, "v1.0")
    assert identity("netkit", url_a, "feature/a") != identity("netkit", url_a, "feature_a")


def _make_git_repo(root, marker):
    """Hermetic local git repo with one committed .btrc module."""
    root.mkdir(parents=True)
    (root / "lib.btrc").write_text(f"// {marker}\nint libfn() {{ return 1; }}\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    for cmd in (
        ["git", "init", "--quiet", "-b", "main", "."],
        ["git", "add", "."],
        ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "init"],
    ):
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
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-am", "two"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()
    pkg._resolve_git("dep", url, "main")
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()

    # ...and --fetch (refresh) re-pins to the new tip.
    refreshed = pkg._resolve_git("dep", url, "main", refresh=True)
    assert refreshed != clone
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()
    assert "rev two" in (pathlib.Path(refreshed) / "lib.btrc").read_text()


def test_pinned_sha_never_refetched(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    repo = _make_git_repo(tmp_path / "upstream", "immutable")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    checkout = pkg._resolve_git("dep", repo.as_uri(), sha)

    def unexpected_clone(*_args):
        raise AssertionError("an immutable cached SHA must not be refetched")

    monkeypatch.setattr(pkg_git, "_clone_to_temporary", unexpected_clone)
    assert pkg._resolve_git("dep", repo.as_uri(), sha, refresh=True) == checkout


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
    manifest.write_text('[dependencies]\nalpha = { path = "../alpha" }\nbeta = { path = "../beta" }\n')
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
    repo = _make_git_repo(tmp_path / "upstream", "locked")
    app = tmp_path / "app"
    app.mkdir()
    url = repo.as_uri()
    (app / "btrc.toml").write_text(f'[dependencies]\nnet = {{ git = "{url}", rev = "main" }}\n')
    resolved = pkg.resolve(str(app / "btrc.toml"), refresh=True)
    commit = pkg._resolved_git_commit(resolved["net"]["path"])
    lock = json.loads((app / "btrc.lock").read_text())
    # Machine-local clone paths never enter the lock; requested + resolved refs do.
    assert lock == {
        "manifest_hash": pkg._deps_hash({"net": {"git": url, "rev": "main"}}),
        "packages": {"net": {"commit": commit, "git": url, "rev": "main"}},
        "schema": pkg.LOCK_SCHEMA,
    }
    # Loading the lock re-derives the clone path from the cache.
    again = pkg.resolve(str(app / "btrc.toml"))
    assert again["net"] == resolved["net"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_branch_lock_pins_same_commit_across_fresh_caches(tmp_path, monkeypatch):
    repo = _make_git_repo(tmp_path / "upstream", "rev one")
    app = tmp_path / "app"
    app.mkdir()
    url = repo.as_uri()
    manifest = app / "btrc.toml"
    manifest.write_text(f'[dependencies]\ndep = {{ git = "{url}", rev = "main" }}\n')

    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "machine-a-cache"))
    first = pkg.resolve(str(manifest), refresh=True)
    pinned = first["dep"]["commit"]

    (repo / "lib.btrc").write_text("// rev two\nint libfn() { return 2; }\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-am", "two"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )

    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "machine-b-cache"))
    second = pkg.resolve(str(manifest))
    assert second["dep"]["commit"] == pinned
    assert pkg._resolved_git_commit(second["dep"]["path"]) == pinned
    assert "rev one" in (pathlib.Path(second["dep"]["path"]) / "lib.btrc").read_text()

    refreshed = pkg.resolve(str(manifest), refresh=True)
    assert refreshed["dep"]["commit"] != pinned
    assert "rev two" in (pathlib.Path(refreshed["dep"]["path"]) / "lib.btrc").read_text()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_formerly_colliding_refs_have_distinct_checkouts(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    repo = _make_git_repo(tmp_path / "upstream", "slash")
    subprocess.run(["git", "branch", "feature/a"], cwd=repo, check=True)

    (repo / "lib.btrc").write_text("// underscore\nint libfn() { return 2; }\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", "commit", "--quiet", "-am", "underscore"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "branch", "feature_a"], cwd=repo, check=True)

    slash = pkg._resolve_git("dep", repo.as_uri(), "feature/a", refresh=True)
    underscore = pkg._resolve_git("dep", repo.as_uri(), "feature_a", refresh=True)
    assert slash != underscore
    assert "slash" in (pathlib.Path(slash) / "lib.btrc").read_text()
    assert "underscore" in (pathlib.Path(underscore) / "lib.btrc").read_text()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_legacy_git_lock_migrates_to_schema_two_and_pins_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    repo = _make_git_repo(tmp_path / "upstream", "legacy")
    app = tmp_path / "app"
    app.mkdir()
    url = repo.as_uri()
    dependencies = {"dep": {"git": url, "rev": "main"}}
    (app / "btrc.toml").write_text(f'[dependencies]\ndep = {{ git = "{url}", rev = "main" }}\n')
    (app / "btrc.lock").write_text(
        json.dumps(
            {
                "manifest_hash": pkg._deps_hash(dependencies),
                "packages": {"dep": {"git": url, "rev": "main"}},
            }
        )
    )

    resolved = pkg.resolve(str(app / "btrc.toml"))
    lock = json.loads((app / "btrc.lock").read_text())
    assert lock["schema"] == pkg.LOCK_SCHEMA
    assert lock["packages"]["dep"]["rev"] == "main"
    assert lock["packages"]["dep"]["commit"] == resolved["dep"]["commit"]


def test_malformed_schema_two_lock_fails_closed_without_resolving_ref(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    dependencies = {"dep": {"git": "https://example.invalid/dep.git", "rev": "main"}}
    manifest = app / "btrc.toml"
    manifest.write_text('[dependencies]\ndep = { git = "https://example.invalid/dep.git", rev = "main" }\n')
    lock_path = app / "btrc.lock"
    lock_path.write_text(
        json.dumps(
            {
                "manifest_hash": pkg._deps_hash(dependencies),
                "packages": {
                    "dep": {
                        "commit": "not-a-commit",
                        "git": "https://example.invalid/dep.git",
                        "rev": "main",
                    }
                },
                "schema": pkg.LOCK_SCHEMA,
            }
        )
    )
    original = lock_path.read_bytes()

    def unexpected_resolution(*_args, **_kwargs):
        raise AssertionError("malformed v2 lock must not re-resolve a moving ref")

    monkeypatch.setattr(pkg, "_resolve_git", unexpected_resolution)
    with pytest.raises(pkg.LockfileError, match="invalid locked Git dependency"):
        pkg.resolve(str(manifest))
    assert lock_path.read_bytes() == original


def test_future_lock_schema_is_rejected_explicitly(tmp_path):
    manifest = tmp_path / "btrc.toml"
    manifest.write_text('[package]\nname = "future"\n')
    (tmp_path / "btrc.lock").write_text(
        json.dumps(
            {
                "manifest_hash": pkg._deps_hash({}),
                "packages": {},
                "schema": pkg.LOCK_SCHEMA + 1,
            }
        )
    )

    with pytest.raises(pkg.LockfileVersionError, match=r"unsupported btrc\.lock schema"):
        pkg.resolve(str(manifest))


def test_atomic_lock_write_failure_preserves_previous_lock(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    app = tmp_path / "app"
    app.mkdir()
    manifest = app / "btrc.toml"
    manifest.write_text('[dependencies]\nfirst = { path = "../first" }\n')
    pkg.resolve(str(manifest))
    previous = (app / "btrc.lock").read_bytes()

    manifest.write_text('[dependencies]\nsecond = { path = "../second" }\n')

    def interrupted(_source, _target):
        raise OSError("simulated crash before lock replace")

    monkeypatch.setattr(cache_io.os, "replace", interrupted)
    with pytest.raises(OSError, match="simulated crash"):
        pkg.resolve(str(manifest))

    assert (app / "btrc.lock").read_bytes() == previous
    assert not list(app.glob(".btrc-cache-*"))


# --------------------------------------------------------------------------
# library errors must not kill the host process (CMP-13)
# --------------------------------------------------------------------------


def test_configure_for_raises_not_exits(tmp_path):
    (tmp_path / "btrc.toml").write_text('[dependencies]\nbad = { version = "1.0" }\n')
    with pytest.raises(IncludeResolutionError) as exc:
        pkg.configure_for(str(tmp_path / "main.btrc"), refresh=True)
    assert not isinstance(exc.value, SystemExit)
    assert "package resolution failed" in str(exc.value)
    assert pkg.configured_packages() == {}  # no stale state after failure


def test_package_import_paths_raises_not_exits(tmp_path):
    root = tmp_path / "dep"
    root.mkdir()
    with (
        pkg.package_context({"dep": {"path": str(root)}}),
        pytest.raises(IncludeResolutionError, match="not found"),
    ):
        pkg.package_import_paths("dep.missing_module")


def test_error_is_canonical_frontend_exception():
    from src.compiler.python.frontend import (
        IncludeResolutionError as FrontendError,
    )

    assert FrontendError is IncludeResolutionError
