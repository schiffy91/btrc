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


def _safe_relative(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        bool(path)
        and "\\" not in path
        and not parsed.is_absolute()
        and path == parsed.as_posix()
        and all(part not in {"", ".", ".."} for part in parsed.parts)
    )


def _canonical_member(name: str, is_directory: bool) -> str:
    bare = name[:-1] if name.endswith("/") else name
    if not _safe_relative(bare):
        raise ValueError(f"bundle archive contains an unsafe member: {name}")
    return f"{bare}/" if is_directory else bare


def _hash_bounded(stream: BinaryIO, size: int) -> ContentSnapshot:
    digest = hashlib.sha256()
    remaining = size
    while remaining:
        chunk = stream.read(min(_CHUNK_SIZE, remaining))
        if not chunk:
            raise ValueError("bundle archive member ended before its declared size")
        digest.update(chunk)
        remaining -= len(chunk)
    if stream.read(1):
        raise ValueError("bundle archive member exceeds its declared size")
    return digest.digest(), size


def _validate_names(names: list[str], expected_files: dict[str, ContentSnapshot], expected_dirs: set[str]) -> None:
    expected = sorted(set(expected_files) | expected_dirs)
    if names != expected:
        raise ValueError("bundle archive member set does not match the manifest")


def _validate_tar(
    stream: BinaryIO,
    expected_files: dict[str, ContentSnapshot],
    expected_dirs: set[str],
    expected_modes: dict[str, int],
    expected_modified_time: int,
) -> None:
    physical = btrcc_archive_layout.validate_gzip_layout(stream)
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode="r:gz") as archive:
        members = []
        for member in archive:
            members.append(member)
            if len(members) > len(expected_modes):
                raise ValueError("bundle archive has unexpected or duplicate members")
        names = []
        timestamps = set()
        padding_extents = []
        header_spans = []
        for member in members:
            if member.type not in {tarfile.REGTYPE, tarfile.DIRTYPE}:
                raise ValueError(f"bundle archive contains a special member: {member.name}")
            name = _canonical_member(member.name, member.isdir())
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
                raise ValueError(f"bundle archive member has noncanonical metadata: {name}")
            if member.mode != expected_modes.get(name):
                raise ValueError(f"bundle archive member has a noncanonical mode: {name}")
            if member.isdir():
                expected_size = 0
            else:
                expected = expected_files.get(name)
                if expected is None or member.size != expected[1]:
                    raise ValueError(f"bundle archive member does not match the manifest: {name}")
                expected_size = expected[1]
                padding_size = (-member.size) % tarfile.BLOCKSIZE
                if padding_size:
                    padding_extents.append((member.offset_data + member.size, padding_size))
                extracted = archive.extractfile(member)
                if extracted is None or _hash_bounded(extracted, member.size) != expected:
                    raise ValueError(f"bundle archive member does not match the manifest: {name}")
            expected_header = canonical_tar_info(
                name,
                is_directory=member.isdir(),
                mode=expected_modes[name],
                size=expected_size,
                modified_time=expected_modified_time,
            ).tobuf(format=tarfile.PAX_FORMAT)
            header_spans.append((member.offset, member.offset_data, expected_header))
        logical_end = archive.offset
        btrcc_archive_layout.validate_tar_headers(
            archive.fileobj,
            header_spans,
        )
        btrcc_archive_layout.validate_tar_member_padding(
            archive.fileobj,
            padding_extents,
        )
    if timestamps != {expected_modified_time}:
        raise ValueError("bundle archive members have noncanonical timestamps")
    btrcc_archive_layout.validate_tar_end(
        physical,
        logical_end,
        expected_modified_time,
    )
    _validate_names(names, expected_files, expected_dirs)


def _validate_zip(
    stream: BinaryIO,
    expected_files: dict[str, ContentSnapshot],
    expected_dirs: set[str],
    expected_modes: dict[str, int],
    expected_modified_time: int,
) -> None:
    expected_timestamp = canonical_zip_timestamp(expected_modified_time)
    with zipfile.ZipFile(stream) as archive:
        entries = archive.infolist()
        if len(entries) != len(expected_modes):
            raise ValueError("bundle archive member set does not match the manifest")
        names = []
        timestamps = set()
        for entry in entries:
            mode = entry.external_attr >> 16
            is_directory = entry.is_dir()
            expected_type = stat.S_IFDIR if is_directory else stat.S_IFREG
            if stat.S_IFMT(mode) != expected_type:
                raise ValueError(f"bundle archive contains a special member: {entry.filename}")
            name = _canonical_member(entry.filename, is_directory)
            names.append(name)
            timestamps.add(entry.date_time)
            if stat.S_IMODE(mode) != expected_modes.get(name):
                raise ValueError(f"bundle archive member has a noncanonical mode: {name}")
            if is_directory:
                continue
            expected = expected_files.get(name)
            if expected is None or entry.file_size != expected[1]:
                raise ValueError(f"bundle archive member does not match the manifest: {name}")
            with archive.open(entry) as member:
                if _hash_bounded(member, entry.file_size) != expected:
                    raise ValueError(f"bundle archive member does not match the manifest: {name}")
        if timestamps != {expected_timestamp}:
            raise ValueError("bundle archive members have noncanonical timestamps")
        btrcc_archive_layout.validate_zip_layout(
            stream,
            archive,
            entries,
            expected_modes,
            expected_timestamp,
        )
    _validate_names(names, expected_files, expected_dirs)


def validate_archive(
    stream: BinaryIO,
    archive_name: str,
    expected_files: dict[str, ContentSnapshot],
    expected_dirs: set[str],
    expected_modes: dict[str, int],
    expected_modified_time: int,
) -> None:
    try:
        if archive_name.endswith(".zip"):
            _validate_zip(
                stream,
                expected_files,
                expected_dirs,
                expected_modes,
                expected_modified_time,
            )
        elif archive_name.endswith(".tar.gz"):
            _validate_tar(
                stream,
                expected_files,
                expected_dirs,
                expected_modes,
                expected_modified_time,
            )
        else:
            raise ValueError(f"unsupported bundle archive format: {archive_name}")
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError) as error:
        raise ValueError("bundle archive is not a valid tar or ZIP file") from error
