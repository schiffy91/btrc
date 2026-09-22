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
from src.compiler.python.frontend.sources import SourceDirectiveScanner, StdlibAstCache
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


def test_stdlib_cache_miss_is_not_an_io_failure(tmp_path) -> None:
    cache = StdlibAstCache()

    assert cache.load(str(tmp_path / "missing.ast.json"), cache.source_hash("missing")) is None


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
    cache.store_artifacts("source", "old output", link_plan="{}")

    def interrupted(_source, _target):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr(artifact_cache.os, "replace", interrupted)
    with pytest.raises(OSError, match="simulated crash"):
        cache.store_artifacts("source", "partial new output", link_plan="{}")

    assert cache.load_artifacts("source").c_source == "old output"
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
    cache.store_artifacts("source", "valid", link_plan="{}")
    cached_file = next(tmp_path.glob("*.artifacts/primary.c"))
    cached_file.write_bytes(b"\xff\xfe")

    assert cache.load_artifacts("source") is None


def test_disk_cache_oversized_entry_is_a_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    writer = CompilerCache()
    writer.store_artifacts("source", "valid", link_plan="{}")
    cached_file = next(tmp_path.glob("*.artifacts/primary.c"))
    cached_file.write_bytes(b"12345")

    assert CompilerCache(max_entry_bytes=4).load_artifacts("source") is None


def test_default_cache_preserves_large_split_debug_generation(tmp_path, monkeypatch):
    # BTRSmith's measured split/debug generation is 327 MB. Exercise the old
    # 256 MiB boundary with real files, not a mocked file-size or capacity check.
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    unit = "/* debug source map and repeated declarations */\n" * 400_000
    units = (unit,) * 15
    assert sum(len(part.encode()) for part in units) > 256 * 1024 * 1024
    cache = CompilerCache()
    cache.store_artifacts("large product", "primary", c_units=units, link_plan="{}")

    restored = CompilerCache().load_artifacts("large product")
    assert restored is not None
    assert restored.c_source == "primary" and restored.c_units == units
    assert restored.link_plan == "{}"
    # A reader with an explicitly smaller memory budget must still miss.
    assert CompilerCache(max_entry_bytes=1024).load_artifacts("large product") is None


def test_disk_cache_unavailable_directory_is_a_cache_miss():
    class UnavailableDirectory:
        def resolve(self, _input_path=None):
            raise PermissionError("read-only cache root")

    assert CompilerCache(directory=UnavailableDirectory()).load_artifacts("source") is None


@pytest.mark.parametrize(
    "damage", ["checksum", "key", "truncated", "linked", "negative", "overlap", "past-end", "non-directive", "bool"]
)
def test_directive_cache_damage_falls_back_to_current_source(tmp_path, monkeypatch, damage):
    import hashlib

    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    source = "import ./First.btrc;\nimport ./Second.btrc;\nint value() { return 0; }\n"
    expected = SourceDirectiveScanner().scan(source)
    path = str(tmp_path / "Main.btrc")
    assert SourceDirectiveScanner(CompilerCache()).scan(source, cache_input=path) == expected
    [entry] = tmp_path.glob("*.directives.json")
    payload = json.loads(entry.read_text())
    if damage == "checksum":
        payload["sha256"] = "0" * 64
    elif damage == "key":
        payload["key"] = "other"
    elif damage == "truncated":
        entry.write_text("{")
    elif damage == "linked":
        entry.rename(tmp_path / "outside.json")
        entry.symlink_to(tmp_path / "outside.json")
    else:
        payload["ranges"] = {
            "negative": [[-1, 1]],
            "overlap": [[1, 2], [2, 2]],
            "past-end": [[1, 100]],
            "non-directive": [[3, 3]],
            "bool": [[True, 1]],
        }[damage]
        payload["sha256"] = hashlib.sha256(json.dumps(payload["ranges"], separators=(",", ":")).encode()).hexdigest()
    if damage not in {"truncated", "linked"}:
        entry.write_text(json.dumps(payload))
    assert SourceDirectiveScanner(CompilerCache()).scan(source, cache_input=path) == expected


