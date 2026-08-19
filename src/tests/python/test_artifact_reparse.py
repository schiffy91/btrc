"""Cross-platform contracts for rejecting links and Windows reparse points."""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.compiler.python.artifacts.publication as storage_module
from src.compiler.python.artifacts.publication import (
    ArtifactStorage,
    ReparsePointError,
)
from src.compiler.python.artifacts.selfhost import SelfhostBundleBuilder
from src.compiler.python.artifacts.archive import ArchiveCodec

ARCHIVE_CODEC = ArchiveCodec()
write_tar_gz = ARCHIVE_CODEC.write_tar_gz
write_zip = ARCHIVE_CODEC.write_zip
from src.tests.python.test_btrcc_bundle import _fixture


def _classify_path_as_reparse(
    monkeypatch: pytest.MonkeyPatch,
    path: Path,
) -> None:
    marked = path.lstat()
    identity = marked.st_dev, marked.st_ino
    original = ArtifactStorage.metadata_is_reparse_point

    def classify(self: ArtifactStorage, metadata: os.stat_result) -> bool:
        return (metadata.st_dev, metadata.st_ino) == identity or original(self, metadata)

    monkeypatch.setattr(ArtifactStorage, "metadata_is_reparse_point", classify)


def test_reparse_tag_is_recognized_without_symlink_mode() -> None:
    junction = SimpleNamespace(
        st_mode=stat.S_IFDIR | 0o755,
        st_reparse_tag=0xA0000003,
    )
    directory = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_reparse_tag=0)

    storage = ArtifactStorage()
    assert storage.metadata_is_reparse_point(junction)
    assert not storage.metadata_is_reparse_point(directory)


def test_tree_walker_rejects_reparse_directory_before_descent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "bundle"
    marked = root / "marked"
    marked.mkdir(parents=True)
    (marked / "outside-payload").write_bytes(b"outside")
    _classify_path_as_reparse(monkeypatch, marked)
    scanned: list[Path] = []
    scandir = storage_module.os.scandir

    def observe_scandir(directory: Path):
        scanned.append(Path(directory))
        return scandir(directory)

    monkeypatch.setattr(storage_module.os, "scandir", observe_scandir)
    with pytest.raises(ReparsePointError, match="link or reparse point"):
        ArtifactStorage().real_tree_entries(root)

    assert scanned == [root]


@pytest.mark.parametrize("writer", [write_tar_gz, write_zip])
def test_archive_writers_apply_reparse_policy_to_every_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    writer: Callable[[Path, Path, int], None],
) -> None:
    bundle = tmp_path / "btrcc-test"
    bundle.mkdir()
    payload = bundle / "payload"
    payload.write_bytes(b"payload")
    _classify_path_as_reparse(monkeypatch, payload)
    destination = tmp_path / "archive"

    with pytest.raises(ReparsePointError, match="link or reparse point"):
        writer(bundle, destination, 0)
    assert not destination.exists()


@pytest.mark.parametrize("boundary", ["source", "output", "destination"])
def test_artifact_boundaries_apply_the_shared_reparse_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    source_root, binary = _fixture(tmp_path / "source")
    output = tmp_path / "dist"
    output.mkdir()
    marked = {
        "source": source_root,
        "output": output,
        "destination": output,
    }[boundary]
    _classify_path_as_reparse(monkeypatch, marked)

    if boundary == "destination":
        with pytest.raises(ValueError, match="invalid publication destination"):
            ArtifactStorage().destination_exists(output, is_directory=True)
        return

    subject = "bundle source root" if boundary == "source" else "bundle output directory"
    with pytest.raises(ValueError, match=subject):
        SelfhostBundleBuilder().build(
            binary=binary,
            target="linux-x64",
            output_dir=output,
            source_root=source_root,
        )


@pytest.mark.skipif(os.name != "nt", reason="native junctions require Windows")
def test_windows_junction_is_rejected_as_archive_entry_and_destination(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload").write_bytes(b"outside")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    junction = bundle / "junction"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        pytest.skip(f"cannot create a native junction: {result.stderr.strip()}")

    try:
        assert junction.is_junction()
        with pytest.raises(ReparsePointError, match="link or reparse point"):
            write_zip(bundle, tmp_path / "archive.zip", 0)
        with pytest.raises(ValueError, match="invalid publication destination"):
            ArtifactStorage().destination_exists(junction, is_directory=True)
    finally:
        if junction.is_junction():
            junction.rmdir()
