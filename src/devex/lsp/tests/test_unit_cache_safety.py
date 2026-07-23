"""Security and correctness contracts for the LSP's persistent unit cache."""

import ast
import json
import os
import pickle
from pathlib import Path

import pytest

from src.compiler.python.ast_codec import AstJsonCodec
from src.compiler.python.ast_nodes import ClassDecl, StructDecl
from src.compiler.python.cache_io import AtomicFileStore
from src.compiler.python.frontend.source_io import SourceFileReader, SourceReadError
from src.devex.lsp import unit_cache, units
from src.devex.lsp import workspace as workspace_module
from src.devex.lsp.unit_cache import FileUnitCacheCodec, UnitCache
from src.devex.lsp.units import FileUnit
from src.devex.lsp.workspace import Workspace

AST_CODEC = AstJsonCodec()


def _source() -> str:
    return "import std.vector;\nstruct CacheOpaque;\nclass CacheProbe { public int value; public CacheProbe() {} }\n"


def test_json_unit_cache_roundtrip_is_deterministic(tmp_path):
    unit = FileUnit.parse(str(tmp_path / "probe.btrc"), _source())
    relocated = FileUnit.parse(str(tmp_path / "elsewhere" / "probe.btrc"), _source())
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_cache = UnitCache(str(first_dir))
    second_cache = UnitCache(str(second_dir))

    first = first_cache.store(_source(), unit)
    second = second_cache.store(_source(), relocated)

    assert first is not None and second is not None
    first = Path(first)
    second = Path(second)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().startswith(b'{"content_hash":')
    loaded = first_cache.load(unit.path, _source())
    assert loaded is not None
    assert loaded.decls == unit.decls
    forward = next(decl for decl in loaded.decls if isinstance(decl, StructDecl))
    class_decl = next(decl for decl in loaded.decls if isinstance(decl, ClassDecl))
    assert forward.is_forward is True
    assert class_decl.members[-1].is_constructor is True
    assert loaded.dependencies == unit.dependencies
    assert loaded.defined_names == unit.defined_names
    assert loaded.source == "" and loaded.tokens == []


def test_unit_cache_version_covers_frontend_schema():
    class FixedFingerprint:
        def __init__(self, value):
            self.value = value

        def digest(self, _scope):
            return self.value

    first = units.FileUnitCacheSchema(FixedFingerprint("frontend-a")).current_version()
    second = units.FileUnitCacheSchema(FixedFingerprint("frontend-b")).current_version()

    assert first != second


def test_cache_rebinds_source_path_instead_of_reusing_stored_path(tmp_path):
    source = _source()
    original = FileUnit.parse(str(tmp_path / "original.btrc"), source)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache = UnitCache(str(cache_dir))
    assert cache.store(source, original) is not None

    relocated_path = str(tmp_path / "relocated.btrc")
    loaded = cache.load(relocated_path, source)

    assert loaded is not None
    assert loaded.path == os.path.abspath(relocated_path)
    assert all(decl.source_file == loaded.path for decl in loaded.decls)


