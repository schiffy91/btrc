"""Cache invalidation and cache-location tests (cache_keys, disk_cache,
frontend stdlib-AST cache, stdlib archive stamping).

Every cache must key itself with a *derived* toolchain hash (a compiler
change orphans stale entries automatically) and must resolve its directory
as $BTRC_CACHE_DIR > btrc.toml project root > user cache dir — never the
bare cwd.
"""

import json
import os
import sys

import pytest

from src.compiler.python import (
    cache_keys,
    disk_cache,
    frontend,
    frontend_stdlib,
    stdlib_archive,
)


@pytest.fixture
def clear_hash_memo(monkeypatch):
    """Run with an empty toolchain-hash memo so monkeypatched file lists bite."""
    monkeypatch.setattr(cache_keys, "_HASH_CACHE", {})


# --------------------------------------------------------------------------
# toolchain hash derivation
# --------------------------------------------------------------------------


def test_toolchain_hash_is_short_hex_and_memoized():
    h = cache_keys.toolchain_hash("frontend")
    assert len(h) == 16 and int(h, 16) >= 0
    assert cache_keys.toolchain_hash("frontend") is h  # memoized


def test_toolchain_hash_unknown_scope_rejected():
    with pytest.raises(ValueError):
        cache_keys.toolchain_hash("nonsense")


def test_full_scope_covers_codegen_sources():
    frontend_files = set(cache_keys._toolchain_files("frontend"))
    full_files = set(cache_keys._toolchain_files("full"))
    assert frontend_files < full_files
    extra = {os.path.relpath(p, cache_keys._COMPILER_DIR) for p in full_files - frontend_files}
    assert any(p.startswith("analyzer") for p in extra)
    assert any(p.startswith("ir") for p in extra)
    assert "main.py" in extra
    assert "cli_options.py" in extra
    # Parser sources are in both scopes; grammar + ASDL too.
    assert any(p.endswith("grammar.ebnf") for p in frontend_files)
    assert any(p.endswith("ast.asdl") for p in frontend_files)
    assert any(p.endswith("ast_nodes.py") for p in frontend_files)
    assert any(p.endswith("ast_codec.py") for p in frontend_files)
    assert any(p.endswith("frontend.py") for p in frontend_files)
    assert any(p.endswith("import_scan.py") for p in frontend_files)


def test_hash_changes_when_a_source_byte_changes(tmp_path, monkeypatch, clear_hash_memo):
    """Simulate editing a parser source: same file list, one byte different."""
    fake = tmp_path / "parser_file.py"
    fake.write_text("x = 1\n")
    monkeypatch.setattr(cache_keys, "_toolchain_files", lambda scope: [str(fake)])
    before = cache_keys.toolchain_hash("full")

    monkeypatch.setattr(cache_keys, "_HASH_CACHE", {})
    fake.write_text("x = 2\n")
    after = cache_keys.toolchain_hash("full")
    assert before != after


def test_hash_includes_source_path_not_only_basename(tmp_path, monkeypatch):
    first = tmp_path / "first" / "types.py"
    second = tmp_path / "second" / "types.py"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("same bytes\n")
    second.write_text("same bytes\n")
    monkeypatch.setattr(cache_keys, "_SRC_DIR", str(tmp_path))

    assert cache_keys._hash_paths([str(first)]) != cache_keys._hash_paths([str(second)])


def test_hash_differs_between_scopes():
    assert cache_keys.toolchain_hash("frontend") != cache_keys.toolchain_hash("full")


def test_disk_cache_key_covers_toolchain(monkeypatch):
    src = "int main() { return 0; }"
    k1 = disk_cache._cache_key(src)
    monkeypatch.setitem(cache_keys._HASH_CACHE, "full", "0" * 16)
    k2 = disk_cache._cache_key(src)
    assert k1 != k2  # a compiler change invalidates cached .c output


# --------------------------------------------------------------------------
# cache directory resolution
# --------------------------------------------------------------------------


def test_cache_dir_env_var_wins(tmp_path, monkeypatch):
    target = tmp_path / "envcache"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(target))
    assert cache_keys.resolve_cache_dir() == str(target)
    assert target.is_dir()  # created on resolve


def test_cache_dir_project_root_from_input_path(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    root = tmp_path / "proj"
    sub = root / "src" / "deep"
    sub.mkdir(parents=True)
    (root / "btrc.toml").write_text("[package]\nname = 'p'\n")
    got = cache_keys.resolve_cache_dir(str(sub / "main.btrc"))
    assert got == str(root / ".btrc-cache")
    assert (root / ".btrc-cache").is_dir()


def test_cache_dir_project_root_from_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    root = tmp_path / "proj2"
    root.mkdir()
    (root / "btrc.toml").write_text("[package]\nname = 'p'\n")
    monkeypatch.chdir(root)
    assert cache_keys.resolve_cache_dir() == str(root / ".btrc-cache")


def test_cache_dir_user_cache_fallback_not_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    workdir = tmp_path / "no_project_here"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    got = cache_keys.resolve_cache_dir()
    assert got.startswith(str(fake_home))  # user cache dir, expanded via $HOME
    assert got.endswith(os.path.join("btrc"))
    assert str(workdir) not in got  # never the invoking cwd
    assert not (workdir / ".btrc-cache").exists()


@pytest.mark.skipif(sys.platform == "darwin", reason="XDG only used off-macOS")
def test_cache_dir_xdg_respected(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    assert cache_keys.resolve_cache_dir() == str(tmp_path / "xdg" / "btrc")


def test_disk_cache_roundtrip_in_resolved_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "c"))
    assert disk_cache.get_cached("src-A") is None
    disk_cache.store("src-A", "/* c output */")
    assert disk_cache.get_cached("src-A") == "/* c output */"
    names = os.listdir(tmp_path / "c")
    assert len(names) == 1 and names[0].endswith(".c")


