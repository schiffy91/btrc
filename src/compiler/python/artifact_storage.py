"""No-follow validation and durability barriers for published artifacts."""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path


def lstat_or_none(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def remove_path(path: Path) -> None:
    metadata = lstat_or_none(path)
    if metadata is None:
        return
    if stat.S_ISDIR(metadata.st_mode) and not stat.S_ISLNK(metadata.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        if os.name == "nt":
            return
        raise
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
    opened = os.fstat(descriptor)
    current = path.lstat()
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
    ):
        os.close(descriptor)
        raise ValueError(f"publication artifact is not a stable regular file: {path}")
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
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"publication artifact is not a real directory: {path}")
    directories = [path]
    for child in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        child_metadata = child.lstat()
        if stat.S_ISLNK(child_metadata.st_mode):
            raise ValueError(f"publication artifact contains a symlink: {child}")
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
    if stat.S_ISLNK(metadata.st_mode) or not expected:
        kind = "directory" if is_directory else "regular file"
        raise ValueError(f"publication artifact must be a real {kind}: {path}")


def destination_exists(path: Path, is_directory: bool) -> bool:
    metadata = lstat_or_none(path)
    if metadata is None:
        return False
    invalid = is_directory and (stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode))
    if invalid or (not is_directory and stat.S_ISDIR(metadata.st_mode)):
        raise ValueError(f"invalid publication destination: {path}")
    return True
