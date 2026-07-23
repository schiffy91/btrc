"""Bounded tar/ZIP member validation against one bundle manifest."""

from __future__ import annotations

import hashlib
import stat
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import BinaryIO

from . import btrcc_archive_layout
from .btrcc_archive_metadata import canonical_tar_info, canonical_zip_timestamp
from .bundle_archive_source import ContentSnapshot

_CHUNK_SIZE = 1024 * 1024


class BundleArchiveValidator:
    """Validate one release archive against its immutable bundle contract."""

    def __init__(
        self,
        archive_name: str,
        expected_files: dict[str, ContentSnapshot],
        expected_directories: set[str],
        expected_modes: dict[str, int],
        expected_modified_time: int,
    ) -> None:
        self._archive_name = archive_name
        self._expected_files = dict(expected_files)
        self._expected_directories = set(expected_directories)
        self._expected_modes = dict(expected_modes)
        self._expected_modified_time = expected_modified_time

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
        physical = btrcc_archive_layout.validate_gzip_layout(stream)
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
                expected_header = canonical_tar_info(
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
            btrcc_archive_layout.validate_tar_headers(
                archive.fileobj,
                header_spans,
            )
            btrcc_archive_layout.validate_tar_member_padding(
                archive.fileobj,
                padding_extents,
            )
        if timestamps != {self._expected_modified_time}:
            raise ValueError(
                "bundle archive members have noncanonical timestamps",
            )
        btrcc_archive_layout.validate_tar_end(
            physical,
            logical_end,
            self._expected_modified_time,
        )
        self._validate_names(names)

    def _validate_zip(self, stream: BinaryIO) -> None:
        expected_timestamp = canonical_zip_timestamp(
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
            btrcc_archive_layout.validate_zip_layout(
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
