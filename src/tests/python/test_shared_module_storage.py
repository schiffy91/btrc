"""Both frontends consume the same on-disk module entries and leases."""

import hashlib
import json
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from src.compiler.python.artifacts.cache import AtomicFileStore, CacheDirectory, CompilerCache, ToolchainFingerprint
from src.compiler.python.artifacts.publication import PublicationLock
from src.tests.python.test_compiler_build_identity import (
    _driver,
    _fields,
    _tree,
    _write_receipt,
)
from src.tests.python.test_compiler_build_identity import (
    identity_driver as identity_driver,
)
from src.tests.python.test_module_record_interchange import _record


@pytest.fixture
def store(tmp_path, monkeypatch):
    inventory = _tree(tmp_path)
    binary = tmp_path / "compiler"
    binary.write_bytes(b"compiler")
    _write_receipt(binary, _fields(tmp_path, inventory, binary))
    directory = tmp_path / "cache"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(directory))
    cache = CompilerCache(fingerprint=ToolchainFingerprint(inventory))
    record = _record()
    data = {
        "mode": "get",
        "module": "module é:数据",
        "executable": str(binary),
        "data_root": str(tmp_path / "src"),
        "record": record.to_text(),
        "text": record.text,
    }
    key = cache.module_key_for(data["module"])
    return cache, data, directory / "modules-v1" / key


def _load(frontend, request, tmp_path, cache, data):
    if frontend == "reference":
        return cache.load_module_unit(data["module"])
    result = _driver(request.getfixturevalue("identity_driver"), tmp_path, {**data, "mode": "get"})
    return (result["record"], result["text"]) if result["hit"] else None


@pytest.mark.parametrize("producer", ["reference", "selfhost"])
def test_paired_store_interchange_has_identical_bytes(store, tmp_path, identity_driver, producer):
    cache, data, entry = store
    cache.store_module_unit(data["module"], data["record"], data["text"])
    expected = {name: (entry / name).read_bytes() for name in ("record.txt", "unit.c")}
    if producer == "selfhost":
        shutil.rmtree(entry)
        result = _driver(identity_driver, tmp_path, {**data, "mode": "put"})
        assert result["hit"]
        assert cache.load_module_unit(data["module"]) == (data["record"], data["text"])
    else:
        result = _driver(identity_driver, tmp_path, data)
        assert result["hit"] and result["record"] == data["record"] and result["text"] == data["text"]
    assert {name: (entry / name).read_bytes() for name in expected} == expected
    assert entry.stat().st_mode & 0o777 == 0o700
    assert all((entry / name).stat().st_mode & 0o777 == 0o600 for name in expected)


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
@pytest.mark.parametrize(
    "damage",
    [
        "record",
        "text",
        "missing",
        "key",
        "header",
        "symlink",
        "file-mode",
        "root-mode",
        "lock-mode",
        "lock-symlink",
        "entry-symlink",
    ],
)
def test_shared_store_rejects_corruption(store, tmp_path, request, frontend, damage):
    cache, data, entry = store
    cache.store_module_unit(data["module"], data["record"], data["text"])
    record, text = entry / "record.txt", entry / "unit.c"
    if damage in {"record", "text"}:
        path = record if damage == "record" else text
        path.write_bytes(path.read_bytes() + b"corrupt")
    elif damage == "missing":
        text.unlink()
    elif damage == "key":
        record.write_text(record.read_text().replace(entry.name, "0" * 64, 1))
    elif damage == "header":
        record.write_text(record.read_text().replace("entry-v1", "entry-v0", 1))
    elif damage == "symlink":
        actual = tmp_path / "external.c"
        text.rename(actual)
        text.symlink_to(actual)
    elif damage == "file-mode":
        text.chmod(0o644)
    elif damage == "root-mode":
        entry.parent.chmod(0o755)
    elif damage == "lock-mode":
        (entry / ".btrc-publications.lock").chmod(0o644)
    elif damage == "lock-symlink":
        lock = entry / ".btrc-publications.lock"
        actual = tmp_path / "external.lock"
        lock.rename(actual)
        lock.symlink_to(actual)
    else:
        actual = tmp_path / "external-entry"
        entry.rename(actual)
        entry.symlink_to(actual, target_is_directory=True)
    assert _load(frontend, request, tmp_path, cache, data) is None


@pytest.mark.parametrize("frontend", ["reference", "selfhost"])
def test_interrupted_replacement_is_a_miss(store, tmp_path, request, frontend):
    cache, data, _ = store
    cache.store_module_unit(data["module"], data["record"], data["text"])

    class FailReceipt(AtomicFileStore):
        def write_text(self, path, content, **kwargs):
            if Path(path).name == "record.txt":
                raise OSError("simulated publication failure")
            super().write_text(path, content, **kwargs)

    interrupted = CompilerCache(fingerprint=cache._fingerprint, file_store=FailReceipt())
    interrupted.store_module_unit(data["module"], data["record"], "changed C")
    assert _load(frontend, request, tmp_path, cache, data) is None


