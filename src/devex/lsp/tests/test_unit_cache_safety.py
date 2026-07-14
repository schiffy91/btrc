"""Security and correctness contracts for the LSP's persistent unit cache."""

import json
import os
import pickle

from src.compiler.python.ast_nodes import ClassDecl, StructDecl
from src.devex.lsp import unit_cache, units
from src.devex.lsp.units import _UNIT_CACHE_VERSION, parse_unit
from src.devex.lsp.workspace import Workspace


def _source() -> str:
    return "struct CacheOpaque;\nclass CacheProbe { public int value; public CacheProbe() {} }\n"


def test_json_unit_cache_roundtrip_is_deterministic(tmp_path):
    unit = parse_unit(str(tmp_path / "probe.btrc"), _source())
    relocated = parse_unit(str(tmp_path / "elsewhere" / "probe.btrc"), _source())
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"

    unit_cache.store_unit(str(first), unit)
    unit_cache.store_unit(str(second), relocated)

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().startswith(b'{"content_hash":')
    loaded = unit_cache.load_unit(str(first), unit.path, unit.content_hash)
    assert loaded is not None
    assert loaded.decls == unit.decls
    forward = next(decl for decl in loaded.decls if isinstance(decl, StructDecl))
    class_decl = next(decl for decl in loaded.decls if isinstance(decl, ClassDecl))
    assert forward.is_forward is True
    assert class_decl.members[-1].is_constructor is True
    assert loaded.defined_names == unit.defined_names
    assert loaded.source == "" and loaded.tokens == []


def test_unit_cache_version_covers_frontend_schema(monkeypatch):
    monkeypatch.setattr(units, "toolchain_hash", lambda _scope: "frontend-a")
    first = units._compute_unit_cache_version()
    monkeypatch.setattr(units, "toolchain_hash", lambda _scope: "frontend-b")
    second = units._compute_unit_cache_version()

    assert first != second


def test_cache_rebinds_source_path_instead_of_reusing_stored_path(tmp_path):
    source = _source()
    original = parse_unit(str(tmp_path / "original.btrc"), source)
    cached = tmp_path / "unit.json"
    unit_cache.store_unit(str(cached), original)

    relocated_path = str(tmp_path / "relocated.btrc")
    loaded = unit_cache.load_unit(str(cached), relocated_path, original.content_hash)

    assert loaded is not None
    assert loaded.path == os.path.abspath(relocated_path)
    assert all(decl.source_file == loaded.path for decl in loaded.decls)


def test_pickle_payload_at_current_cache_path_is_never_executed(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    source_file = tmp_path / "probe.btrc"
    source_file.write_text(_source())
    marker = tmp_path / "pickle-executed"

    class Exploit:
        def __reduce__(self):
            return os.mkdir, (str(marker),)

    path = unit_cache.cache_path(str(cache_dir), _UNIT_CACHE_VERSION, _source())
    with open(path, "wb") as cache_file:
        pickle.dump(Exploit(), cache_file)
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache_dir))

    loaded = Workspace()._load_stdlib_unit(str(source_file))

    assert loaded is not None
    assert not marker.exists()
    with open(path, encoding="utf-8") as cache_file:
        assert json.load(cache_file)["schema"] == 1


def test_unknown_schema_and_ast_node_are_rejected(tmp_path):
    source_hash = parse_unit("/probe.btrc", _source()).content_hash
    path = tmp_path / "unit.json"
    base = {
        "content_hash": source_hash,
        "decls": [],
        "defined_names": [],
        "schema": 999,
    }
    path.write_text(json.dumps(base))
    assert unit_cache.load_unit(str(path), "/probe.btrc", source_hash) is None

    base["schema"] = 1
    base["decls"] = [{"fields": {}, "type": "NotAnAstClass"}]
    path.write_text(json.dumps(base))
    assert unit_cache.load_unit(str(path), "/probe.btrc", source_hash) is None


def test_parse_failures_are_not_persisted_as_successful_units(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    source_file = tmp_path / "broken.btrc"
    source_file.write_text("class Broken {\n")
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache_dir))

    unit = Workspace()._load_stdlib_unit(str(source_file))

    assert unit is not None and unit.error is not None
    assert not list(cache_dir.glob("lspunit-*.json"))


def test_disk_unit_cache_detects_same_size_same_mtime_rewrite(tmp_path):
    path = tmp_path / "changing.btrc"
    path.write_text("class A {}\n")
    original_stat = path.stat()
    workspace = Workspace()
    first = workspace.get_file_unit(str(path))

    path.write_text("class B {}\n")
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    second = workspace.get_file_unit(str(path))

    assert first is not None and second is not None and second is not first
    assert first.decls[0].name == "A"
    assert second.decls[0].name == "B"
