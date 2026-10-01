"""Unit tests for the package universe."""

import ast
import json
import os
import pathlib
import shutil
import stat
import subprocess

import pytest

import src.compiler.python.artifacts.cache as artifact_cache
import src.compiler.python.frontend.packages as packages
from src.compiler.python.frontend.packages import (
    GitDependencyCache,
    IncludeResolutionError,
    PackageManifestReader,
)
from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT

GIT = GitDependencyCache()
RESOLVER = packages.PackageUniverse(GIT)


def test_git_dependency_behavior_is_owned_by_the_package_resolver(tmp_path):
    module = ast.parse(pathlib.Path(packages.__file__).read_text())
    loose_behavior = [node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    git_dependencies = GitDependencyCache(str(tmp_path / "cache"))
    resolver = packages.PackageUniverse(git_dependencies)

    assert loose_behavior == []
    assert resolver.git_dependencies is git_dependencies


def test_package_resolver_owns_manifest_reads(tmp_path):
    reader = PackageManifestReader()
    resolver = packages.PackageUniverse(manifest_reader=reader)

    assert resolver.manifest_reader is reader
    assert resolver.file_store is reader.file_store
    assert resolver.git_dependencies.file_store is reader.file_store
    assert not (pathlib.Path(packages.__file__).with_name("manifest_io.py")).exists()


def test_find_manifest_walks_up(tmp_path):
    root = tmp_path / "proj"
    sub = root / "a" / "b"
    sub.mkdir(parents=True)
    (root / "btrc.toml").write_text("[package]\nname = 'p'\n")
    assert RESOLVER.find_manifest(str(sub)) == str(root / "btrc.toml")


def test_find_manifest_none(tmp_path):
    d = tmp_path / "nowhere"
    d.mkdir()
    assert RESOLVER.find_manifest(str(d)) is None


@pytest.mark.skipif(os.name == "nt", reason="final-symlink manifest contract is POSIX-only")
def test_resolve_accepts_final_symlink_manifest(tmp_path):
    target = tmp_path / "manifest-source.toml"
    target.write_text("[package]\nname = 'linked'\n")
    manifest = tmp_path / "btrc.toml"
    manifest.symlink_to(target.name)

    assert RESOLVER.resolve_manifest(str(manifest)).entries == {}


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are unavailable")
def test_resolve_rejects_nonregular_manifest(tmp_path):
    manifest = tmp_path / "btrc.toml"
    os.mkfifo(manifest)

    with pytest.raises(ValueError, match="not a regular file"):
        RESOLVER.resolve_manifest(str(manifest))


def test_package_timeout_becomes_resolution_error(tmp_path, monkeypatch):
    manifest = tmp_path / "btrc.toml"
    manifest.write_text('[dependencies]\ndep = { git = "https://example.invalid/dep.git" }\n')

    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(["git", "clone"], 300)

    monkeypatch.setattr(GIT, "resolve", timeout)
    with pytest.raises(IncludeResolutionError, match="package resolution failed"):
        RESOLVER.resolve_for(str(tmp_path / "Main.btrc"))


def test_package_manifest_read_reports_encoding_faults(tmp_path):
    manifest = tmp_path / "btrc.toml"
    manifest.write_bytes(b"[package]\nname = '\xff'\n")
    with pytest.raises(ValueError, match="not valid UTF-8"):
        RESOLVER.resolve_manifest(str(manifest))


def test_resolve_path_dep_writes_lock(tmp_path):
    dep = tmp_path / "mathx"
    (dep / "src").mkdir(parents=True)
    (dep / "src" / "mathx.btrc").write_text("class Mathx {}\n")
    (dep / "btrc.toml").write_text("[package]\nname = 'mathx'\n")

    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\nmathx = { path = "../mathx" }\n')

    resolved = RESOLVER.resolve_manifest(str(app / "btrc.toml")).entries
    assert "mathx" in resolved
    assert os.path.isdir(resolved["mathx"]["path"])
    lock = json.loads((app / "btrc.lock").read_text())
    # Lock paths are relative to the lock file (reproducible across checkouts)
    # and stamped with the manifest's dependency-table hash.
    assert lock["packages"]["mathx"]["path"] == os.path.join("..", "mathx")
    assert lock["manifest_hash"] == RESOLVER.dependencies_hash({"mathx": {"path": "../mathx"}})
    assert lock["schema"] == packages.LOCK_SCHEMA
    if os.name != "nt":
        assert stat.S_IMODE((app / "btrc.lock").stat().st_mode) == 0o644

    # A fresh resolve trusts the still-matching lock and resolves the relative
    # path back against the lock's own directory.
    again = RESOLVER.resolve_manifest(str(app / "btrc.toml")).entries
    assert again["mathx"]["path"] == resolved["mathx"]["path"]


def test_resolve_uses_existing_lock(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\nx = { path = "../x" }\n')
    (app / "btrc.lock").write_text(
        json.dumps(
            {
                "manifest_hash": RESOLVER.dependencies_hash({"x": {"path": "../x"}}),
                "packages": {"x": {"path": "/pinned/location"}},
                "schema": packages.LOCK_SCHEMA,
            }
        )
    )
    resolved = RESOLVER.resolve_manifest(str(app / "btrc.toml")).entries
    assert resolved["x"]["path"] == "/pinned/location"  # fresh lock wins


def test_resolved_packages_find_import_modules(tmp_path):
    dep = tmp_path / "mathx"
    (dep / "src").mkdir(parents=True)
    (dep / "src" / "mathx.btrc").write_text("class Mathx {}\n")
    (dep / "src" / "vec.btrc").write_text("class Vec {}\n")
    resolved_packages = packages.ResolvedPackages(None, {"mathx": {"path": str(dep)}})
    assert resolved_packages.paths_for_import("mathx")[0].endswith("src/mathx.btrc")
    assert resolved_packages.paths_for_import("mathx.vec")[0].endswith("src/vec.btrc")
    assert resolved_packages.paths_for_import("not_a_dep") == ()


# --------------------------------------------------------------------------
# git cache keying (URL-distinct deps must not share a clone)
# --------------------------------------------------------------------------


def test_git_cache_identity_includes_exact_url_and_ref():
    """The identity hashes exact bytes, including formerly-colliding refs."""
    url_a = "https://a.example/netkit.git"
    url_b = "https://b.example/netkit.git"
    identity = GIT.cache_identity
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
        subprocess.run(cmd, cwd=root, env=env, check=True, capture_output=True, timeout=C_COMPILE_TIMEOUT)
    return root


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_git_branch_dep_repinned_on_refresh(tmp_path, monkeypatch):
    """A branch rev is pinned by the first clone and advanced by --fetch."""
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    repo = _make_git_repo(tmp_path / "upstream", "rev one")
    url = repo.as_uri()  # hermetic local file:// URL — no network

    clone = GIT.resolve("dep", url, "main")
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
        timeout=TOOL_TIMEOUT,
    )
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()
    GIT.resolve("dep", url, "main")
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()

    # ...and --fetch (refresh) re-pins to the new tip.
    refreshed = GIT.resolve("dep", url, "main", refresh=True)
    assert refreshed != clone
    assert "rev one" in (pathlib.Path(clone) / "lib.btrc").read_text()
    assert "rev two" in (pathlib.Path(refreshed) / "lib.btrc").read_text()


def test_pinned_sha_never_refetched(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    repo = _make_git_repo(tmp_path / "upstream", "immutable")
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True, timeout=TOOL_TIMEOUT
    ).stdout.strip()
    checkout = GIT.resolve("dep", repo.as_uri(), sha)

    def unexpected_clone(*_args):
        raise AssertionError("an immutable cached SHA must not be refetched")

    monkeypatch.setattr(GIT, "_clone_to_temporary", unexpected_clone)
    assert GIT.resolve("dep", repo.as_uri(), sha, refresh=True) == checkout


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
    first = RESOLVER.resolve_manifest(str(manifest)).entries
    assert set(first) == {"alpha"}

    # Adding a dep must take effect WITHOUT --fetch.
    manifest.write_text('[dependencies]\nalpha = { path = "../alpha" }\nbeta = { path = "../beta" }\n')
    second = RESOLVER.resolve_manifest(str(manifest)).entries
    assert set(second) == {"alpha", "beta"}
    lock = json.loads((app / "btrc.lock").read_text())
    assert set(lock["packages"]) == {"alpha", "beta"}


def test_lock_paths_are_relative_and_portable(tmp_path):
    (tmp_path / "depx").mkdir()
    app = tmp_path / "app"
    app.mkdir()
    (app / "btrc.toml").write_text('[dependencies]\ndepx = { path = "../depx" }\n')
    RESOLVER.resolve_manifest(str(app / "btrc.toml"))
    lock = json.loads((app / "btrc.lock").read_text())
    assert lock["packages"]["depx"]["path"] == os.path.join("..", "depx")
    assert not os.path.isabs(lock["packages"]["depx"]["path"])

    # Relocate the whole tree: the lock still resolves (no absolute paths).
    moved = tmp_path / "moved"
    moved.mkdir()
    shutil.move(str(tmp_path / "depx"), str(moved / "depx"))
    shutil.move(str(app), str(moved / "app"))
    resolved = RESOLVER.resolve_manifest(str(moved / "app" / "btrc.toml")).entries
    assert resolved["depx"]["path"] == str(moved / "depx")


def test_lock_git_entries_have_no_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    repo = _make_git_repo(tmp_path / "upstream", "locked")
    app = tmp_path / "app"
    app.mkdir()
    url = repo.as_uri()
    (app / "btrc.toml").write_text(f'[dependencies]\nnet = {{ git = "{url}", rev = "main" }}\n')
    resolved = RESOLVER.resolve_manifest(
        str(app / "btrc.toml"),
        refresh=True,
    ).entries
    commit = GIT.resolved_commit(resolved["net"]["path"])
    lock = json.loads((app / "btrc.lock").read_text())
    # Machine-local clone paths never enter the lock; requested + resolved refs do.
    assert lock == {
        "manifest_hash": RESOLVER.dependencies_hash({"net": {"git": url, "rev": "main"}}),
        "packages": {"net": {"commit": commit, "git": url, "rev": "main"}},
        "schema": packages.LOCK_SCHEMA,
    }
    # Loading the lock re-derives the clone path from the cache.
    again = RESOLVER.resolve_manifest(str(app / "btrc.toml")).entries
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
    first = RESOLVER.resolve_manifest(str(manifest), refresh=True).entries
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
        timeout=TOOL_TIMEOUT,
    )

    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "machine-b-cache"))
    second = RESOLVER.resolve_manifest(str(manifest)).entries
    assert second["dep"]["commit"] == pinned
    assert GIT.resolved_commit(second["dep"]["path"]) == pinned
    assert "rev one" in (pathlib.Path(second["dep"]["path"]) / "lib.btrc").read_text()

    refreshed = RESOLVER.resolve_manifest(str(manifest), refresh=True).entries
    assert refreshed["dep"]["commit"] != pinned
    assert "rev two" in (pathlib.Path(refreshed["dep"]["path"]) / "lib.btrc").read_text()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_formerly_colliding_refs_have_distinct_checkouts(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    repo = _make_git_repo(tmp_path / "upstream", "slash")
    subprocess.run(["git", "branch", "feature/a"], cwd=repo, check=True, timeout=TOOL_TIMEOUT)

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
        timeout=TOOL_TIMEOUT,
    )
    subprocess.run(["git", "branch", "feature_a"], cwd=repo, check=True, timeout=TOOL_TIMEOUT)

    slash = GIT.resolve("dep", repo.as_uri(), "feature/a", refresh=True)
    underscore = GIT.resolve(
        "dep",
        repo.as_uri(),
        "feature_a",
        refresh=True,
    )
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
                "manifest_hash": RESOLVER.dependencies_hash(dependencies),
                "packages": {"dep": {"git": url, "rev": "main"}},
            }
        )
    )

    resolved = RESOLVER.resolve_manifest(str(app / "btrc.toml")).entries
    lock = json.loads((app / "btrc.lock").read_text())
    assert lock["schema"] == packages.LOCK_SCHEMA
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
                "manifest_hash": RESOLVER.dependencies_hash(dependencies),
                "packages": {
                    "dep": {
                        "commit": "not-a-commit",
                        "git": "https://example.invalid/dep.git",
                        "rev": "main",
                    }
                },
                "schema": packages.LOCK_SCHEMA,
            }
        )
    )
    original = lock_path.read_bytes()

    def unexpected_resolution(*_args, **_kwargs):
        raise AssertionError("malformed v2 lock must not re-resolve a moving ref")

    monkeypatch.setattr(GIT, "resolve", unexpected_resolution)
    with pytest.raises(packages.LockfileError, match="invalid locked Git dependency"):
        RESOLVER.resolve_manifest(str(manifest))
    assert lock_path.read_bytes() == original


