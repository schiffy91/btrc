"""Archive identity and transactional-publication security contracts."""

from __future__ import annotations

import hashlib
import os
import tarfile
import zipfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import pytest

import src.compiler.python.btrcc_bundle as bundle_module
import src.compiler.python.btrcc_bundle_archive as archive_module
import src.compiler.python.btrcc_bundle_validation as validation_module
import src.compiler.python.bundle_archive_source as archive_source_module
from src.compiler.python.btrcc_bundle import build_bundle
from src.compiler.python.btrcc_bundle_archive import write_tar_gz, write_zip
from src.tests.python.test_btrcc_bundle import _fixture, _manifest


class _MutatingReader:
    def __init__(self, stream, mutate: Callable[[], None]) -> None:
        self._stream = stream
        self._mutate = mutate
        self._mutated = False

    def __enter__(self):
        self._stream.__enter__()
        return self

    def __exit__(self, *args):
        return self._stream.__exit__(*args)

    def fileno(self) -> int:
        return self._stream.fileno()

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        if chunk and not self._mutated:
            self._mutated = True
            self._mutate()
        return chunk

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._stream.seek(offset, whence)


def _replace_contents_in_place(path: Path, payload: bytes, previous_mtime_ns: int) -> None:
    path.write_bytes(payload)
    metadata = path.stat()
    os.utime(path, ns=(metadata.st_atime_ns, previous_mtime_ns + 1_000_000_000))


def _wrap_archive_payload_reads(
    monkeypatch: pytest.MonkeyPatch,
    payload: Path,
    mutate: Callable[[], None],
) -> None:
    expected = payload.stat()
    original_fdopen = archive_source_module.os.fdopen

    def wrapped_fdopen(descriptor: int, *args, **kwargs):
        opened = os.fstat(descriptor)
        stream = original_fdopen(descriptor, *args, **kwargs)
        if (opened.st_dev, opened.st_ino) == (expected.st_dev, expected.st_ino):
            return _MutatingReader(stream, mutate)
        return stream

    monkeypatch.setattr(archive_source_module.os, "fdopen", wrapped_fdopen)


def test_bundle_copy_rejects_same_inode_same_size_mutation_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    source.write_bytes(b"a" * (2 * 1024 * 1024))
    initial = source.stat()
    original_fdopen = bundle_module.os.fdopen

    def mutating_fdopen(descriptor: int, *args, **kwargs):
        stream = original_fdopen(descriptor, *args, **kwargs)
        return _MutatingReader(
            stream,
            lambda: _replace_contents_in_place(source, b"b" * initial.st_size, initial.st_mtime_ns),
        )

    monkeypatch.setattr(bundle_module.os, "fdopen", mutating_fdopen)
    with pytest.raises(ValueError, match="changed while being copied"):
        bundle_module._copy_file(source, destination, 0o644, 0)

    changed = source.stat()
    assert (changed.st_dev, changed.st_ino, changed.st_size) == (
        initial.st_dev,
        initial.st_ino,
        initial.st_size,
    )


def test_bundle_copy_accepts_content_neutral_metadata_churn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    destination = tmp_path / "destination"
    payload = b"stable" * (1024 * 1024)
    source.write_bytes(payload)
    original_fdopen = bundle_module.os.fdopen

    def touching_fdopen(descriptor: int, *args, **kwargs):
        stream = original_fdopen(descriptor, *args, **kwargs)
        return _MutatingReader(stream, source.touch)

    monkeypatch.setattr(bundle_module.os, "fdopen", touching_fdopen)
    bundle_module._copy_file(source, destination, 0o644, 7)

    assert destination.read_bytes() == payload


def test_artifact_hash_rejects_same_inode_growth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "archive"
    artifact.write_bytes(b"a" * 4096)
    initial = artifact.stat()
    original_fdopen = validation_module.os.fdopen

    def append_byte() -> None:
        with artifact.open("ab") as destination:
            destination.write(b"x")

    def mutating_fdopen(descriptor: int, *args, **kwargs):
        opened = os.fstat(descriptor)
        stream = original_fdopen(descriptor, *args, **kwargs)
        if (opened.st_dev, opened.st_ino) == (initial.st_dev, initial.st_ino):
            return _MutatingReader(stream, append_byte)
        return stream

    monkeypatch.setattr(validation_module.os, "fdopen", mutating_fdopen)
    with pytest.raises(ValueError, match="changed size"):
        validation_module._hash_artifact(artifact)
    assert artifact.stat().st_size == initial.st_size + 1


def test_archive_reader_revalidates_same_inode_same_size_source_after_read(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "btrcc-test"
    bundle.mkdir()
    payload = bundle / "payload"
    payload.write_bytes(b"a" * 4096)
    initial = payload.stat()
    entry = next(item for item in archive_module._bundle_entries(bundle) if item.path == payload)

    with (
        pytest.raises(ValueError, match="changed while packaging"),
        archive_module._open_regular(entry) as stream,
    ):
        assert stream.read(1)
        _replace_contents_in_place(payload, b"b" * initial.st_size, initial.st_mtime_ns)


@pytest.mark.parametrize("writer", [write_tar_gz, write_zip])
def test_archive_writers_accept_content_neutral_metadata_churn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: Callable[[Path, Path, int], None],
) -> None:
    bundle = tmp_path / "btrcc-test"
    bundle.mkdir()
    payload = bundle / "payload"
    content = b"stable archive payload"
    payload.write_bytes(content)

    def touch_metadata() -> None:
        metadata = payload.stat()
        os.utime(
            payload,
            ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000),
        )

    _wrap_archive_payload_reads(monkeypatch, payload, touch_metadata)
    destination = tmp_path / "archive"
    writer(bundle, destination, 0)

    assert destination.is_file()
    if writer is write_zip:
        with zipfile.ZipFile(destination) as archive:
            archived = archive.read("btrcc-test/payload")
    else:
        with tarfile.open(destination, "r:gz") as archive:
            archived_file = archive.extractfile("btrcc-test/payload")
            assert archived_file is not None
            archived = archived_file.read()
    assert archived == content


