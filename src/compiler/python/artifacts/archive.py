"""Canonical archives, release-target binaries, and bundle validation."""

from __future__ import annotations

import datetime
import gzip
import hashlib
import os
import platform
import stat
import struct
import tarfile
import tempfile
import zipfile
import zlib
from collections.abc import Iterable, Iterator, Mapping, Set
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import BinaryIO

from .publication import ArtifactStorage, ReparsePointError

_CHUNK_SIZE = 1024 * 1024
_MAX_TAR_BYTES = 2 * 1024 * 1024 * 1024
_TAR_RECORD_SIZE = 20 * tarfile.BLOCKSIZE
_TAR_TAIL_SIZE = 2 * _TAR_RECORD_SIZE
_ZIP_VERSION = 20
_MAX_ARCHIVE_EPOCH = 0xFFFFFFFF
_ZIP_MINIMUM_EPOCH = 315532800
_MAX_BINARY_BYTES = 2 * 1024 * 1024 * 1024
_MAX_HEADER_REGION = 16 * 1024 * 1024
_ELF_HEADER_SIZE = 64
_ELF_PROGRAM_HEADER_SIZE = 56
_MACH_HEADER_SIZE = 32
_PE_MAX_SECTIONS = 96
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1


@dataclass(frozen=True)
class GzipLayout:
    uncompressed_size: int
    tail: bytes
    modified_time: int


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


class ArchiveSource:
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


