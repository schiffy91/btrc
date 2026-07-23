"""Cache invalidation and cache-location tests (owned compiler caches,
frontend stdlib-AST cache, stdlib archive stamping).

Every cache must key itself with a *derived* toolchain hash (a compiler
change orphans stale entries automatically) and must resolve its directory
as $BTRC_CACHE_DIR > btrc.toml project root > user cache dir — never the
bare cwd.
"""

import hashlib
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.compiler.python import (
    stdlib_archive,
)
from src.compiler.python.artifacts.cache.compiler_cache import (
    CacheDirectory,
    CompilationCache,
    ToolchainFingerprint,
    ToolchainSourceInventory,
)
from src.compiler.python.artifacts.publication.publisher import ArtifactPublisher
from src.compiler.python.artifacts.publication.storage import ArtifactStorage
from src.compiler.python.artifacts.stdlib.publisher import StdlibArchivePublisher
from src.compiler.python.frontend.stdlib import StdlibRepository

STDLIB = StdlibRepository()


def _archive_publisher() -> StdlibArchivePublisher:
    return StdlibArchivePublisher(ArtifactPublisher(ArtifactStorage()))


class FixedFingerprint:
    def __init__(self, value: str) -> None:
        self.value = value

    def digest(self, _scope: str = "full") -> str:
        return self.value


class SingleFileInventory:
    def __init__(self, source_directory: str, path: str) -> None:
        self.source_directory = source_directory
        self._path = path

    def files(self, _scope: str) -> tuple[str, ...]:
        return (self._path,)


# --------------------------------------------------------------------------
# toolchain hash derivation
# --------------------------------------------------------------------------


def test_toolchain_hash_is_short_hex_and_memoized():
    fingerprint = ToolchainFingerprint()
    h = fingerprint.digest("frontend")
    assert len(h) == 16 and int(h, 16) >= 0
    assert fingerprint.digest("frontend") is h  # memoized by this owner


def test_toolchain_hash_unknown_scope_rejected():
    with pytest.raises(ValueError):
        ToolchainFingerprint().digest("nonsense")


def test_full_scope_covers_codegen_sources():
    inventory = ToolchainSourceInventory.canonical()
    frontend_files = set(inventory.files("frontend"))
    full_files = set(inventory.files("full"))
    assert frontend_files < full_files
    extra = {os.path.relpath(path, inventory.compiler_directory) for path in full_files - frontend_files}
    assert any(p.startswith("analyzer") for p in extra)
    assert any(p.startswith("ir") for p in extra)
    assert "main.py" in extra
    assert "cli/compiler_cli.py" in extra
    # Parser sources are in both scopes; grammar + ASDL too.
    assert any(p.endswith("grammar.ebnf") for p in frontend_files)
    assert any(p.endswith("ast.asdl") for p in frontend_files)
    assert any(p.endswith("ast_nodes.py") for p in frontend_files)
    assert any(p.endswith("ast_codec.py") for p in frontend_files)
    assert any(p.endswith("frontend/resolver.py") for p in frontend_files)
    assert any(p.endswith("frontend/visibility.py") for p in frontend_files)
    assert any(p.endswith("frontend/source_io.py") for p in frontend_files)


def test_hash_changes_when_a_source_byte_changes(tmp_path):
    """Simulate editing a parser source: same file list, one byte different."""
    fake = tmp_path / "parser_file.py"
    fake.write_text("x = 1\n")
    inventory = SingleFileInventory(str(tmp_path), str(fake))
    before = ToolchainFingerprint(inventory).digest("full")

    fake.write_text("x = 2\n")
    after = ToolchainFingerprint(inventory).digest("full")
    assert before != after


def test_toolchain_hash_memo_is_owned_by_each_fingerprint(tmp_path):
    source = tmp_path / "compiler.py"
    source.write_text("before\n")
    inventory = SingleFileInventory(str(tmp_path), str(source))
    first_owner = ToolchainFingerprint(inventory)
    before = first_owner.digest()

    source.write_text("after\n")

    assert first_owner.digest() == before
    assert ToolchainFingerprint(inventory).digest() != before


def test_toolchain_hash_owner_serializes_concurrent_first_access(tmp_path):
    source = tmp_path / "compiler.py"
    source.write_text("stable\n")

    class CountingInventory(SingleFileInventory):
        def __init__(self):
            super().__init__(str(tmp_path), str(source))
            self.calls = 0

        def files(self, scope: str) -> tuple[str, ...]:
            self.calls += 1
            return super().files(scope)

    inventory = CountingInventory()
    fingerprint = ToolchainFingerprint(inventory)
    start = threading.Barrier(8)

    def digest_after_barrier(_index: int) -> str:
        start.wait()
        return fingerprint.digest("full")

    with ThreadPoolExecutor(max_workers=8) as workers:
        digests = list(workers.map(digest_after_barrier, range(8)))

    assert len(set(digests)) == 1
    assert inventory.calls == 1


