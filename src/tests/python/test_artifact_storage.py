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


def test_fsync_directory_does_not_swallow_windows_identity_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "artifact"
    directory.mkdir()

    def fail_fstat(descriptor: int):
        raise OSError("injected identity failure")

    monkeypatch.setattr(storage_module.os, "name", "nt")
    monkeypatch.setattr(storage_module.os, "fstat", fail_fstat)
    with pytest.raises(OSError, match="injected identity failure"):
        ArtifactStorage().fsync_directory(directory)


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
