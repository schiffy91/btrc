"""No-follow validation and durability barriers for published artifacts."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from . import artifact_paths as _paths


def lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def remove_path(path: Path) -> None:
    metadata = lstat_or_none(path)
    if metadata is None:
        return
    if _paths.metadata_is_reparse_point(metadata):
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            path.unlink()
        else:
            os.rmdir(path)
    elif stat.S_ISDIR(metadata.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def fsync_directory(directory: Path) -> None:
    expected = _paths.require_real_directory(directory, "publication directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        if os.name == "nt":
            return
        raise
    try:
        opened = os.fstat(descriptor)
        current = _paths.require_real_directory(directory, "publication directory")
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not os.path.samestat(expected, opened)
            or not os.path.samestat(opened, current)
        ):
            raise ValueError(f"publication directory is not stable: {directory}")
        try:
            os.fsync(descriptor)
        except OSError:
            if os.name != "nt":
                raise
    finally:
        os.close(descriptor)


def open_regular(path: Path) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        current = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or _paths.metadata_is_reparse_point(current)
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise ValueError(f"publication artifact is not a stable regular file: {path}")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def fsync_artifact(path: Path, is_directory: bool) -> None:
    """Validate an artifact recursively and force its bytes to storage."""

    if not is_directory:
        descriptor = open_regular(path)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return
    entries = _paths.real_tree_entries(path)
    directories = []
    for child, child_metadata in entries:
        if stat.S_ISDIR(child_metadata.st_mode):
            directories.append(child)
        elif stat.S_ISREG(child_metadata.st_mode):
            descriptor = open_regular(child)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        else:
            raise ValueError(f"publication artifact contains a special file: {child}")
    for child in reversed(directories):
        fsync_directory(child)


def validate_artifact(path: Path, is_directory: bool) -> None:
    metadata = lstat_or_none(path)
    if metadata is None:
        raise ValueError(f"publication artifact is missing: {path}")
    expected = stat.S_ISDIR(metadata.st_mode) if is_directory else stat.S_ISREG(metadata.st_mode)
    if _paths.metadata_is_reparse_point(metadata) or not expected:
        kind = "directory" if is_directory else "regular file"
        raise ValueError(f"publication artifact must be a real {kind}: {path}")


def destination_exists(path: Path, is_directory: bool) -> bool:
    """Return whether a destination is a stable prior artifact to preserve.

    A file-destination symlink is only a replaceable directory entry. It is
    never followed or treated as a rollback backup.
    """

    metadata = lstat_or_none(path)
    if metadata is None:
        return False
    if _paths.metadata_is_reparse_point(metadata):
        if stat.S_ISLNK(metadata.st_mode) and not is_directory:
            return False
        raise ValueError(f"invalid publication destination: {path}")
    expected = stat.S_ISDIR(metadata.st_mode) if is_directory else stat.S_ISREG(metadata.st_mode)
    if not expected:
        raise ValueError(f"invalid publication destination: {path}")
    if not is_directory:
        descriptor = open_regular(path)
        os.close(descriptor)
    return True