@pytest.mark.parametrize("configured", ["", "relative-cache", "absolute"])
@pytest.mark.parametrize("package", [False, True])
def test_paired_default_directory_is_under_build(tmp_path, monkeypatch, identity_driver, configured, package):
    root = tmp_path / "project"
    source = root / "src/nested/Main.btrc"
    source.parent.mkdir(parents=True)
    source.write_text("int main() { return 0; }")
    if package:
        (root / "btrc.toml").write_text("")
    value = str(tmp_path / "configured") if configured == "absolute" else configured
    monkeypatch.chdir(tmp_path)
    if value:
        monkeypatch.setenv("BTRC_CACHE_DIR", value)
    else:
        monkeypatch.delenv("BTRC_CACHE_DIR", raising=False)
    reference = Path(CacheDirectory().resolve_modules(str(source))) / "modules-v1"
    actual = _driver(identity_driver, tmp_path, {"mode": "directory", "configured": value, "input_path": str(source)})
    assert Path(actual["directory"]) == reference
    expected = Path(value).absolute() if value else (root if package else source.parent) / "build/btrc"
    assert reference == expected / "modules-v1"
    inventory = _tree(tmp_path / "compiler-source")
    binary = tmp_path / "compiler"
    binary.write_bytes(b"compiler")
    _write_receipt(binary, _fields(tmp_path / "compiler-source", inventory, binary))
    cache = CompilerCache(fingerprint=ToolchainFingerprint(inventory))
    cache.store_module_unit("directory-test", "record", "int value;", str(source))
    result = _driver(
        identity_driver,
        tmp_path,
        {
            "mode": "get",
            "executable": str(binary),
            "data_root": str(tmp_path / "compiler-source/src"),
            "input_path": str(source),
            "module": "directory-test",
        },
    )
    assert result["hit"] and result["record"] == "record" and result["text"] == "int value;"
    assert (reference / result["key"] / "unit.c").is_file()


def test_generation_cache_reads_shared_module_references(store, tmp_path, identity_driver):
    cache, data, entry = store
    cache.store_module_unit(data["module"], data["record"], data["text"])
    prefix = str(tmp_path / "program")
    data.update(prefix=prefix, plan=json.dumps({"schema": 5, "emitted-units": [prefix + ".unit-one.c"]}))
    stored = _driver(identity_driver, tmp_path, {**data, "mode": "generation-put"})
    assert stored["generation_hit"] and stored["unit"] == data["text"]
    assert _driver(identity_driver, tmp_path, {**data, "mode": "generation-get"})["generation_hit"]
    (entry / "unit.c").write_text("corrupt")
    assert not _driver(identity_driver, tmp_path, {**data, "mode": "generation-get"})["generation_hit"]
    cache.store_module_unit(data["module"], data["record"], data["text"])
    assert _driver(identity_driver, tmp_path, {**data, "mode": "generation-get"})["generation_hit"]


def test_shared_store_respects_aggregate_byte_limit(store):
    cache, data, _ = store
    limited = CompilerCache(fingerprint=cache._fingerprint, max_entry_bytes=8)
    limited.store_module_unit(data["module"], "four", "bytes")
    assert limited.load_module_unit(data["module"]) is None
    limited.store_module_unit(data["module"], "four", "byte")
    assert limited.load_module_unit(data["module"]) == ("four", "byte")


def test_selfhost_reader_waits_for_reference_entry_lease(store, tmp_path, identity_driver):
    cache, data, entry = store
    cache.store_module_unit(data["module"], data["record"], data["text"])
    path = tmp_path / "request.json"
    path.write_text(json.dumps({**data, "ready": True}))
    process = None
    try:
        with PublicationLock(entry, None, threading.Lock()):
            (entry / "unit.c").write_text("replacement")
            process = subprocess.Popen(
                [str(identity_driver), str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            import select

            assert select.select([process.stdout], [], [], 10)[0], "driver did not reach cache read"
            assert process.stdout.readline().strip() == "ready"
            with pytest.raises(subprocess.TimeoutExpired):
                process.communicate(timeout=0.2)
            record = entry / "record.txt"
            header, key, hashes, metadata = record.read_text().split("\n", 3)
            hashes = hashes.split(" ")[0] + " " + hashlib.sha256(b"replacement").hexdigest()
            record.write_text("\n".join((header, key, hashes, metadata)))
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 0, stderr
        result = json.loads(stdout)
        assert result["hit"] and result["text"] == "replacement"
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
