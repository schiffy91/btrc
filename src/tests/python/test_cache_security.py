"""Security and crash-consistency contracts for compiler caches."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python import ast_codec, cache_io, disk_cache, stdlib_ast_cache
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _declarations(source: str):
    return Parser(Lexer(source).tokenize()).parse().declarations


def _schema_marker_declarations():
    return _declarations("struct Opaque; class CacheBox { public CacheBox() {} public int value() { return 1; } }\n")


def test_ast_codec_roundtrip_preserves_schema_markers():
    declarations = _schema_marker_declarations()
    encoded = [ast_codec.encode_ast(declaration) for declaration in declarations]
    decoded = [ast_codec.decode_ast(declaration) for declaration in encoded]

    assert encoded[0]["fields"]["is_forward"] is True
    assert encoded[1]["fields"]["members"][0]["fields"]["is_constructor"] is True
    assert decoded == declarations
    assert decoded[0].is_forward is True
    assert decoded[1].members[0].is_constructor is True


def test_stdlib_cache_rejects_nodes_missing_current_marker_fields(tmp_path):
    source = "schema markers"
    content_hash = stdlib_ast_cache.source_hash(source)
    path = stdlib_ast_cache.cache_path(str(tmp_path), "frontend-v1", source)
    stdlib_ast_cache.store_declarations(
        path,
        content_hash,
        _schema_marker_declarations(),
    )
    with open(path, encoding="utf-8") as cache_file:
        current = json.load(cache_file)

    stale_struct = json.loads(json.dumps(current))
    stale_struct["declarations"][0]["fields"].pop("is_forward")
    cache_io.atomic_write_json(path, stale_struct)
    assert stdlib_ast_cache.load_declarations(path, content_hash) is None

    stale_method = json.loads(json.dumps(current))
    stale_method["declarations"][1]["fields"]["members"][0]["fields"].pop("is_constructor")
    cache_io.atomic_write_json(path, stale_method)
    assert stdlib_ast_cache.load_declarations(path, content_hash) is None


def test_stdlib_json_cache_rejects_schema_hash_and_node_tampering(tmp_path):
    source = "class Cached { public int value; }\n"
    content_hash = stdlib_ast_cache.source_hash(source)
    path = stdlib_ast_cache.cache_path(str(tmp_path), "frontend-v1", source)
    stdlib_ast_cache.store_declarations(
        path,
        content_hash,
        _declarations(source),
    )
    with open(path, encoding="utf-8") as cache_file:
        valid = json.load(cache_file)

    valid["schema"] += 1
    cache_io.atomic_write_json(path, valid)
    assert stdlib_ast_cache.load_declarations(path, content_hash) is None

    valid["schema"] = stdlib_ast_cache.SCHEMA_VERSION
    valid["content_hash"] = "0" * 64
    cache_io.atomic_write_json(path, valid)
    assert stdlib_ast_cache.load_declarations(path, content_hash) is None

    valid["content_hash"] = content_hash
    valid["declarations"] = [{"fields": {}, "type": "ArbitraryPythonClass"}]
    cache_io.atomic_write_json(path, valid)
    assert stdlib_ast_cache.load_declarations(path, content_hash) is None


def test_stdlib_cache_key_covers_schema_frontend_and_source(tmp_path, monkeypatch):
    one = stdlib_ast_cache.cache_path(str(tmp_path), "frontend-a", "class A {}\n")
    assert one != stdlib_ast_cache.cache_path(str(tmp_path), "frontend-b", "class A {}\n")
    assert one != stdlib_ast_cache.cache_path(str(tmp_path), "frontend-a", "class B {}\n")
    monkeypatch.setattr(
        stdlib_ast_cache,
        "SCHEMA_VERSION",
        stdlib_ast_cache.SCHEMA_VERSION + 1,
    )
    assert one != stdlib_ast_cache.cache_path(str(tmp_path), "frontend-a", "class A {}\n")


def test_disk_cache_atomic_failure_preserves_previous_entry(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    disk_cache.store("source", "old output")

    def interrupted(_source, _target):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(cache_io.os, "replace", interrupted)
    with pytest.raises(OSError, match="simulated crash"):
        disk_cache.store("source", "partial new output")

    assert disk_cache.get_cached("source") == "old output"
    assert not list(tmp_path.glob(".btrc-cache-*"))


def test_atomic_text_writes_disable_platform_newline_translation(tmp_path, monkeypatch):
    real_fdopen = cache_io.os.fdopen
    observed = {}

    def recording_fdopen(descriptor, *args, **kwargs):
        observed["newline"] = kwargs.get("newline")
        return real_fdopen(descriptor, *args, **kwargs)

    monkeypatch.setattr(cache_io.os, "fdopen", recording_fdopen)
    target = tmp_path / "deterministic.txt"
    cache_io.atomic_write_text(str(target), "left\nright\n")

    assert observed["newline"] == "\n"
    assert target.read_bytes() == b"left\nright\n"


def test_atomic_text_fsyncs_parent_after_replacement(tmp_path, monkeypatch):
    target = tmp_path / "durable.txt"
    events = []
    real_replace = cache_io.os.replace

    def recording_replace(source, destination):
        events.append(("replace", destination))
        real_replace(source, destination)

    monkeypatch.setattr(cache_io.os, "replace", recording_replace)
    monkeypatch.setattr(
        cache_io,
        "fsync_parent_directory",
        lambda path: events.append(("fsync-parent", path)),
    )

    cache_io.atomic_write_text(str(target), "durable")

    assert events == [("replace", str(target)), ("fsync-parent", str(target))]


def test_parent_directory_fsync_uses_bounded_best_effort_syscalls(tmp_path, monkeypatch):
    target = tmp_path / "cache.json"
    events = []

    monkeypatch.setattr(
        cache_io.os,
        "open",
        lambda path, flags: events.append(("open", path, flags)) or 73,
    )
    monkeypatch.setattr(cache_io.os, "fsync", lambda descriptor: events.append(("fsync", descriptor)))
    monkeypatch.setattr(cache_io.os, "close", lambda descriptor: events.append(("close", descriptor)))

    cache_io.fsync_parent_directory(str(target))

    assert events[0][0:2] == ("open", str(tmp_path))
    assert events[1:] == [("fsync", 73), ("close", 73)]


def test_parent_directory_fsync_tolerates_unsupported_platform(tmp_path, monkeypatch):
    def unsupported(_path, _flags):
        raise OSError("directory handles are unavailable")

    monkeypatch.setattr(cache_io.os, "open", unsupported)

    cache_io.fsync_parent_directory(str(tmp_path / "cache.json"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")
def test_atomic_text_can_publish_a_public_artifact_mode(tmp_path):
    target = tmp_path / "artifact.txt"

    cache_io.atomic_write_text(str(target), "artifact\n", file_mode=0o644)

    assert stat.S_IMODE(target.stat().st_mode) == 0o644


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission contract")
def test_atomic_text_explicit_mode_replaces_unsafe_existing_mode(tmp_path):
    target = tmp_path / "artifact.txt"
    target.write_text("old\n")
    target.chmod(0o777)

    cache_io.atomic_write_text(str(target), "replacement\n", file_mode=0o644)

    assert target.read_text() == "replacement\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_disk_cache_corrupt_utf8_is_a_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    disk_cache.store("source", "valid")
    cached_file = next(tmp_path.glob("*.c"))
    cached_file.write_bytes(b"\xff\xfe")

    assert disk_cache.get_cached("source") is None


def test_disk_cache_oversized_entry_is_a_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    disk_cache.store("source", "valid")
    cached_file = next(tmp_path.glob("*.c"))
    cached_file.write_bytes(b"12345")
    monkeypatch.setattr(disk_cache, "MAX_C_CACHE_BYTES", 4)

    assert disk_cache.get_cached("source") is None


def test_disk_cache_unavailable_directory_is_a_cache_miss(monkeypatch):
    def unavailable(_input_path=None):
        raise PermissionError("read-only cache root")

    monkeypatch.setattr(disk_cache, "resolve_cache_dir", unavailable)
    assert disk_cache.get_cached("source") is None


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="platform has no no-follow open flag")
def test_cache_reads_do_not_follow_final_symlinks(tmp_path):
    target = tmp_path / "target.json"
    target.write_text('{"valid": true}')
    link = tmp_path / "cache.json"
    link.symlink_to(target.name)

    assert cache_io.load_json(str(link)) is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes are unavailable")
def test_cache_and_archive_validation_reject_fifos_without_blocking(tmp_path):
    fifo = tmp_path / "substituted-cache"
    os.mkfifo(fifo)
    repo_root = Path(__file__).resolve().parents[3]
    script = """
import sys
from src.compiler.python.cache_io import load_json
from src.compiler.python.stdlib_archive_validation import _artifact_hash

path = sys.argv[1]
assert load_json(path) is None
assert _artifact_hash(path) is None
"""

    subprocess.run(
        [sys.executable, "-c", script, str(fifo)],
        check=True,
        cwd=repo_root,
        timeout=5,
    )