class ArchiveCodec:
    """Own deterministic archive encoding and its canonical physical layout."""

    def __init__(self, storage: ArtifactStorage | None = None) -> None:
        self._storage = storage or ArtifactStorage()

    def _invalid(self) -> ValueError:
        return ValueError("bundle archive is not a valid tar or ZIP file: noncanonical physical layout")

    def _read_exact(self, stream: BinaryIO, size: int) -> bytes:
        payload = bytearray()
        while len(payload) < size:
            chunk = stream.read(size - len(payload))
            if not chunk:
                raise self._invalid()
            payload.extend(chunk)
        return bytes(payload)

    def validate_gzip_layout(self, stream: BinaryIO) -> GzipLayout:
        """Require the exact single-member gzip shape emitted by ``GzipFile``."""

        header = self._read_exact(stream, 10)
        if header[:3] != b"\x1f\x8b\x08" or header[3] != 0 or header[8] != 2 or header[9] != 0xFF:
            raise self._invalid()
        modified_time = struct.unpack_from("<I", header, 4)[0]
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        total = 0
        tail = b""

        def consume(decoded: bytes) -> None:
            nonlocal total, tail
            total += len(decoded)
            if total > _MAX_TAR_BYTES:
                raise self._invalid()
            tail = (tail + decoded)[-_TAR_TAIL_SIZE:]

        def feed(encoded: bytes) -> None:
            pending = encoded
            while pending:
                decoded = inflater.decompress(pending, _CHUNK_SIZE)
                consume(decoded)
                if inflater.unused_data:
                    raise self._invalid()
                pending = inflater.unconsumed_tail

        try:
            feed(header)
            while chunk := stream.read(_CHUNK_SIZE):
                if inflater.eof:
                    raise self._invalid()
                feed(chunk)
            consume(inflater.flush())
        except zlib.error as error:
            raise self._invalid() from error
        if not inflater.eof or inflater.unused_data:
            raise self._invalid()
        return GzipLayout(total, tail, modified_time)

    def validate_tar_end(self, layout: GzipLayout, logical_end: int, modified_time: int) -> None:
        """Require two end blocks and only writer-added record padding."""

        padded_end = (
            (logical_end + 2 * tarfile.BLOCKSIZE + _TAR_RECORD_SIZE - 1) // _TAR_RECORD_SIZE
        ) * _TAR_RECORD_SIZE
        tail_start = layout.uncompressed_size - len(layout.tail)
        if (
            padded_end != layout.uncompressed_size
            or modified_time != layout.modified_time
            or logical_end < tail_start
            or any(layout.tail[logical_end - tail_start :])
        ):
            raise self._invalid()

    def validate_tar_member_padding(
        self,
        stream: BinaryIO,
        extents: list[tuple[int, int]],
    ) -> None:
        """Require every file's alignment padding to remain zero-filled."""

        for offset, size in extents:
            stream.seek(offset)
            if any(self._read_exact(stream, size)):
                raise self._invalid()

    def validate_tar_headers(
        self,
        stream: BinaryIO,
        headers: list[tuple[int, int, bytes]],
    ) -> None:
        """Require each raw header span to match the canonical PAX encoding."""

        for offset, data_offset, expected in headers:
            if data_offset - offset != len(expected):
                raise self._invalid()
            stream.seek(offset)
            if self._read_exact(stream, len(expected)) != expected:
                raise self._invalid()

    def _encoded_name(self, entry: zipfile.ZipInfo) -> bytes:
        encoding = "utf-8" if entry.flag_bits & 0x800 else "cp437"
        try:
            encoded = entry.filename.encode(encoding)
        except UnicodeError as error:
            raise self._invalid() from error
        return encoded

    def validate_zip_layout(
        self,
        stream: BinaryIO,
        archive: zipfile.ZipFile,
        entries: list[zipfile.ZipInfo],
        expected_modes: dict[str, int],
        expected_timestamp: tuple[int, int, int, int, int, int],
    ) -> None:
        """Reject ZIP prefixes, trailers, comments, descriptors, and layout gaps."""

        stream.seek(0, 2)
        archive_size = stream.tell()
        if archive_size < 22:
            raise self._invalid()
        stream.seek(archive_size - 22)
        eocd = struct.unpack("<IHHHHIIH", self._read_exact(stream, 22))
        signature, disk, central_disk, disk_entries, entry_count, central_size, central_offset, comment_size = eocd
        if (
            signature != 0x06054B50
            or disk
            or central_disk
            or disk_entries != len(entries)
            or entry_count != len(entries)
            or comment_size
            or central_offset + central_size != archive_size - 22
            or archive.start_dir != central_offset
        ):
            raise self._invalid()
        cursor = 0
        central_expected = 0
        year, month, day, hour, minute, second = expected_timestamp
        expected_time = (hour << 11) | (minute << 5) | (second // 2)
        expected_date = ((year - 1980) << 9) | (month << 5) | day
        for entry in entries:
            encoded_name = self._encoded_name(entry)
            year, month, day, hour, minute, second = entry.date_time
            central_time = (hour << 11) | (minute << 5) | (second // 2)
            central_date = ((year - 1980) << 9) | (month << 5) | day
            expected_mode = expected_modes.get(entry.filename)
            expected_type = stat.S_IFDIR if entry.is_dir() else stat.S_IFREG
            expected_dos_attributes = 0x10 if entry.is_dir() else 0
            expected_external_attributes = (
                ((expected_type | expected_mode) & 0xFFFF) << 16 | expected_dos_attributes
                if expected_mode is not None
                else None
            )
            if (
                entry.header_offset != cursor
                or entry.date_time != expected_timestamp
                or entry.flag_bits & ~0x800
                or entry.compress_type != zipfile.ZIP_DEFLATED
                or entry.create_system != 3
                or entry.create_version != _ZIP_VERSION
                or entry.extract_version != _ZIP_VERSION
                or entry.reserved
                or entry.volume
                or entry.internal_attr
                or entry.external_attr != expected_external_attributes
                or entry.extra
                or entry.comment
            ):
                raise self._invalid()
            stream.seek(cursor)
            local = struct.unpack("<IHHHHHIIIHH", self._read_exact(stream, 30))
            local_signature, local_version, flags, method, modified_time, modified_date = local[:6]
            crc, compressed_size, file_size, name_size, extra_size = local[6:]
            local_name = self._read_exact(stream, name_size)
            if (
                local_signature != 0x04034B50
                or local_version != _ZIP_VERSION
                or flags != entry.flag_bits
                or method != entry.compress_type
                or (modified_date, modified_time) != (expected_date, expected_time)
                or (modified_date, modified_time) != (central_date, central_time)
                or crc != entry.CRC
                or compressed_size != entry.compress_size
                or file_size != entry.file_size
                or local_name != encoded_name
                or extra_size
            ):
                raise self._invalid()
            cursor += 30 + name_size + entry.compress_size
            central_expected += 46 + len(encoded_name)
        if cursor != central_offset or central_expected != central_size:
            raise self._invalid()

    def canonical_epoch(self, modified_times_ns: Iterable[int]) -> int:
        """Derive one exact, archive-representable epoch from staged metadata."""

        modified_times = set(modified_times_ns)
        if len(modified_times) != 1:
            raise ValueError("bundle artifacts have noncanonical timestamps")
        modified_time_ns = next(iter(modified_times))
        if (
            modified_time_ns < 0
            or modified_time_ns % 1_000_000_000
            or modified_time_ns > _MAX_ARCHIVE_EPOCH * 1_000_000_000
        ):
            raise ValueError("bundle artifacts have noncanonical timestamps")
        return modified_time_ns // 1_000_000_000

    def canonical_tar_info(
        self,
        name: str,
        *,
        is_directory: bool,
        mode: int,
        size: int,
        modified_time: int,
    ) -> tarfile.TarInfo:
        """Return the exact tar metadata shape used for bundle members."""

        info = tarfile.TarInfo(name)
        info.mtime = modified_time
        info.uid = 0
        info.gid = 0
        info.uname = ""
        info.gname = ""
        info.mode = mode
        if is_directory:
            info.type = tarfile.DIRTYPE
        else:
            info.type = tarfile.REGTYPE
            info.size = size
        return info

    def canonical_zip_timestamp(self, modified_time: int) -> tuple[int, int, int, int, int, int]:
        """Convert an epoch to the canonical even-second UTC ZIP timestamp."""

        value = datetime.datetime.fromtimestamp(
            max(modified_time, _ZIP_MINIMUM_EPOCH),
            datetime.UTC,
        )
        return value.year, value.month, value.day, value.hour, value.minute, value.second & ~1

    def _reject_destination_in_bundle(self, bundle: Path, destination: Path) -> None:
        bundle_path = os.path.realpath(bundle)
        destination_path = os.path.realpath(destination)
        try:
            inside = os.path.commonpath((bundle_path, destination_path)) == bundle_path
        except ValueError:
            inside = False
        if inside:
            raise ValueError(f"archive destination must be outside its source bundle: {destination}")

    def _portable_mode(self, entry: ArchiveEntry, bundle: Path) -> int:
        if entry.is_directory:
            return 0o755
        relative = entry.path.relative_to(bundle)
        if len(relative.parts) == 2 and relative.parts[0] == "bin" and relative.name in {"btrcc", "btrcc.exe"}:
            return 0o755
        return 0o644

    def _tar_info(self, entry: ArchiveEntry, bundle: Path, epoch: int) -> tarfile.TarInfo:
        relative = entry.path.relative_to(bundle.parent).as_posix()
        name = relative + ("/" if entry.is_directory else "")
        return self.canonical_tar_info(
            name,
            is_directory=entry.is_directory,
            mode=self._portable_mode(entry, bundle),
            size=entry.size,
            modified_time=epoch,
        )

    def write_tar_gz(self, bundle: Path, destination: Path, epoch: int) -> None:
        """Write a byte-reproducible gzip-compressed POSIX tar archive."""

        self._reject_destination_in_bundle(bundle, destination)
        source = ArchiveSource(bundle, self._storage)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=f".{destination.name}.tmp-",
                dir=destination.parent,
                delete=False,
            ) as raw:
                temporary = Path(raw.name)
                with (
                    gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed,
                    tarfile.open(
                        fileobj=compressed,
                        mode="w",
                        format=tarfile.PAX_FORMAT,
                    ) as archive,
                ):
                    entries = source.discover()
                    for entry in entries:
                        info = self._tar_info(entry, bundle, epoch)
                        if not entry.is_directory:
                            with source.open_regular(entry) as payload:
                                archive.addfile(info, payload)
                        else:
                            source.validate_directory(entry)
                            archive.addfile(info)
                    source.validate_snapshot(entries)
            os.replace(temporary, destination)
            destination.chmod(0o644)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def write_zip(self, bundle: Path, destination: Path, epoch: int) -> None:
        """Write a deterministic ZIP archive with portable Unix mode metadata."""

        self._reject_destination_in_bundle(bundle, destination)
        source = ArchiveSource(bundle, self._storage)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                prefix=f".{destination.name}.tmp-",
                dir=destination.parent,
                delete=False,
            ) as raw:
                temporary = Path(raw.name)
                with zipfile.ZipFile(
                    raw,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                ) as archive:
                    entries = source.discover()
                    for entry in entries:
                        relative = entry.path.relative_to(bundle.parent).as_posix()
                        name = relative + ("/" if entry.is_directory else "")
                        info = zipfile.ZipInfo(name, self.canonical_zip_timestamp(epoch))
                        info.create_system = 3
                        if entry.is_directory:
                            source.validate_directory(entry)
                            mode = stat.S_IFDIR | self._portable_mode(entry, bundle)
                            dos_attributes = 0x10
                            payload = b""
                        else:
                            mode = stat.S_IFREG | self._portable_mode(entry, bundle)
                            dos_attributes = 0
                            with source.open_regular(entry) as payload_stream:
                                payload = payload_stream.read()
                            source.validate_payload(entry, payload)
                        info.external_attr = (mode & 0xFFFF) << 16 | dos_attributes
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, payload)
                    source.validate_snapshot(entries)
            os.replace(temporary, destination)
            destination.chmod(0o644)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def write_checksum(self, archive: Path) -> Path:
        """Write the conventional SHA-256 sidecar for ``archive``."""

        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        destination = archive.with_name(f"{archive.name}.sha256")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{destination.name}.tmp-",
                dir=destination.parent,
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(f"{digest}  {archive.name}\n")
            os.replace(temporary, destination)
            destination.chmod(0o644)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return destination