def test_pickle_payload_at_current_cache_path_is_never_executed(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    source_file = tmp_path / "probe.btrc"
    source_file.write_text(_source())
    marker = tmp_path / "pickle-executed"

    class Exploit:
        def __reduce__(self):
            return os.mkdir, (str(marker),)

    cache = UnitCache(str(cache_dir))
    path = cache.entry_path(_source())
    assert path is not None
    with open(path, "wb") as cache_file:
        pickle.dump(Exploit(), cache_file)

    loaded = Workspace(unit_cache=cache)._load_stdlib_unit(str(source_file))

    assert loaded is not None
    assert not marker.exists()
    with open(path, encoding="utf-8") as cache_file:
        assert json.load(cache_file)["schema"] == FileUnitCacheCodec.SCHEMA_VERSION


def test_unknown_schema_and_ast_node_are_rejected(tmp_path):
    unit = FileUnit.parse("/probe.btrc", _source())
    cache = UnitCache(str(tmp_path))
    path = cache.entry_path(_source())
    assert path is not None
    base = {
        "content_hash": unit.content_hash,
        "decls": [],
        "dependencies": [],
        "defined_names": [],
        "schema": 999,
    }
    Path(path).write_text(json.dumps(base))
    assert cache.load("/probe.btrc", _source()) is None

    base["schema"] = FileUnitCacheCodec.SCHEMA_VERSION
    base["decls"] = [{"fields": {}, "type": "NotAnAstClass"}]
    Path(path).write_text(json.dumps(base))
    assert cache.load("/probe.btrc", _source()) is None


@pytest.mark.parametrize(
    "mutate",
    (
        lambda dependency: dependency.update(kind="not-a-dependency-kind"),
        lambda dependency: dependency.update(spec=AST_CODEC.encode(ClassDecl(name="NotAnImportSpec"))),
    ),
    ids=("invalid-kind", "invalid-import-spec-ast"),
)
def test_corrupt_cached_dependencies_are_rejected(tmp_path, mutate):
    unit = FileUnit.parse(str(tmp_path / "probe.btrc"), _source())
    cache = UnitCache(str(tmp_path))
    path = cache.store(_source(), unit)
    assert path is not None
    path = Path(path)
    payload = json.loads(path.read_text())
    mutate(payload["dependencies"][0])
    path.write_text(json.dumps(payload))

    assert cache.load(unit.path, _source()) is None


def test_parse_failures_are_not_persisted_as_successful_units(tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    source_file = tmp_path / "broken.btrc"
    source_file.write_text("class Broken {\n")

    unit = Workspace(unit_cache=UnitCache(str(cache_dir)))._load_stdlib_unit(str(source_file))

    assert unit is not None and unit.error is not None
    assert not list(cache_dir.glob("lspunit-*.json"))


def test_unavailable_cache_does_not_disable_stdlib_analysis(tmp_path):
    source_file = tmp_path / "stdlib.btrc"
    source_file.write_text(_source())

    class UnavailableDirectory:
        def resolve(self, _input_path=None):
            raise PermissionError("read-only cache root")

    unavailable_cache = UnitCache.from_environment(UnavailableDirectory())
    unit = Workspace(unit_cache=unavailable_cache)._load_stdlib_unit(str(source_file))

    assert unit is not None and unit.error is None
    assert unit.decls


def test_prune_retries_after_a_transient_directory_scan_failure(
    tmp_path,
    monkeypatch,
):
    cache = UnitCache(str(tmp_path))
    original_listdir = unit_cache.os.listdir
    calls = 0

    def flaky_listdir(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("transient cache scan failure")
        return original_listdir(path)

    monkeypatch.setattr(unit_cache.os, "listdir", flaky_listdir)

    assert cache.prune() is False
    assert cache.prune() is True
    assert cache.prune() is True
    assert calls == 2


def test_cache_and_workspace_behavior_is_instance_owned() -> None:
    root = Path(workspace_module.__file__).parent
    for filename in ("unit_cache.py", "workspace.py"):
        module = ast.parse((root / filename).read_text())
        loose = [node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        assert loose == []

    assert not hasattr(unit_cache, "_pruned_dirs")


def test_unit_cache_uses_its_owned_codec_and_file_store(tmp_path, monkeypatch):
    codec = FileUnitCacheCodec()
    store = AtomicFileStore()
    cache = UnitCache(str(tmp_path), codec=codec, file_store=store)
    unit = FileUnit.parse(str(tmp_path / "probe.btrc"), _source())
    writes = []
    write_json = store.write_json

    def track_write(path, payload, *, file_mode=None):
        writes.append((path, payload))
        write_json(path, payload, file_mode=file_mode)

    monkeypatch.setattr(store, "write_json", track_write)

    assert cache.store(_source(), unit) is not None
    assert writes
    assert writes[0][1] == codec.encode(unit)
    assert cache.load(unit.path, _source()) is not None


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


def test_live_document_and_overlay_sources_share_the_compiler_size_limit(tmp_path):
    workspace = Workspace(source_reader=SourceFileReader(max_bytes=4))

    with pytest.raises(ValueError, match="4-byte source limit"):
        workspace.parse_active(str(tmp_path / "active.btrc"), "12345")

    workspace.overlay_provider = lambda _path: "12345"
    assert workspace.get_file_unit(str(tmp_path / "import.btrc")) is None


def test_disk_units_delegate_to_the_bounded_source_reader(tmp_path):
    source_file = tmp_path / "import.btrc"
    source_file.write_text("class Imported {}\n")

    class RejectingSourceReader(SourceFileReader):
        def read(self, _path: str) -> str:
            raise SourceReadError("source exceeds limit")

    assert Workspace(source_reader=RejectingSourceReader()).get_file_unit(str(source_file)) is None