@pytest.mark.parametrize("writer", [write_tar_gz, write_zip])
def test_archive_writers_reject_mutation_after_discovery_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: Callable[[Path, Path, int], None],
) -> None:
    bundle = tmp_path / "btrcc-test"
    bundle.mkdir()
    payload = bundle / "payload"
    payload.write_bytes(b"a" * 4096)
    initial = payload.stat()
    _wrap_archive_payload_reads(
        monkeypatch,
        payload,
        lambda: _replace_contents_in_place(
            payload,
            b"b" * initial.st_size,
            initial.st_mtime_ns,
        ),
    )

    with pytest.raises(ValueError, match="changed while packaging"):
        writer(bundle, tmp_path / "archive", 0)


@pytest.mark.parametrize("writer", [write_tar_gz, write_zip])
@pytest.mark.parametrize("change", ["modify", "remove", "add"])
def test_archive_writers_reject_tree_changes_after_entry_emission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: Callable[[Path, Path, int], None],
    change: str,
) -> None:
    bundle = tmp_path / "btrcc-test"
    bundle.mkdir()
    early = bundle / "early"
    late = bundle / "late"
    early.write_bytes(b"early-old")
    late.write_bytes(b"late")
    open_regular = archive_module._open_regular
    changed = False

    @contextmanager
    def change_after_last_emission(entry):
        nonlocal changed
        with open_regular(entry) as source:
            yield source
        if entry.path == late and not changed:
            changed = True
            if change == "modify":
                early.write_bytes(b"early-new")
            elif change == "remove":
                early.unlink()
            else:
                (bundle / "added").write_bytes(b"added")

    monkeypatch.setattr(archive_module, "_open_regular", change_after_last_emission)
    destination = tmp_path / "archive"
    with pytest.raises(ValueError, match="changed while packaging"):
        writer(bundle, destination, 0)
    assert not destination.exists()


@pytest.mark.parametrize("writer", [write_tar_gz, write_zip])
def test_archive_writers_reject_symlinked_payloads(
    tmp_path: Path,
    writer: Callable[[Path, Path, int], None],
) -> None:
    bundle = tmp_path / "btrcc-test"
    bundle.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside-bundle")
    (bundle / "linked").symlink_to(outside)

    with pytest.raises(ValueError, match="link or reparse point"):
        writer(bundle, tmp_path / "archive", 0)


@pytest.mark.parametrize("writer", [write_tar_gz, write_zip])
def test_archive_writers_reject_destinations_inside_the_source(
    tmp_path: Path,
    writer: Callable[[Path, Path, int], None],
) -> None:
    bundle = tmp_path / "btrcc-test"
    bundle.mkdir()
    (bundle / "payload").write_bytes(b"payload")

    with pytest.raises(ValueError, match="outside its source bundle"):
        writer(bundle, bundle / "self-archive", 0)


@pytest.mark.parametrize("writer", [write_tar_gz, write_zip])
def test_archive_writers_reject_destination_parent_aliasing_source(
    tmp_path: Path,
    writer: Callable[[Path, Path, int], None],
) -> None:
    bundle = tmp_path / "btrcc-test"
    bundle.mkdir()
    (bundle / "payload").write_bytes(b"payload")
    alias = tmp_path / "bundle-alias"
    alias.symlink_to(bundle, target_is_directory=True)

    with pytest.raises(ValueError, match="outside its source bundle"):
        writer(bundle, alias / "self-archive", 0)


@pytest.mark.parametrize("target", ["linux-x64", "windows-x64"])
def test_archive_is_created_from_private_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    source_root, binary = _fixture(tmp_path / "source", target)
    output = tmp_path / "dist"
    original = bundle_module.write_zip if target.startswith("windows-") else bundle_module.write_tar_gz
    observed = False

    def observing_writer(bundle: Path, destination: Path, epoch: int) -> None:
        nonlocal observed
        observed = True
        assert bundle != output / f"btrcc-{target}"
        assert not (output / f"btrcc-{target}").exists()
        assert destination.parent != output
        original(bundle, destination, epoch)

    name = "write_zip" if target.startswith("windows-") else "write_tar_gz"
    monkeypatch.setattr(bundle_module, name, observing_writer)
    result = build_bundle(
        binary=binary,
        target=target,
        output_dir=output,
        source_root=source_root,
    )

    assert observed
    manifest = _manifest(result.bundle)
    expected = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    prefix = f"btrcc-{target}/"
    if target.startswith("windows-"):
        with zipfile.ZipFile(result.archive) as archive:
            actual = {
                name.removeprefix(prefix): hashlib.sha256(archive.read(name)).hexdigest()
                for name in archive.namelist()
                if not name.endswith("/") and name != f"{prefix}share/btrc/manifest.json"
            }
    else:
        with tarfile.open(result.archive, "r:gz") as archive:
            actual = {
                member.name.removeprefix(prefix): hashlib.sha256(
                    archive.extractfile(member).read()  # type: ignore[union-attr]
                ).hexdigest()
                for member in archive.getmembers()
                if member.isfile() and member.name != f"{prefix}share/btrc/manifest.json"
            }
    assert actual == expected
