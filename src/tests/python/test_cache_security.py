"""Security and crash-consistency contracts for compiler caches."""

import ast
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

import src.compiler.python.artifacts.cache as artifact_cache
import src.compiler.python.syntax.ast.codec as ast_codec
from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.frontend.sources import StdlibAstCache
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.codec import AstJsonCodec


def _declarations(source: str):
    return Parser(Lexer(source).tokenize()).parse().declarations


def _schema_marker_declarations():
    return _declarations("struct Opaque; class CacheBox { public CacheBox() {} public int value() { return 1; } }\n")


def test_cache_file_behavior_has_one_explicit_owner() -> None:
    module = ast.parse(Path(artifact_cache.__file__).read_text())
    loose_behavior = [node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    assert loose_behavior == []


def test_ast_codec_behavior_has_one_explicit_owner() -> None:
    module = ast.parse(Path(ast_codec.__file__).read_text())
    loose_behavior = [node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    assert loose_behavior == []


def test_ast_codec_roundtrip_preserves_schema_markers():
    codec = AstJsonCodec()
    declarations = _schema_marker_declarations()
    encoded = [codec.encode(declaration) for declaration in declarations]
    decoded = [codec.decode(declaration) for declaration in encoded]

    assert encoded[0]["fields"]["is_forward"] is True
    assert encoded[1]["fields"]["members"][0]["fields"]["is_constructor"] is True
    assert decoded == declarations
    assert decoded[0].is_forward is True
    assert decoded[1].members[0].is_constructor is True


def test_stdlib_cache_owns_its_codec() -> None:
    codec = AstJsonCodec({})

    cache = StdlibAstCache(codec=codec)

    assert cache.codec is codec


def test_stdlib_cache_rejects_nodes_missing_current_marker_fields(tmp_path):
    cache = StdlibAstCache()
    source = "schema markers"
    content_hash = cache.source_hash(source)
    path = cache.path(str(tmp_path), "frontend-v1", source)
    cache.store(
        path,
        content_hash,
        _schema_marker_declarations(),
    )
    with open(path, encoding="utf-8") as cache_file:
        current = json.load(cache_file)

    stale_struct = json.loads(json.dumps(current))
    stale_struct["declarations"][0]["fields"].pop("is_forward")
    Path(path).write_text(json.dumps(stale_struct), encoding="utf-8")
    assert cache.load(path, content_hash) is None

    stale_method = json.loads(json.dumps(current))
    stale_method["declarations"][1]["fields"]["members"][0]["fields"].pop("is_constructor")
    Path(path).write_text(json.dumps(stale_method), encoding="utf-8")
    assert cache.load(path, content_hash) is None


def test_stdlib_json_cache_rejects_schema_hash_and_node_tampering(tmp_path):
    cache = StdlibAstCache()
    source = "class Cached { public int value; }\n"
    content_hash = cache.source_hash(source)
    path = cache.path(str(tmp_path), "frontend-v1", source)
    cache.store(
        path,
        content_hash,
        _declarations(source),
    )
    with open(path, encoding="utf-8") as cache_file:
        valid = json.load(cache_file)

    valid["schema"] += 1
    Path(path).write_text(json.dumps(valid), encoding="utf-8")
    assert cache.load(path, content_hash) is None

    valid["schema"] = StdlibAstCache.SCHEMA
    valid["content_hash"] = "0" * 64
    Path(path).write_text(json.dumps(valid), encoding="utf-8")
    assert cache.load(path, content_hash) is None

    valid["content_hash"] = content_hash
    valid["declarations"] = [{"fields": {}, "type": "ArbitraryPythonClass"}]
    Path(path).write_text(json.dumps(valid), encoding="utf-8")
    assert cache.load(path, content_hash) is None


def test_stdlib_cache_key_covers_schema_frontend_and_source(tmp_path):
    cache = StdlibAstCache()
    one = cache.path(str(tmp_path), "frontend-a", "class A {}\n")
    assert one != cache.path(str(tmp_path), "frontend-b", "class A {}\n")
    assert one != cache.path(str(tmp_path), "frontend-a", "class B {}\n")
    newer_schema = StdlibAstCache(schema_version=StdlibAstCache.SCHEMA + 1)
    assert one != newer_schema.path(
        str(tmp_path),
        "frontend-a",
        "class A {}\n",
    )


def test_stdlib_cache_pruning_state_is_instance_owned(tmp_path):
    legacy = tmp_path / "stdlib-legacy.ast"
    first = StdlibAstCache()
    second = StdlibAstCache()

    legacy.write_bytes(b"unsafe pickle")
    first.prune(str(tmp_path))
    assert not legacy.exists()

    legacy.write_bytes(b"unsafe pickle restored after first cache scan")
    second.prune(str(tmp_path))
    assert not legacy.exists()


def test_stdlib_cache_retries_pruning_after_unavailable_directory(tmp_path):
    cache = StdlibAstCache()
    cache_dir = tmp_path / "created-later"

    cache.prune(str(cache_dir))

    cache_dir.mkdir()
    legacy = cache_dir / "stdlib-legacy.ast"
    legacy.write_bytes(b"unsafe pickle")
    cache.prune(str(cache_dir))
    assert not legacy.exists()


def test_disk_cache_atomic_failure_preserves_previous_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    cache = CompilerCache()
    cache.store_text("source", "old output")

    def interrupted(_source, _target):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(artifact_cache.os, "replace", interrupted)
    with pytest.raises(OSError, match="simulated crash"):
        cache.store_text("source", "partial new output")

    assert cache.load_text("source") == "old output"
    assert not list(tmp_path.glob(".btrc-cache-*"))


def test_atomic_text_writes_disable_platform_newline_translation(tmp_path, monkeypatch):
    real_fdopen = artifact_cache.os.fdopen
    observed = {}

    def recording_fdopen(descriptor, *args, **kwargs):
        observed["newline"] = kwargs.get("newline")
        return real_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(artifact_cache.os, "fdopen", recording_fdopen)
    target = tmp_path / "deterministic.txt"
    artifact_cache.AtomicFileStore().write_text(str(target), "left\nright\n")

    assert observed["newline"] == "\n"
    assert target.read_bytes() == b"left\nright\n"


def test_atomic_text_fsyncs_parent_after_replacement(tmp_path, monkeypatch):
    target = tmp_path / "durable.txt"
    events = []
    real_replace = artifact_cache.os.replace

    def recording_replace(source, destination):
        events.append(("replace", destination))
        real_replace(source, destination)

    monkeypatch.setattr(artifact_cache.os, "replace", recording_replace)
    file_store = artifact_cache.AtomicFileStore()
    monkeypatch.setattr(
        file_store,
        "sync_parent",
        lambda path: events.append(("fsync-parent", path)),
    )

    file_store.write_text(str(target), "durable")

    assert events == [("replace", str(target)), ("fsync-parent", str(target))]


def test_parent_directory_fsync_uses_bounded_best_effort_syscalls(tmp_path, monkeypatch):
    target = tmp_path / "cache.json"
    events = []

    monkeypatch.setattr(
        artifact_cache.os,
        "open",
        lambda path, flags: events.append(("open", path, flags)) or 73,
    )
    monkeypatch.setattr(artifact_cache.os, "fsync", lambda descriptor: events.append(("fsync", descriptor)))
    monkeypatch.setattr(artifact_cache.os, "close", lambda descriptor: events.append(("close", descriptor)))

    artifact_cache.AtomicFileStore().sync_parent(str(target))

    assert events[0][0:2] == ("open", str(tmp_path))
    assert events[1:] == [("fsync", 73), ("close", 73)]


def test_parent_directory_fsync_tolerates_unsupported_platform(tmp_path, monkeypatch):
    def unsupported(_path, _flags):
        raise OSError("directory handles are unavailable")

    monkeypatch.setattr(artifact_cache.os, "open", unsupported)

    artifact_cache.AtomicFileStore().sync_parent(str(tmp_path / "cache.json"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")
def test_atomic_text_can_publish_a_public_artifact_mode(tmp_path):
    target = tmp_path / "artifact.txt"

    artifact_cache.AtomicFileStore().write_text(
        str(target),
        "artifact\n",
        file_mode=0o644,
    )

    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")
def test_atomic_text_explicit_mode_replaces_unsafe_existing_mode(tmp_path):
    target = tmp_path / "artifact.txt"
    target.write_text("old\n")
    target.chmod(0o777)

    artifact_cache.AtomicFileStore().write_text(
        str(target),
        "replacement\n",
        file_mode=0o644,
    )

    assert target.read_text() == "replacement\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_disk_cache_corrupt_utf8_is_a_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    cache = CompilerCache()
    cache.store_text("source", "valid")
    cached_file = next(tmp_path.glob("*.c"))
    cached_file.write_bytes(b"\xff\xfe")

    assert cache.load_text("source") is None


def test_disk_cache_oversized_entry_is_a_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    writer = CompilerCache()
    writer.store_text("source", "valid")
    cached_file = next(tmp_path.glob("*.c"))
    cached_file.write_bytes(b"12345")

    assert CompilerCache(max_entry_bytes=4).load_text("source") is None


def test_disk_cache_unavailable_directory_is_a_cache_miss():
    class UnavailableDirectory:
        def resolve(self, _input_path=None):
            raise PermissionError("read-only cache root")

    assert CompilerCache(directory=UnavailableDirectory()).load_text("source") is None


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="platform has no no-follow open flag")
def test_cache_reads_do_not_follow_final_symlinks(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"valid": true}')
    link = tmp_path / "cache.json"
    link.symlink_to(target.name)

    assert artifact_cache.AtomicFileStore().read_json(str(link)) is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are unavailable")
def test_cache_and_archive_validation_reject_fifos_without_blocking(tmp_path):
    fifo = tmp_path / "substituted-cache"
    os.mkfifo(fifo)
    repo_root = Path(__file__).resolve().parents[3]
    script = """
import sys
from src.compiler.python.artifacts.cache import AtomicFileStore
from src.compiler.python.artifacts.publication import ArtifactPublisher
from src.compiler.python.artifacts.stdlib import StdlibArchivePublisher
from src.compiler.python.artifacts.stdlib import StdlibArchiveManifest

path = sys.argv[1]
assert AtomicFileStore().read_json(path) is None
manifest = StdlibArchiveManifest(StdlibArchivePublisher(ArtifactPublisher()))
assert manifest._artifact_hash(path) is None
"""

    subprocess.run(
        [sys.executable, "-c", script, str(fifo)],
        check=True,
        cwd=repo_root,
        timeout=5,
    )