def test_future_lock_schema_is_rejected_explicitly(tmp_path):
    manifest = tmp_path / "btrc.toml"
    manifest.write_text('[package]\nname = "future"\n')
    (tmp_path / "btrc.lock").write_text(
        json.dumps(
            {
                "manifest_hash": RESOLVER.dependencies_hash({}),
                "packages": {},
                "schema": packages.LOCK_SCHEMA + 1,
            }
        )
    )

    with pytest.raises(packages.LockfileVersionError, match=r"unsupported btrc\.lock schema"):
        RESOLVER.resolve_manifest(str(manifest))


def test_atomic_lock_write_failure_preserves_previous_lock(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    app = tmp_path / "app"
    app.mkdir()
    manifest = app / "btrc.toml"
    manifest.write_text('[dependencies]\nfirst = { path = "../first" }\n')
    RESOLVER.resolve_manifest(str(manifest))
    previous = (app / "btrc.lock").read_bytes()

    manifest.write_text('[dependencies]\nsecond = { path = "../second" }\n')

    def interrupted(_source, _target):
        raise OSError("simulated crash before lock replace")

    monkeypatch.setattr(artifact_cache.os, "replace", interrupted)
    with pytest.raises(OSError, match="simulated crash"):
        RESOLVER.resolve_manifest(str(manifest))

    assert (app / "btrc.lock").read_bytes() == previous
    assert not list(app.glob(".btrc-cache-*"))


# --------------------------------------------------------------------------
# library errors must not kill the host process (CMP-13)
# --------------------------------------------------------------------------


def test_resolve_for_raises_not_exits(tmp_path):
    (tmp_path / "btrc.toml").write_text('[dependencies]\nbad = { version = "1.0" }\n')
    with pytest.raises(IncludeResolutionError) as exc:
        RESOLVER.resolve_for(str(tmp_path / "Main.btrc"), refresh=True)
    assert not isinstance(exc.value, SystemExit)
    assert "package resolution failed" in str(exc.value)


def test_missing_resolved_package_module_raises_not_exits(tmp_path):
    root = tmp_path / "dep"
    root.mkdir()
    resolved_packages = packages.ResolvedPackages(None, {"dep": {"path": str(root)}})
    with pytest.raises(IncludeResolutionError, match="not found"):
        resolved_packages.paths_for_import("dep.missing_module")


def test_error_is_canonical_frontend_exception():
    from src.compiler.python.frontend.packages import IncludeResolutionError as FrontendError

    assert FrontendError is IncludeResolutionError


# --------------------------------------------------------------------------
# dependency entry shapes
# --------------------------------------------------------------------------


def test_resolve_dep_bare_string(tmp_path):
    d = RESOLVER._resolve_dependency(
        "x",
        "../sibling",
        str(tmp_path),
    )
    assert os.path.isabs(d["path"])


def test_resolve_dep_path_dict_relative(tmp_path):
    d = RESOLVER._resolve_dependency(
        "x",
        {"path": "../sib"},
        str(tmp_path),
    )
    assert d["path"].endswith("sib") and os.path.isabs(d["path"])


def test_resolve_dep_path_dict_absolute():
    d = RESOLVER._resolve_dependency(
        "x",
        {"path": "/abs/path"},
        "/manifest",
    )
    assert d["path"] == "/abs/path"


def test_resolve_dep_git(monkeypatch):
    monkeypatch.setattr(
        GIT,
        "resolve",
        lambda n, u, r, refresh=False: "/clone/root",
    )
    monkeypatch.setattr(GIT, "resolved_commit", lambda _path: "a" * 40)
    d = RESOLVER._resolve_dependency(
        "net",
        {"git": "https://x/n.git", "rev": "v1"},
        "/m",
    )
    assert d == {
        "commit": "a" * 40,
        "git": "https://x/n.git",
        "path": "/clone/root",
        "rev": "v1",
    }


def test_resolve_dep_invalid():
    with pytest.raises(ValueError):
        RESOLVER._resolve_dependency(
            "x",
            {"version": "1.0"},
            "/m",
        )


# --------------------------------------------------------------------------
# git checkouts
# --------------------------------------------------------------------------


def _fake_git_run(calls):
    """subprocess.run stand-in: records commands, reports success."""

    def run(cmd, *a, **k):
        calls.append(cmd)
        output = "a" * 40 + "\n" if "rev-parse" in cmd else ""
        return subprocess.CompletedProcess(cmd, 0, output, "")

    return run


def test_resolve_git_clones(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(packages.subprocess, "run", _fake_git_run(calls))
    path = GIT.resolve("net", "https://x/n.git", "v1")
    assert os.path.isabs(path) and len(calls) == 3  # clone + checkout + rev-parse


def test_resolve_git_uses_pinned_ref_record(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    record = GIT._ref_record_path("net", "https://x/n.git", "v1")
    GIT._publish_ref_record(record, "net", "https://x/n.git", "v1", "a" * 40)
    observed = []

    def pinned(name, url, rev, commit):
        observed.append((name, url, rev, commit))
        return "/immutable/checkout"

    monkeypatch.setattr(GIT, "_ensure_commit_checkout", pinned)
    assert GIT.resolve("net", "https://x/n.git", "v1") == "/immutable/checkout"
    assert observed == [("net", "https://x/n.git", "v1", "a" * 40)]


def test_resolve_git_separates_url_from_options(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(packages.subprocess, "run", _fake_git_run(calls))
    GIT.resolve("net", "--upload-pack=untrusted", "v1")
    assert calls[0][0:4] == ["git", "clone", "--quiet", "--"]
    assert calls[0][4] == "--upload-pack=untrusted"


def test_git_subprocesses_are_noninteractive_and_bounded(monkeypatch):
    observed = {}

    def run(cmd, **kwargs):
        observed.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(packages.subprocess, "run", run)
    GIT._git(["status"])

    assert observed["check"] is True
    assert observed["timeout"] == GIT.GIT_TIMEOUT_SECONDS
    assert observed["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert observed["env"]["GCM_INTERACTIVE"] == "Never"


def test_resolve_git_rejects_option_revision(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_PKG_CACHE", str(tmp_path / "cache"))
    calls = []
    monkeypatch.setattr(packages.subprocess, "run", _fake_git_run(calls))
    with pytest.raises(ValueError, match="invalid revision"):
        GIT.resolve("net", "https://x/n.git", "--orphan")
    assert calls == []


def test_failed_git_checkout_does_not_poison_cache(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    monkeypatch.setenv("BTRC_PKG_CACHE", str(cache))
    monkeypatch.setattr(GIT, "_git", lambda _args: None)

    def fail_checkout(_dest, _rev):
        raise ValueError("bad revision")

    monkeypatch.setattr(GIT, "_checkout", fail_checkout)

    with pytest.raises(ValueError, match="bad revision"):
        GIT.resolve("net", "https://x/n.git", "missing")

    assert list(cache.iterdir()) == []


# --------------------------------------------------------------------------
# manifest + lock resolution
# --------------------------------------------------------------------------


def test_resolve_uses_lock(tmp_path):
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n')
    lock = {
        "manifest_hash": RESOLVER.dependencies_hash({}),
        "packages": {"dep": {"path": "/p"}},
        "schema": packages.LOCK_SCHEMA,
    }
    (tmp_path / "btrc.lock").write_text(json.dumps(lock))
    resolved = RESOLVER.resolve_manifest(str(tmp_path / "btrc.toml"))
    assert resolved.entries == {"dep": {"path": "/p"}}


def test_resolve_ignores_stale_lock(tmp_path):
    # Legacy (hash-less) and out-of-date locks are re-resolved, not trusted.
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n')
    (tmp_path / "btrc.lock").write_text('{"packages": {"dep": {"path": "/p"}}}')
    assert RESOLVER.resolve_manifest(str(tmp_path / "btrc.toml")).entries == {}


@pytest.mark.parametrize(
    "lock",
    [
        [],
        {"packages": [], "schema": packages.LOCK_SCHEMA},
        {"packages": {"dep": []}, "schema": packages.LOCK_SCHEMA},
        {"packages": {"dep": {"path": 1}}, "schema": packages.LOCK_SCHEMA},
        {
            "packages": {"dep": {"commit": "a" * 40, "git": 1, "rev": "main"}},
            "schema": packages.LOCK_SCHEMA,
        },
        {
            "packages": {"dep": {"commit": "bad", "git": "https://x/n.git", "rev": "main"}},
            "schema": packages.LOCK_SCHEMA,
        },
    ],
)
def test_resolve_fails_closed_on_structurally_invalid_current_lock(tmp_path, lock):
    manifest = tmp_path / "btrc.toml"
    manifest.write_text('[package]\nname = "x"\n')
    if isinstance(lock, dict):
        lock["manifest_hash"] = RESOLVER.dependencies_hash({})
    (tmp_path / "btrc.lock").write_text(json.dumps(lock))
    before = (tmp_path / "btrc.lock").read_bytes()
    with pytest.raises(packages.LockfileError):
        RESOLVER.resolve_manifest(str(manifest))
    assert (tmp_path / "btrc.lock").read_bytes() == before


def test_resolve_for_invalid_dependency_shape_is_controlled(tmp_path):
    (tmp_path / "btrc.toml").write_text("dependencies = 1\n")
    with pytest.raises(IncludeResolutionError, match=r"dependencies.*table"):
        RESOLVER.resolve_for(str(tmp_path / "Main.btrc"))


def test_resolve_writes_lock(tmp_path):
    (tmp_path / "sib").mkdir()
    (tmp_path / "btrc.toml").write_text('[package]\nname = "x"\n[dependencies]\nsib = { path = "./sib" }\n')
    result = RESOLVER.resolve_manifest(
        str(tmp_path / "btrc.toml"),
        refresh=True,
    )
    assert "sib" in result.entries and (tmp_path / "btrc.lock").exists()


def test_resolve_for_no_manifest(tmp_path):
    assert RESOLVER.resolve_for(str(tmp_path / "x.btrc")).entries == {}


# --------------------------------------------------------------------------
# resolved package module lookup
# --------------------------------------------------------------------------


def test_resolved_packages_ignore_unknown_dependency():
    assert packages.ResolvedPackages.empty().paths_for_import("unknowndep.mod") == ()


def test_resolved_packages_support_root_layout(tmp_path):
    root = tmp_path / "vec"
    root.mkdir()
    (root / "sub.btrc").write_text("int f() { return 0; }\n")
    resolved_packages = packages.ResolvedPackages(None, {"vec": {"path": str(root)}})
    paths = resolved_packages.paths_for_import("vec.sub")
    assert paths and paths[0].endswith("sub.btrc")