def test_directive_cache_storage_failure_and_bounds_do_not_break_scanning(tmp_path, monkeypatch):
    class UnavailableDirectory:
        def resolve(self, _input_path=None):
            raise PermissionError("read-only cache root")

    source = "import ./First.btrc;\n"
    expected = SourceDirectiveScanner().scan(source)
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    for cache in (CompilerCache(directory=UnavailableDirectory()), CompilerCache(max_entry_bytes=4)):
        assert SourceDirectiveScanner(cache).scan(source, cache_input=str(tmp_path / "Main.btrc")) == expected
    assert not list(tmp_path.glob("*.directives.json"))


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


@pytest.mark.parametrize("damage", ["content", "missing", "extra", "manifest", "symlink", "directory-link"])
def test_compiled_generation_rejects_partial_corrupt_or_linked_payloads(tmp_path, monkeypatch, damage):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    cache = CompilerCache()
    cache.store_artifacts("source", "primary", c_units=("secondary",), link_plan="plan")
    generation = next(tmp_path.glob("*.artifacts"))
    original = cache.load_artifacts("source")
    assert original is not None and original.c_units == ("secondary",)
    unit = generation / "unit-1.c"
    if damage == "content":
        unit.write_text("corrupted")
    elif damage == "missing":
        unit.unlink()
    elif damage == "extra":
        (generation / "unexpected.c").write_text("untracked")
    elif damage == "manifest":
        (generation / "manifest.json").write_text('{"schema":true}')
    elif damage == "symlink":
        unit.rename(tmp_path / "external")
        unit.symlink_to(tmp_path / "external")
    else:
        saved = tmp_path / "saved"
        generation.rename(saved)
        generation.symlink_to(saved, target_is_directory=True)
    assert cache.load_artifacts("source") is None


def test_compiled_generation_publication_failure_preserves_previous(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    cache = CompilerCache()
    cache.store_artifacts("source", "old primary", c_units=("old unit",), link_plan="old plan")
    before = cache.load_artifacts("source")
    replace = os.replace

    def fail_install(source, destination):
        if str(source).endswith(".publish.new-0"):
            raise OSError("injected installation failure")
        replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_install)
    with pytest.raises(OSError, match="injected"):
        cache.store_artifacts("source", "new primary", c_units=("new unit",), link_plan="new plan")
    assert cache.load_artifacts("source") == before
    assert not list(tmp_path.glob(".btrc-generation-*"))
    assert not list(tmp_path.glob("*.journal"))


def test_compiled_generation_bounds_total_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    writer = CompilerCache()
    writer.store_artifacts("source", "1234", c_units=("5678",), link_plan="90")
    manifest = json.loads(next(tmp_path.glob("*.artifacts/manifest.json")).read_text())
    total = sum(record["bytes"] for record in manifest["files"])
    assert CompilerCache(max_entry_bytes=total - 1).load_artifacts("source") is None
    assert CompilerCache(max_entry_bytes=total).load_artifacts("source") is not None
    CompilerCache(max_entry_bytes=total - 1).store_artifacts("other", "1234", c_units=("5678",), link_plan="90")
    assert writer.load_artifacts("other") is None


def test_compiled_generation_recovers_after_writer_process_dies(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    cache = CompilerCache()
    cache.store_artifacts("source", "old primary", c_units=("old unit",), link_plan="old plan")
    before = cache.load_artifacts("source")
    script = """
import os
from pathlib import Path
from src.compiler.python.artifacts.cache import CompilerCache
replace = os.replace

def interrupt(source, destination):
    replace(source, destination)
    if str(source).endswith(".publish.new-0"):
        os._exit(91)

os.replace = interrupt
CompilerCache().store_artifacts("source", "interrupted", c_units=("interrupted",), link_plan="interrupted")
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 91, result.stderr
    assert cache.load_artifacts("source") is None
    # Recovery must restore the last committed generation even if the next
    # writer fails too; a partially published directory is never a cache hit.
    replace = os.replace

    def fail_install(source, destination):
        if str(source).endswith(".publish.new-0"):
            raise OSError("second writer failed")
        replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_install)
    with pytest.raises(OSError, match="second writer"):
        cache.store_artifacts("source", "retry", c_units=("retry",), link_plan="retry")
    assert cache.load_artifacts("source") == before