def test_hash_includes_source_path_not_only_basename(tmp_path):
    first = tmp_path / "first" / "types.py"
    second = tmp_path / "second" / "types.py"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("same bytes\n")
    second.write_text("same bytes\n")
    first_fingerprint = ToolchainFingerprint(SingleFileInventory(str(tmp_path), str(first)))
    second_fingerprint = ToolchainFingerprint(SingleFileInventory(str(tmp_path), str(second)))
    assert first_fingerprint.digest() != second_fingerprint.digest()


def test_hash_differs_between_scopes():
    fingerprint = ToolchainFingerprint()
    assert fingerprint.digest("frontend") != fingerprint.digest("full")


def test_disk_cache_key_covers_toolchain():
    src = "int main() { return 0; }"
    k1 = CompilationCache(fingerprint=FixedFingerprint("1" * 16)).key_for(src)
    k2 = CompilationCache(fingerprint=FixedFingerprint("0" * 16)).key_for(src)
    assert k1 != k2  # a compiler change invalidates cached .c output


# --------------------------------------------------------------------------
# cache directory resolution
# --------------------------------------------------------------------------


def test_cache_dir_env_var_wins(tmp_path, monkeypatch):
    target = tmp_path / "envcache"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(target))
    assert CacheDirectory().resolve() == str(target)
    assert target.is_dir()  # created on resolve


def test_cache_dir_project_root_from_input_path(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    root = tmp_path / "proj"
    sub = root / "src" / "deep"
    sub.mkdir(parents=True)
    (root / "btrc.toml").write_text("[package]\nname = 'p'\n")
    got = CacheDirectory().resolve(str(sub / "main.btrc"))
    assert got == str(root / ".btrc-cache")
    assert (root / ".btrc-cache").is_dir()


def test_cache_dir_project_root_from_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    root = tmp_path / "proj2"
    root.mkdir()
    (root / "btrc.toml").write_text("[package]\nname = 'p'\n")
    monkeypatch.chdir(root)
    assert CacheDirectory().resolve() == str(root / ".btrc-cache")


def test_cache_dir_user_cache_fallback_not_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    workdir = tmp_path / "no_project_here"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    got = CacheDirectory().resolve()
    assert got.startswith(str(fake_home))  # user cache dir, expanded via $HOME
    assert got.endswith(os.path.join("btrc"))
    assert str(workdir) not in got  # never the invoking cwd
    assert not (workdir / ".btrc-cache").exists()


@pytest.mark.skipif(sys.platform == "darwin", reason="XDG only used off-macOS")
def test_cache_dir_xdg_respected(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    assert CacheDirectory().resolve() == str(tmp_path / "xdg" / "btrc")


def test_disk_cache_roundtrip_in_resolved_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "c"))
    cache = CompilationCache()
    assert cache.load_text("src-A") is None
    cache.store_text("src-A", "/* c output */")
    assert cache.load_text("src-A") == "/* c output */"
    names = os.listdir(tmp_path / "c")
    assert len(names) == 1 and names[0].endswith(".c")


def test_disk_cache_input_path_anchors_project_root(tmp_path, monkeypatch):
    monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    root = tmp_path / "proj"
    root.mkdir()
    (root / "btrc.toml").write_text("[package]\nname = 'p'\n")
    monkeypatch.chdir(tmp_path)  # cwd is NOT the project
    cache = CompilationCache()
    cache.store_text("src-B", "out", input_path=str(root / "main.btrc"))
    assert os.listdir(root / ".btrc-cache")  # cache landed in the project
    assert not (tmp_path / ".btrc-cache").exists()
    assert cache.load_text("src-B", input_path=str(root / "main.btrc")) == "out"


# --------------------------------------------------------------------------
# stdlib-AST cache invalidation
# --------------------------------------------------------------------------


def test_stdlib_ast_version_is_derived():
    assert ToolchainFingerprint().digest("frontend") == STDLIB.ast_version


def test_stale_stdlib_ast_is_not_served_after_toolchain_change(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "c"))
    src = "class CacheProbe { public int x; public CacheProbe(int x) { self.x = x; } }\n"
    first_repository = StdlibRepository(fingerprint=FixedFingerprint("a" * 16))
    first = first_repository.cached_declarations(src)
    assert first
    artifacts = os.listdir(tmp_path / "c")
    assert len(artifacts) == 1 and artifacts[0].endswith(".ast.json")

    # A toolchain change produces a different AST version -> different key:
    # the old JSON entry is orphaned, never served.
    changed_repository = StdlibRepository(fingerprint=FixedFingerprint("f" * 16))
    changed_repository.cached_declarations(src)
    assert len(os.listdir(tmp_path / "c")) == 2  # reparsed + stored under new key


# --------------------------------------------------------------------------
# stdlib archive stamping
# --------------------------------------------------------------------------


