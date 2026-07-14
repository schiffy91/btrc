"""Security and crash-consistency contracts for compiler caches."""

import json

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
