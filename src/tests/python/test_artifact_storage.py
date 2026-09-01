"""Descriptor-lifetime contracts for artifact storage."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import src.compiler.python.artifacts.publication as storage_module
from src.compiler.python.artifacts.publication import ArtifactStorage


def _observe_close(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    closed: list[int] = []
    close = os.close

    def observed(descriptor: int) -> None:
        closed.append(descriptor)
        close(descriptor)

    monkeypatch.setattr(storage_module.os, "close", observed)
    return closed


def test_open_regular_closes_descriptor_when_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")
    closed = _observe_close(monkeypatch)

    def fail_fstat(descriptor: int):
        raise OSError("injected fstat failure")

    monkeypatch.setattr(storage_module.os, "fstat", fail_fstat)
    with pytest.raises(OSError, match="injected fstat failure"):
        ArtifactStorage().open_regular(artifact)

    assert len(closed) == 1


def test_open_regular_closes_descriptor_when_lstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")
    closed = _observe_close(monkeypatch)
    lstat = Path.lstat

    def fail_lstat(path: Path):
        if path == artifact:
            raise OSError("injected lstat failure")
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", fail_lstat)
    with pytest.raises(OSError, match="injected lstat failure"):
        ArtifactStorage().open_regular(artifact)

    assert len(closed) == 1


def test_open_regular_for_sync_adds_windows_write_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")
    flags: list[int] = []
    open_file = os.open

    def observed(path: Path, options: int, mode: int = 0o777) -> int:
        flags.append(options)
        return open_file(path, options, mode)

    monkeypatch.setattr(storage_module.os, "name", "nt")
    monkeypatch.setattr(storage_module.os, "open", observed)
    storage = ArtifactStorage()
    ordinary_descriptor = storage.open_regular(artifact)
    os.close(ordinary_descriptor)
    sync_descriptor = storage.open_regular_for_sync(artifact)
    os.close(sync_descriptor)

    access_mask = os.O_WRONLY | os.O_RDWR
    assert len(flags) == 2
    assert flags[0] & access_mask == os.O_RDONLY
    assert flags[1] & access_mask == os.O_WRONLY


def test_fsync_artifact_reports_the_failing_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")

    def fail_fsync(descriptor: int) -> None:
        raise OSError(9, "injected bad descriptor")

    monkeypatch.setattr(storage_module.os, "fsync", fail_fsync)
    with pytest.raises(OSError) as raised:
        ArtifactStorage().fsync_artifact(artifact, is_directory=False)
    assert f"cannot flush publication artifact: {artifact}" in str(raised.value)


@pytest.mark.skipif(os.name != "nt", reason="requires the native Windows CRT")
def test_fsync_artifact_flushes_native_windows_file_and_tree(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "nested").write_bytes(b"nested payload")

    storage = ArtifactStorage()
    storage.fsync_artifact(artifact, is_directory=False)
    storage.fsync_artifact(tree, is_directory=True)


def test_fsync_directory_does_not_swallow_windows_identity_failure_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "artifact"
    directory.mkdir()
    opened = tmp_path / "opened"
    opened.write_bytes(b"payload")
    descriptor = os.open(opened, os.O_RDONLY)

    def open_directory(path: Path, flags: int) -> int:
        return descriptor

    def fail_fstat(descriptor: int):
        raise OSError("injected identity failure")

    monkeypatch.setattr(storage_module.os, "name", "nt")
    monkeypatch.setattr(storage_module.os, "open", open_directory)
    monkeypatch.setattr(storage_module.os, "fstat", fail_fstat)
    with pytest.raises(OSError, match="injected identity failure"):
        ArtifactStorage().fsync_directory(directory)


@pytest.mark.skipif(os.name == "nt", reason="requires POSIX no-follow utime")
def test_normalize_timestamp_uses_no_follow_posix_utime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")
    calls: list[tuple[Path, tuple[int, int], bool]] = []
    utime = os.utime

    def observed(path: Path, times: tuple[int, int], *, follow_symlinks: bool) -> None:
        calls.append((path, times, follow_symlinks))
        utime(path, times, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(storage_module.os, "utime", observed)
    ArtifactStorage().normalize_timestamp(artifact, 1_700_000_000)

    assert calls == [(artifact, (1_700_000_000, 1_700_000_000), False)]


def test_normalize_timestamp_routes_windows_through_handle_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")
    calls: list[tuple[Path, int]] = []
    utime = os.utime

    def observed(self: ArtifactStorage, path: Path, epoch: int, expected: os.stat_result) -> None:
        calls.append((path, epoch))
        utime(path, (epoch, epoch))

    monkeypatch.setattr(storage_module.os, "name", "nt")
    monkeypatch.setattr(ArtifactStorage, "_set_windows_timestamp", observed)
    ArtifactStorage().normalize_timestamp(artifact, 1_700_000_000)

    assert calls == [(artifact, 1_700_000_000)]


def test_normalize_timestamp_rejects_windows_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"replacement")

    def replace(self: ArtifactStorage, path: Path, epoch: int, expected: os.stat_result) -> None:
        os.replace(replacement, path)

    monkeypatch.setattr(storage_module.os, "name", "nt")
    monkeypatch.setattr(ArtifactStorage, "_set_windows_timestamp", replace)
    with pytest.raises(ValueError, match="artifact timestamp target changed identity"):
        ArtifactStorage().normalize_timestamp(artifact, 1_700_000_000)


def test_normalize_timestamp_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    artifact = tmp_path / "artifact"
    try:
        artifact.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    with pytest.raises(ValueError, match="artifact timestamp target must be a real file or directory"):
        ArtifactStorage().normalize_timestamp(artifact, 1_700_000_000)


@pytest.mark.skipif(os.name != "nt", reason="requires the native Windows handle API")
def test_normalize_timestamp_sets_windows_file_and_directory_times(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.write_bytes(b"payload")
    directory = tmp_path / "directory"
    directory.mkdir()
    epoch = 1_700_000_000

    storage = ArtifactStorage()
    storage.normalize_timestamp(artifact, epoch)
    storage.normalize_timestamp(directory, epoch)

    assert artifact.lstat().st_mtime_ns == epoch * 1_000_000_000
    assert directory.lstat().st_mtime_ns == epoch * 1_000_000_000


def test_destination_exists_accepts_a_stable_regular_file(tmp_path: Path) -> None:
    destination = tmp_path / "artifact"
    destination.write_bytes(b"payload")

    assert ArtifactStorage().destination_exists(destination, is_directory=False)


def test_destination_exists_does_not_preserve_a_symlink_file(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"payload")
    destination = tmp_path / "artifact"
    try:
        destination.symlink_to(target)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    assert not ArtifactStorage().destination_exists(destination, is_directory=False)
    assert destination.is_symlink()
    assert target.read_bytes() == b"payload"


def test_destination_exists_rejects_a_symlink_directory(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    destination = tmp_path / "artifact"
    try:
        destination.symlink_to(target, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    with pytest.raises(ValueError, match="invalid publication destination"):
        ArtifactStorage().destination_exists(destination, is_directory=True)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_destination_exists_rejects_a_special_file(tmp_path: Path) -> None:
    destination = tmp_path / "artifact"
    os.mkfifo(destination)

    with pytest.raises(ValueError, match="invalid publication destination"):
        ArtifactStorage().destination_exists(destination, is_directory=False)