def test_disk_cache_input_path_anchors_project_root(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    root = tmp_path / "proj"
    root.mkdir()
    (root / "btrc.toml").write_text("[package]\nname = 'p'\n")
    monkeypatch.chdir(tmp_path)  # cwd is NOT the project
    disk_cache.store("src-B", "out", input_path=str(root / "main.btrc"))
    assert os.listdir(root / ".btrc-cache")  # cache landed in the project
    assert not (tmp_path / ".btrc-cache").exists()
    assert disk_cache.get_cached("src-B", input_path=str(root / "main.btrc")) == "out"


# --------------------------------------------------------------------------
# stdlib-AST cache invalidation
# --------------------------------------------------------------------------


def test_stdlib_ast_version_is_derived():
    assert cache_keys.toolchain_hash("frontend") == frontend._STDLIB_AST_VERSION


def test_stale_stdlib_ast_is_not_served_after_toolchain_change(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "c"))
    src = "class CacheProbe { public int x; public CacheProbe(int x) { self.x = x; } }\n"
    first = frontend._cached_stdlib_decls(src)
    assert first
    artifacts = os.listdir(tmp_path / "c")
    assert len(artifacts) == 1 and artifacts[0].endswith(".ast.json")

    # A toolchain change produces a different AST version -> different key:
    # the old JSON entry is orphaned, never served.
    monkeypatch.setattr(frontend_stdlib, "_STDLIB_AST_VERSION", "f" * 16)
    frontend._cached_stdlib_decls(src)
    assert len(os.listdir(tmp_path / "c")) == 2  # reparsed + stored under new key


# --------------------------------------------------------------------------
# stdlib archive stamping
# --------------------------------------------------------------------------


def _archive_manifest(stdlib_source: str, **overrides):
    manifest = {
        "schema": stdlib_archive.MANIFEST_SCHEMA,
        "stdlib_source": stdlib_archive._stdlib_source_hash(stdlib_source),
        "toolchain": cache_keys.toolchain_hash("full"),
        "macros": [],
        **{field: [] for field in stdlib_archive._MANIFEST_LIST_FIELDS},
    }
    manifest.update(overrides)
    return manifest


def test_archive_manifest_is_stamped_and_validated(tmp_path):
    source = "stdlib source"
    manifest = _archive_manifest(source)
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(json.dumps(manifest))
    assert stdlib_archive.load_manifest(str(tmp_path), source)["types"] == []


@pytest.mark.parametrize(
    "macro",
    [
        {
            "name": "LEGACY",
            "params": None,
            "replacement": "1",
            "before_includes": False,
        },
        {"name": "7BAD", "params": None, "replacement": "1"},
        {"name": "BAD", "params": ["x", "x"], "replacement": "x"},
        {"name": "BAD", "params": None, "replacement": "one\ntwo"},
    ],
)
def test_archive_manifest_refuses_invalid_typed_macro_records(
    tmp_path,
    macro,
):
    source = "stdlib source"
    manifest = _archive_manifest(source, macros=[macro])
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(json.dumps(manifest))

    with pytest.raises(
        stdlib_archive.ArchiveVersionError,
        match="invalid or unsupported",
    ):
        stdlib_archive.load_manifest(str(tmp_path), source)


def test_archive_manifest_refused_on_toolchain_mismatch(tmp_path):
    source = "stdlib source"
    stale = _archive_manifest(source, toolchain="0" * 16)
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(json.dumps(stale))
    with pytest.raises(stdlib_archive.ArchiveVersionError, match="different compiler"):
        stdlib_archive.load_manifest(str(tmp_path), source)


def test_archive_manifest_refused_on_stdlib_source_mismatch(tmp_path):
    manifest = _archive_manifest("archive stdlib")
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(json.dumps(manifest))

    with pytest.raises(stdlib_archive.ArchiveVersionError, match="different standard library"):
        stdlib_archive.load_manifest(str(tmp_path), "current or user-overridden stdlib")


def test_raw_top_level_manifest_requires_regeneration(tmp_path):
    source = "stdlib source"
    stale = _archive_manifest(source)
    stale["schema"] = 3
    stale.pop("macros")
    stale["raw_sections"] = ["#define LEGACY 1"]
    stale["vtables"] = ["legacy vtable text"]
    stale["globals"] = ["int legacy;"]
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(json.dumps(stale))

    with pytest.raises(
        stdlib_archive.ArchiveVersionError,
        match=r"invalid or unsupported.*regenerate",
    ):
        stdlib_archive.load_manifest(str(tmp_path), source)


@pytest.mark.parametrize("payload", ["not json", "{}", '{"schema":1,"types":"wrong"}'])
def test_archive_manifest_refuses_corrupt_or_unsupported_schema(tmp_path, payload):
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(payload)

    with pytest.raises(stdlib_archive.ArchiveVersionError, match="invalid or unsupported"):
        stdlib_archive.load_manifest(str(tmp_path), "stdlib source")