class ArchiveValidator:
    """Validate one release archive against its immutable bundle contract."""

    def __init__(
        self,
        archive_name: str,
        expected_files: dict[str, ContentSnapshot],
        expected_directories: set[str],
        expected_modes: dict[str, int],
        expected_modified_time: int,
        codec: ArchiveCodec | None = None,
    ) -> None:
        self._archive_name = archive_name
        self._expected_files = dict(expected_files)
        self._expected_directories = set(expected_directories)
        self._expected_modes = dict(expected_modes)
        self._expected_modified_time = expected_modified_time
        self._codec = codec or ArchiveCodec()

    def validate(self, stream: BinaryIO) -> None:
        try:
            if self._archive_name.endswith(".zip"):
                self._validate_zip(stream)
            elif self._archive_name.endswith(".tar.gz"):
                self._validate_tar(stream)
            else:
                raise ValueError(
                    f"unsupported bundle archive format: {self._archive_name}",
                )
        except (
            tarfile.TarError,
            zipfile.BadZipFile,
            EOFError,
            RuntimeError,
            NotImplementedError,
        ) as error:
            raise ValueError(
                "bundle archive is not a valid tar or ZIP file",
            ) from error

    def _validate_tar(self, stream: BinaryIO) -> None:
        physical = self._codec.validate_gzip_layout(stream)
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r:gz") as archive:
            members = []
            for member in archive:
                members.append(member)
                if len(members) > len(self._expected_modes):
                    raise ValueError(
                        "bundle archive has unexpected or duplicate members",
                    )
            names = []
            timestamps = set()
            padding_extents = []
            header_spans = []
            for member in members:
                if member.type not in {tarfile.REGTYPE, tarfile.DIRTYPE}:
                    raise ValueError(
                        f"bundle archive contains a special member: {member.name}",
                    )
                name = self._canonical_member(member.name, member.isdir())
                names.append(name)
                timestamps.add(member.mtime)
                if (
                    member.uid != 0
                    or member.gid != 0
                    or member.uname
                    or member.gname
                    or member.linkname
                    or member.devmajor
                    or member.devminor
                    or set(member.pax_headers) - {"path"}
                    or member.pax_headers.get("path", member.name) != member.name
                ):
                    raise ValueError(
                        f"bundle archive member has noncanonical metadata: {name}",
                    )
                if member.mode != self._expected_modes.get(name):
                    raise ValueError(
                        f"bundle archive member has a noncanonical mode: {name}",
                    )
                if member.isdir():
                    expected_size = 0
                else:
                    expected = self._expected_files.get(name)
                    if expected is None or member.size != expected[1]:
                        raise ValueError(
                            f"bundle archive member does not match the manifest: {name}",
                        )
                    expected_size = expected[1]
                    padding_size = (-member.size) % tarfile.BLOCKSIZE
                    if padding_size:
                        padding_extents.append(
                            (member.offset_data + member.size, padding_size),
                        )
                    extracted = archive.extractfile(member)
                    if extracted is None or self._hash_bounded(extracted, member.size) != expected:
                        raise ValueError(
                            f"bundle archive member does not match the manifest: {name}",
                        )
                expected_header = self._codec.canonical_tar_info(
                    name,
                    is_directory=member.isdir(),
                    mode=self._expected_modes[name],
                    size=expected_size,
                    modified_time=self._expected_modified_time,
                ).tobuf(format=tarfile.PAX_FORMAT)
                header_spans.append(
                    (member.offset, member.offset_data, expected_header),
                )
            logical_end = archive.offset
            self._codec.validate_tar_headers(
                archive.fileobj,
                header_spans,
            )
            self._codec.validate_tar_member_padding(
                archive.fileobj,
                padding_extents,
            )
        if timestamps != {self._expected_modified_time}:
            raise ValueError(
                "bundle archive members have noncanonical timestamps",
            )
        self._codec.validate_tar_end(
            physical,
            logical_end,
            self._expected_modified_time,
        )
        self._validate_names(names)

    def _validate_zip(self, stream: BinaryIO) -> None:
        expected_timestamp = self._codec.canonical_zip_timestamp(
            self._expected_modified_time,
        )
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if len(entries) != len(self._expected_modes):
                raise ValueError(
                    "bundle archive member set does not match the manifest",
                )
            names = []
            timestamps = set()
            for entry in entries:
                mode = entry.external_attr >> 16
                is_directory = entry.is_dir()
                expected_type = stat.S_IFDIR if is_directory else stat.S_IFREG
                if stat.S_IFMT(mode) != expected_type:
                    raise ValueError(
                        f"bundle archive contains a special member: {entry.filename}",
                    )
                name = self._canonical_member(
                    entry.filename,
                    is_directory,
                )
                names.append(name)
                timestamps.add(entry.date_time)
                if stat.S_IMODE(mode) != self._expected_modes.get(name):
                    raise ValueError(
                        f"bundle archive member has a noncanonical mode: {name}",
                    )
                if is_directory:
                    continue
                expected = self._expected_files.get(name)
                if expected is None or entry.file_size != expected[1]:
                    raise ValueError(
                        f"bundle archive member does not match the manifest: {name}",
                    )
                with archive.open(entry) as member:
                    if self._hash_bounded(member, entry.file_size) != expected:
                        raise ValueError(
                            f"bundle archive member does not match the manifest: {name}",
                        )
            if timestamps != {expected_timestamp}:
                raise ValueError(
                    "bundle archive members have noncanonical timestamps",
                )
            self._codec.validate_zip_layout(
                stream,
                archive,
                entries,
                self._expected_modes,
                expected_timestamp,
            )
        self._validate_names(names)

    @staticmethod
    def _safe_relative(path: str) -> bool:
        parsed = PurePosixPath(path)
        return (
            bool(path)
            and "\\" not in path
            and not parsed.is_absolute()
            and path == parsed.as_posix()
            and all(part not in {"", ".", ".."} for part in parsed.parts)
        )

    def _canonical_member(self, name: str, is_directory: bool) -> str:
        bare = name[:-1] if name.endswith("/") else name
        if not self._safe_relative(bare):
            raise ValueError(
                f"bundle archive contains an unsafe member: {name}",
            )
        return f"{bare}/" if is_directory else bare

    @staticmethod
    def _hash_bounded(
        stream: BinaryIO,
        size: int,
    ) -> ContentSnapshot:
        digest = hashlib.sha256()
        remaining = size
        while remaining:
            chunk = stream.read(min(_CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError(
                    "bundle archive member ended before its declared size",
                )
            digest.update(chunk)
            remaining -= len(chunk)
        if stream.read(1):
            raise ValueError(
                "bundle archive member exceeds its declared size",
            )
        return digest.digest(), size

    def _validate_names(self, names: list[str]) -> None:
        expected = sorted(
            set(self._expected_files) | self._expected_directories,
        )
        if names != expected:
            raise ValueError(
                "bundle archive member set does not match the manifest",
            )


class InvalidBinary(ValueError):
    """The stream is not a structurally complete supported executable."""


class _BoundedReader:
    """Own monotonic, size-bounded access to one executable stream."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.offset = 0

    def read_exact(self, size: int) -> bytes:
        if size < 0 or self.offset + size > _MAX_BINARY_BYTES:
            raise InvalidBinary
        payload = bytearray()
        while len(payload) < size:
            chunk = self.stream.read(size - len(payload))
            if not chunk:
                raise InvalidBinary
            payload.extend(chunk)
        self.offset += size
        return bytes(payload)

    def skip_to(self, offset: int) -> None:
        if offset < self.offset or offset > _MAX_HEADER_REGION:
            raise InvalidBinary
        remaining = offset - self.offset
        while remaining:
            chunk = self.read_exact(min(_CHUNK_SIZE, remaining))
            remaining -= len(chunk)

    def finish(self) -> int:
        while True:
            remaining = _MAX_BINARY_BYTES - self.offset
            chunk = self.stream.read(min(_CHUNK_SIZE, remaining + 1))
            if not chunk:
                return self.offset
            self.offset += len(chunk)
            if self.offset > _MAX_BINARY_BYTES:
                raise InvalidBinary


class ExecutableFormatInspector:
    """Own structural format detection for one complete binary stream."""

    def __init__(self, stream: BinaryIO) -> None:
        self._reader = _BoundedReader(stream)

    def machine(self, binary_format: str) -> int | None:
        """Return the machine id only for a complete supported executable."""

        try:
            if binary_format == "elf":
                machine = self._elf64_machine()
            elif binary_format == "mach-o":
                machine = self._mach_o64_machine()
            elif binary_format == "pe":
                machine = self._pe32_plus_machine()
            else:
                raise InvalidBinary
        except InvalidBinary:
            machine = None
        try:
            self._reader.finish()
        except InvalidBinary:
            machine = None
        return machine

    @staticmethod
    def _bounded_extent(offset: int, size: int, total: int) -> bool:
        return 0 <= offset <= total and 0 <= size <= total - offset

    @staticmethod
    def _bounded_address_extent(
        offset: int,
        size: int,
        limit: int = _UINT64_MAX,
    ) -> bool:
        """Return whether adding ``size`` to ``offset`` stays representable."""

        return 0 <= offset <= limit and 0 <= size <= limit - offset

    @staticmethod
    def _contains(offset: int, size: int, point: int) -> bool:
        """Return whether ``point`` lies in a non-empty extent."""

        return size > 0 and offset <= point and point - offset < size

    def _elf64_machine(self) -> int:
        reader = self._reader
        header = reader.read_exact(_ELF_HEADER_SIZE)
        values = struct.unpack("<16sHHIQQQIHHHHHH", header)
        ident, kind, machine, version, entry, program_offset, section_offset = values[:7]
        header_size, program_size, program_count, section_size, section_count = values[8:13]
        if (
            ident[:7] != b"\x7fELF\x02\x01\x01"
            or kind not in {2, 3}
            or version != 1
            or entry == 0
            or header_size != _ELF_HEADER_SIZE
            or program_size != _ELF_PROGRAM_HEADER_SIZE
            or not 0 < program_count <= 4096
        ):
            raise InvalidBinary
        program_end = program_offset + program_size * program_count
        if program_offset < _ELF_HEADER_SIZE or program_end > _MAX_HEADER_REGION:
            raise InvalidBinary
        if section_count:
            section_end = section_offset + section_size * section_count
            if section_size != 64 or section_offset < _ELF_HEADER_SIZE or section_end > _MAX_BINARY_BYTES:
                raise InvalidBinary
        elif section_offset or section_size:
            raise InvalidBinary
        reader.skip_to(program_offset)
        file_extents: list[tuple[int, int]] = []
        executable_entry = False
        for _ in range(program_count):
            fields = struct.unpack(
                "<IIQQQQQQ",
                reader.read_exact(program_size),
            )
            (
                segment_kind,
                flags,
                file_offset,
                virtual_address,
                _,
                file_size,
                memory_size,
                _,
            ) = fields
            file_extents.append((file_offset, file_size))
            if segment_kind == 1:
                if file_size > memory_size or not self._bounded_address_extent(
                    virtual_address,
                    memory_size,
                ):
                    raise InvalidBinary
                if flags & 1 and self._contains(
                    virtual_address,
                    file_size,
                    entry,
                ):
                    executable_entry = True
        total = reader.finish()
        if not executable_entry or not all(self._bounded_extent(*extent, total) for extent in file_extents):
            raise InvalidBinary
        if section_count and not self._bounded_extent(
            section_offset,
            section_size * section_count,
            total,
        ):
            raise InvalidBinary
        return machine

    def _mach_o64_machine(self) -> int:
        reader = self._reader
        header = reader.read_exact(_MACH_HEADER_SIZE)
        (
            magic,
            machine,
            _,
            kind,
            command_count,
            command_bytes,
            _,
            reserved,
        ) = struct.unpack("<IIIIIIII", header)
        if (
            magic != 0xFEEDFACF
            or kind != 2
            or reserved != 0
            or not 0 < command_count <= 4096
            or command_bytes < command_count * 8
            or _MACH_HEADER_SIZE + command_bytes > _MAX_HEADER_REGION
        ):
            raise InvalidBinary
        commands = reader.read_exact(command_bytes)
        cursor = 0
        file_extents: list[tuple[int, int]] = []
        executable_extents: list[tuple[int, int]] = []
        main_entry: int | None = None
        for _ in range(command_count):
            if cursor + 8 > len(commands):
                raise InvalidBinary
            command, size = struct.unpack_from("<II", commands, cursor)
            if size < 8 or size % 8 or cursor + size > len(commands):
                raise InvalidBinary
            if command == 0x19:
                if size < 72:
                    raise InvalidBinary
                (
                    virtual_address,
                    virtual_size,
                    file_offset,
                    file_size,
                ) = struct.unpack_from("<QQQQ", commands, cursor + 24)
                _, initial_protection, section_count = struct.unpack_from(
                    "<III",
                    commands,
                    cursor + 56,
                )
                if (
                    size != 72 + section_count * 80
                    or file_size > virtual_size
                    or not self._bounded_address_extent(
                        virtual_address,
                        virtual_size,
                    )
                ):
                    raise InvalidBinary
                file_extents.append((file_offset, file_size))
                if initial_protection & 4:
                    if not virtual_size or not file_size:
                        raise InvalidBinary
                    executable_extents.append((file_offset, file_size))
            elif command == 0x80000028:
                if size != 24:
                    raise InvalidBinary
                main_entry = struct.unpack_from(
                    "<Q",
                    commands,
                    cursor + 8,
                )[0]
                file_extents.append((main_entry, 1))
            cursor += size
        total = reader.finish()
        if (
            cursor != len(commands)
            or not executable_extents
            or not main_entry
            or not any(self._contains(offset, size, main_entry) for offset, size in executable_extents)
            or not all(self._bounded_extent(*extent, total) for extent in file_extents)
        ):
            raise InvalidBinary
        return machine

    def _pe32_plus_machine(self) -> int:
        reader = self._reader
        dos_header = reader.read_exact(64)
        pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
        if dos_header[:2] != b"MZ" or pe_offset < 64 or pe_offset > 1024 * 1024 or pe_offset % 4:
            raise InvalidBinary
        reader.skip_to(pe_offset)
        signature_and_coff = reader.read_exact(24)
        (
            machine,
            section_count,
            _,
            symbol_offset,
            symbol_count,
            optional_size,
            characteristics,
        ) = struct.unpack_from("<HHIIIHH", signature_and_coff, 4)
        if (
            signature_and_coff[:4] != b"PE\0\0"
            or not 0 < section_count <= _PE_MAX_SECTIONS
            or optional_size < 112
            or optional_size > 4096
            or not characteristics & 0x0002
            or characteristics & 0x2000
        ):
            raise InvalidBinary
        optional = reader.read_exact(optional_size)
        magic = struct.unpack_from("<H", optional)[0]
        entrypoint = struct.unpack_from("<I", optional, 16)[0]
        image_size, header_size = struct.unpack_from("<II", optional, 56)
        subsystem = struct.unpack_from("<H", optional, 68)[0]
        directory_count = struct.unpack_from("<I", optional, 108)[0]
        if (
            magic != 0x20B
            or not entrypoint
            or not image_size
            or subsystem != 3
            or 112 + directory_count * 8 > optional_size
        ):
            raise InvalidBinary
        section_table_end = reader.offset + section_count * 40
        if section_table_end > _MAX_HEADER_REGION or header_size < section_table_end:
            raise InvalidBinary
        file_extents: list[tuple[int, int]] = []
        executable_entry = False
        for _ in range(section_count):
            section = reader.read_exact(40)
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                "<IIII",
                section,
                8,
            )
            section_flags = struct.unpack_from("<I", section, 36)[0]
            file_extents.append((raw_offset, raw_size))
            mapped_size = max(virtual_size, raw_size)
            if (
                not self._bounded_address_extent(
                    virtual_address,
                    mapped_size,
                    _UINT32_MAX,
                )
                or virtual_address > image_size
                or mapped_size > image_size - virtual_address
            ):
                raise InvalidBinary
            if section_flags & 0x20000000 and self._contains(
                virtual_address,
                raw_size,
                entrypoint,
            ):
                executable_entry = True
        total = reader.finish()
        if (
            not executable_entry
            or header_size > total
            or not all(size == 0 or self._bounded_extent(offset, size, total) for offset, size in file_extents)
            or (
                symbol_count
                and not self._bounded_extent(
                    symbol_offset,
                    symbol_count * 18,
                    total,
                )
            )
        ):
            raise InvalidBinary
        return machine


@dataclass(frozen=True)
class TargetSpec:
    executable: str
    archive_suffix: str
    binary_format: str
    machine: int
    description: str


_DEFAULT_TARGETS = MappingProxyType(
    {
        "linux-x64": TargetSpec(
            "bin/btrcc",
            ".tar.gz",
            "elf",
            62,
            "ELF x86-64",
        ),
        "linux-arm64": TargetSpec(
            "bin/btrcc",
            ".tar.gz",
            "elf",
            183,
            "ELF AArch64",
        ),
        "macos-x64": TargetSpec(
            "bin/btrcc",
            ".tar.gz",
            "mach-o",
            0x01000007,
            "Mach-O x86_64",
        ),
        "macos-arm64": TargetSpec(
            "bin/btrcc",
            ".tar.gz",
            "mach-o",
            0x0100000C,
            "Mach-O arm64",
        ),
        "windows-x64": TargetSpec(
            "bin/btrcc.exe",
            ".zip",
            "pe",
            0x8664,
            "PE x86-64",
        ),
    },
)

_DEFAULT_HOST_TARGETS = MappingProxyType(
    {
        ("darwin", "arm64"): "macos-arm64",
        ("darwin", "x86_64"): "macos-x64",
        ("linux", "aarch64"): "linux-arm64",
        ("linux", "x86_64"): "linux-x64",
        ("windows", "amd64"): "windows-x64",
        ("windows", "x86_64"): "windows-x64",
    },
)


class TargetCatalog:
    """Own immutable release-target and native-host mappings."""

    def __init__(
        self,
        targets: Mapping[str, TargetSpec] | None = None,
        host_targets: Mapping[tuple[str, str], str] | None = None,
    ) -> None:
        self._targets = MappingProxyType(
            dict(_DEFAULT_TARGETS if targets is None else targets),
        )
        self._host_targets = MappingProxyType(
            dict(
                _DEFAULT_HOST_TARGETS if host_targets is None else host_targets,
            ),
        )

    def spec(self, target: str) -> TargetSpec:
        try:
            return self._targets[target]
        except KeyError as error:
            raise ValueError(
                f"unsupported bundle target: {target!r}",
            ) from error

    def host_target(self) -> str:
        """Return the release target matching the native Python process."""

        host = platform.system().lower(), platform.machine().lower()
        try:
            return self._host_targets[host]
        except KeyError as error:
            raise ValueError(
                f"unsupported bundle host: {host[0]} {host[1]}",
            ) from error


class TargetBinaryValidator:
    """Own native-format validation for release-target binaries."""

    def __init__(
        self,
        catalog: TargetCatalog | None = None,
        storage: ArtifactStorage | None = None,
    ) -> None:
        self._catalog = catalog if catalog is not None else TargetCatalog()
        self._storage = storage if storage is not None else ArtifactStorage()

    def validate_stream(self, stream: BinaryIO, target: str) -> None:
        """Validate one complete binary stream against its release target."""

        spec = self._catalog.spec(target)
        try:
            machine = ExecutableFormatInspector(stream).machine(
                spec.binary_format,
            )
        except OSError as error:
            raise ValueError(
                f"cannot inspect compiler binary for {target}: {error}",
            ) from error
        self._validate_machine(machine, target, spec)

    def validate_path(self, path: Path, target: str) -> None:
        """Reject a file whose format or machine conflicts with ``target``."""

        spec = self._catalog.spec(target)
        descriptor = -1
        try:
            descriptor = self._storage.open_regular(path)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                machine = ExecutableFormatInspector(stream).machine(
                    spec.binary_format,
                )
        except OSError as error:
            raise ValueError(
                f"cannot inspect compiler binary for {target}: {path}: {error}",
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        self._validate_machine(machine, target, spec)

    @staticmethod
    def _validate_machine(
        machine: int | None,
        target: str,
        spec: TargetSpec,
    ) -> None:
        if machine != spec.machine:
            raise ValueError(
                f"compiler binary does not match target {target!r}: expected {spec.description}",
            )
