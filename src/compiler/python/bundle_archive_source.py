"""Stable, content-verified source reads for release archives."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator, Mapping, Set
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .artifacts.publication.storage import ArtifactStorage, ReparsePointError

_CHUNK_SIZE = 1024 * 1024
ContentSnapshot = tuple[bytes, int]
FileIdentity = tuple[int, int, int]


@dataclass(frozen=True)
class ArchiveEntry:
    path: Path
    device: int
    inode: int
    mode: int
    modified_time_ns: int
    is_directory: bool
    content: ContentSnapshot | None

    @property
    def size(self) -> int:
        return 0 if self.content is None else self.content[1]

    @property
    def identity(self) -> FileIdentity:
        return self.device, self.inode, stat.S_IFMT(self.mode)


class _HashingReader:
    def __init__(self, stream: BinaryIO, max_size: int) -> None:
        self._stream = stream
        self._digest = hashlib.sha256()
        self._size = 0
        self._max_size = max_size

    def read(self, size: int = -1) -> bytes:
        remaining = self._max_size - self._size
        if size < 0 or size > remaining + 1:
            size = remaining + 1
        chunk = self._stream.read(size)
        self._digest.update(chunk)
        self._size += len(chunk)
        if self._size > self._max_size:
            raise ValueError("archive source exceeds its expected size")
        return chunk

    @property
    def content(self) -> ContentSnapshot:
        return self._digest.digest(), self._size


class BundleArchiveSource:
    """Own stable discovery, reads, and revalidation for one bundle tree."""

    def __init__(
        self,
        bundle: Path,
        storage: ArtifactStorage | None = None,
    ) -> None:
        self._bundle = bundle
        self._storage = storage or ArtifactStorage()

    def discover(self) -> list[ArchiveEntry]:
        return [self._entry(path, metadata) for path, metadata in self._storage.real_tree_entries(self._bundle)]

    def discover_bounded(
        self,
        files: Mapping[str, int],
        directories: Set[str],
    ) -> list[ArchiveEntry]:
        """Capture exactly a manifest-bounded tree without hashing surprises."""

        self._storage.require_real_directory(self._bundle, "archive root")
        self._validate_directory_entries(
            self._expected_children(files, directories),
        )
        paths = [
            self._bundle,
            *(self._bundle / path for path in directories),
            *(self._bundle / path for path in files),
        ]
        paths.sort(key=lambda path: path.as_posix())
        entries = []
        for path in paths:
            relative = path.relative_to(self._bundle).as_posix()
            entries.append(
                self._entry(
                    path,
                    path.lstat(),
                    expected_size=files.get(relative),
                ),
            )
        return entries

    @contextmanager
    def open_regular(self, entry: ArchiveEntry) -> Iterator[_HashingReader]:
        if entry.content is None:
            raise ValueError(f"archive source is not a regular file: {entry.path}")
        descriptor = os.open(entry.path, self._open_flags())
        try:
            self._validate_regular_identity(entry, descriptor)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                before = self._hash_stream(stream, entry.size)
                if before != entry.content:
                    raise self._changed(entry)
                stream.seek(0)
                emitted = _HashingReader(stream, entry.size)
                yield emitted
                stream.seek(0)
                after = self._hash_stream(stream, entry.size)
                self._validate_regular_identity(entry, stream.fileno())
                if emitted.content != entry.content or after != entry.content:
                    raise self._changed(entry)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def validate_directory(self, entry: ArchiveEntry) -> None:
        metadata = entry.path.lstat()
        if (
            not entry.is_directory
            or not stat.S_ISDIR(metadata.st_mode)
            or self._storage.metadata_is_reparse_point(metadata)
            or self._metadata_identity(metadata) != entry.identity
        ):
            raise self._changed(entry)

    def validate_payload(self, entry: ArchiveEntry, payload: bytes) -> None:
        snapshot = hashlib.sha256(payload).digest(), len(payload)
        if snapshot != entry.content:
            raise self._changed(entry)

    def validate_snapshot(
        self,
        expected: list[ArchiveEntry],
        *,
        files: Mapping[str, int] | None = None,
        directories: Set[str] | None = None,
    ) -> None:
        """Revalidate the exact tree and every identity/digest after emission."""

        validate_metadata = files is not None and directories is not None
        if files is None or directories is None:
            current = self.discover()
        else:
            current = self.discover_bounded(files, directories)
        if len(current) != len(expected):
            raise ValueError(
                f"archive source tree changed while packaging: {self._bundle}",
            )
        for before, after in zip(expected, current, strict=True):
            if (
                before.path != after.path
                or before.identity != after.identity
                or before.mode != after.mode
                or (validate_metadata and before.modified_time_ns != after.modified_time_ns)
                or before.is_directory != after.is_directory
                or before.content != after.content
            ):
                raise self._changed(before)

    @staticmethod
    def _changed(entry: ArchiveEntry) -> ValueError:
        return ValueError(f"archive source changed while packaging: {entry.path}")

    @staticmethod
    def _metadata_identity(metadata: os.stat_result) -> FileIdentity:
        return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)

    def _validate_regular_identity(
        self,
        entry: ArchiveEntry,
        descriptor: int,
    ) -> None:
        opened = os.fstat(descriptor)
        current = entry.path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or self._storage.metadata_is_reparse_point(current)
            or self._metadata_identity(opened) != entry.identity
            or self._metadata_identity(current) != entry.identity
        ):
            raise self._changed(entry)

    @staticmethod
    def _hash_stream(
        stream: BinaryIO,
        max_size: int | None = None,
    ) -> ContentSnapshot:
        digest = hashlib.sha256()
        size = 0
        while chunk := stream.read(
            _CHUNK_SIZE if max_size is None else min(_CHUNK_SIZE, max_size - size + 1),
        ):
            digest.update(chunk)
            size += len(chunk)
            if max_size is not None and size > max_size:
                raise ValueError("archive source exceeds its expected size")
        return digest.digest(), size

    @staticmethod
    def _open_flags() -> int:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        return flags | getattr(os, "O_NOFOLLOW", 0)

    def _discover_regular(
        self,
        path: Path,
        metadata: os.stat_result,
        expected_size: int | None = None,
    ) -> ContentSnapshot:
        provisional = ArchiveEntry(
            path=path,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            mode=metadata.st_mode,
            modified_time_ns=metadata.st_mtime_ns,
            is_directory=False,
            content=None,
        )
        descriptor = os.open(path, self._open_flags())
        try:
            self._validate_regular_identity(provisional, descriptor)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                content = self._hash_stream(stream, expected_size)
                self._validate_regular_identity(provisional, stream.fileno())
                return content
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _entry(
        self,
        path: Path,
        metadata: os.stat_result,
        *,
        expected_size: int | None = None,
    ) -> ArchiveEntry:
        is_directory = stat.S_ISDIR(metadata.st_mode)
        if self._storage.metadata_is_reparse_point(metadata):
            raise ReparsePointError(path)
        if not is_directory and not stat.S_ISREG(metadata.st_mode):
            raise ValueError(
                f"archive source must be a regular file or directory: {path}",
            )
        if expected_size is not None and metadata.st_size != expected_size:
            raise ValueError(
                f"archive source changed size before validation: {path}",
            )
        return ArchiveEntry(
            path=path,
            device=metadata.st_dev,
            inode=metadata.st_ino,
            mode=metadata.st_mode,
            modified_time_ns=metadata.st_mtime_ns,
            is_directory=is_directory,
            content=(None if is_directory else self._discover_regular(path, metadata, expected_size)),
        )

    @staticmethod
    def _expected_children(
        files: Mapping[str, int],
        directories: Set[str],
    ) -> dict[str, set[str]]:
        children = {directory: set() for directory in {".", *directories}}
        for relative in [*directories, *files]:
            parsed = Path(relative)
            parent = parsed.parent.as_posix()
            children[parent].add(parsed.name)
        return children

    def _validate_directory_entries(
        self,
        expected: dict[str, set[str]],
    ) -> None:
        for relative, expected_names in expected.items():
            directory = self._bundle if relative == "." else self._bundle / relative
            metadata = self._storage.require_real_directory(
                directory,
                "archive source directory",
            )
            actual = set()
            with os.scandir(directory) as entries:
                for entry in entries:
                    child = directory / entry.name
                    child_metadata = entry.stat(follow_symlinks=False)
                    if self._storage.metadata_is_reparse_point(child_metadata):
                        raise ReparsePointError(child)
                    actual.add(entry.name)
                    if len(actual) > len(expected_names):
                        raise ValueError(
                            f"archive source tree has unexpected entries: {directory}",
                        )
            current = self._storage.require_real_directory(
                directory,
                "archive source directory",
            )
            if self._metadata_identity(current) != self._metadata_identity(
                metadata,
            ):
                raise ValueError(
                    f"archive source directory changed type: {directory}",
                )
            if actual != expected_names:
                raise ValueError(
                    f"archive source tree changed before validation: {directory}",
                )