def _archive_manifest(stdlib_source: str, **overrides):
    manifest = {
        "artifacts": {
            name: hashlib.sha256(b"").hexdigest() for name in (stdlib_archive.HEADER_NAME, stdlib_archive.IMPL_NAME)
        },
        "schema": stdlib_archive.MANIFEST_SCHEMA,
        "stdlib_source": stdlib_archive._stdlib_source_hash(stdlib_source),
        "toolchain": ToolchainFingerprint().digest("full"),
        "macros": [],
        **{field: [] for field in stdlib_archive._MANIFEST_LIST_FIELDS},
    }
    manifest.update(overrides)
    return manifest


def _write_archive(tmp_path, manifest, artifacts=None):
    artifacts = artifacts or {
        stdlib_archive.HEADER_NAME: "/* header */\n",
        stdlib_archive.IMPL_NAME: "/* implementation */\n",
    }
    manifest = dict(manifest)
    manifest["artifacts"] = {
        name: hashlib.sha256(content.encode()).hexdigest() for name, content in artifacts.items() if content is not None
    }
    # Preserve the complete artifact-name schema even for a deliberately
    # missing file; its expected hash remains part of the manifest.
    for name, content_hash in _archive_manifest("")["artifacts"].items():
        manifest["artifacts"].setdefault(name, content_hash)
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(json.dumps(manifest))
    for name, content in artifacts.items():
        if content is not None:
            (tmp_path / name).write_text(content)


def test_archive_manifest_is_stamped_and_validated(tmp_path):
    source = "stdlib source"
    manifest = _archive_manifest(source)
    _write_archive(tmp_path, manifest)
    assert (
        stdlib_archive.load_manifest(
            str(tmp_path),
            source,
            _archive_publisher(),
        )["types"]
        == []
    )


@pytest.mark.skipif(os.name == "nt", reason="final-symlink archive contract is POSIX-only")
def test_archive_validation_accepts_final_symlink_manifest_and_artifacts(tmp_path):
    source = "stdlib source"
    _write_archive(tmp_path, _archive_manifest(source))
    for name in (
        stdlib_archive.MANIFEST_NAME,
        stdlib_archive.HEADER_NAME,
        stdlib_archive.IMPL_NAME,
    ):
        path = tmp_path / name
        target = tmp_path / f"{name}.real"
        path.rename(target)
        path.symlink_to(target.name)

    assert (
        stdlib_archive.load_manifest(
            str(tmp_path),
            source,
            _archive_publisher(),
        )["types"]
        == []
    )


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        (stdlib_archive.HEADER_NAME, None, "incomplete"),
        (stdlib_archive.IMPL_NAME, "", "invalid"),
    ],
)
def test_archive_manifest_rejects_missing_or_empty_artifacts(tmp_path, name, content, message):
    source = "stdlib source"
    manifest = _archive_manifest(source)
    artifacts = {
        stdlib_archive.HEADER_NAME: "/* header */\n",
        stdlib_archive.IMPL_NAME: "/* implementation */\n",
    }
    artifacts[name] = content
    _write_archive(tmp_path, manifest, artifacts)

    with pytest.raises(stdlib_archive.ArchiveVersionError, match=message):
        stdlib_archive.load_manifest(str(tmp_path), source, _archive_publisher())


def test_archive_manifest_rejects_modified_artifact(tmp_path):
    source = "stdlib source"
    _write_archive(tmp_path, _archive_manifest(source))
    with open(tmp_path / stdlib_archive.HEADER_NAME, "a") as header:
        header.write("/* tampered */\n")

    with pytest.raises(stdlib_archive.ArchiveVersionError, match="modified"):
        stdlib_archive.load_manifest(str(tmp_path), source, _archive_publisher())


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
        stdlib_archive.load_manifest(str(tmp_path), source, _archive_publisher())


def test_archive_manifest_refused_on_toolchain_mismatch(tmp_path):
    source = "stdlib source"
    stale = _archive_manifest(source, toolchain="0" * 16)
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(json.dumps(stale))
    with pytest.raises(stdlib_archive.ArchiveVersionError, match="different compiler"):
        stdlib_archive.load_manifest(str(tmp_path), source, _archive_publisher())


def test_archive_manifest_refused_on_stdlib_source_mismatch(tmp_path):
    manifest = _archive_manifest("archive stdlib")
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(json.dumps(manifest))

    with pytest.raises(stdlib_archive.ArchiveVersionError, match="different standard library"):
        stdlib_archive.load_manifest(
            str(tmp_path),
            "current or user-overridden stdlib",
            _archive_publisher(),
        )


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
        stdlib_archive.load_manifest(str(tmp_path), source, _archive_publisher())


@pytest.mark.parametrize("payload", ["not json", "{}", '{"schema":1,"types":"wrong"}'])
def test_archive_manifest_refuses_corrupt_or_unsupported_schema(tmp_path, payload):
    (tmp_path / stdlib_archive.MANIFEST_NAME).write_text(payload)

    with pytest.raises(stdlib_archive.ArchiveVersionError, match="invalid or unsupported"):
        stdlib_archive.load_manifest(
            str(tmp_path),
            "stdlib source",
            _archive_publisher(),
        )
