"""Bounded tar/ZIP member validation against one bundle manifest."""

from __future__ import annotations

import hashlib
import stat
import tarfile
import zipfile
from pathlib import PurePosixPath
from typing import BinaryIO

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
    if len(names) != len(set(names)) or set(names) != set(expected_files) | expected_dirs:
        raise ValueError("bundle archive member set does not match the manifest")


def _validate_tar(
    stream: BinaryIO,
    expected_files: dict[str, ContentSnapshot],
    expected_dirs: set[str],
    expected_modes: dict[str, int],
) -> None:
    with tarfile.open(fileobj=stream, mode="r:gz") as archive:
        members = []
        for member in archive:
            members.append(member)
            if len(members) > len(expected_modes):
                raise ValueError("bundle archive has unexpected or duplicate members")
        names = []
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"bundle archive contains a special member: {member.name}")
            name = _canonical_member(member.name, member.isdir())
            names.append(name)
            if member.mode != expected_modes.get(name):
                raise ValueError(f"bundle archive member has a noncanonical mode: {name}")
            if member.isdir():
                continue
            expected = expected_files.get(name)
            if expected is None or member.size != expected[1]:
                raise ValueError(f"bundle archive member does not match the manifest: {name}")
            extracted = archive.extractfile(member)
            if extracted is None or _hash_bounded(extracted, member.size) != expected:
                raise ValueError(f"bundle archive member does not match the manifest: {name}")
    _validate_names(names, expected_files, expected_dirs)


def _validate_zip(
    stream: BinaryIO,
    expected_files: dict[str, ContentSnapshot],
    expected_dirs: set[str],
    expected_modes: dict[str, int],
) -> None:
    with zipfile.ZipFile(stream) as archive:
        entries = archive.infolist()
        if len(entries) != len(expected_modes):
            raise ValueError("bundle archive member set does not match the manifest")
        names = []
        for entry in entries:
            mode = entry.external_attr >> 16
            is_directory = entry.is_dir()
            expected_type = stat.S_IFDIR if is_directory else stat.S_IFREG
            if stat.S_IFMT(mode) != expected_type:
                raise ValueError(f"bundle archive contains a special member: {entry.filename}")
            name = _canonical_member(entry.filename, is_directory)
            names.append(name)
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
    _validate_names(names, expected_files, expected_dirs)


def validate_archive(
    stream: BinaryIO,
    archive_name: str,
    expected_files: dict[str, ContentSnapshot],
    expected_dirs: set[str],
    expected_modes: dict[str, int],
) -> None:
    try:
        if archive_name.endswith(".zip"):
            _validate_zip(stream, expected_files, expected_dirs, expected_modes)
        elif archive_name.endswith(".tar.gz"):
            _validate_tar(stream, expected_files, expected_dirs, expected_modes)
        else:
            raise ValueError(f"unsupported bundle archive format: {archive_name}")
    except (tarfile.TarError, zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError) as error:
        raise ValueError("bundle archive is not a valid tar or ZIP file") from error
