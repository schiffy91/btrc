"""No-reparse filesystem boundaries for published artifact trees."""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

PathMetadata = tuple[Path, os.stat_result]


class ReparsePointError(ValueError):
    """A path would escape the real directory tree being validated."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"filesystem tree must not contain a link or reparse point: {path}")
        self.path = path


def metadata_is_reparse_point(metadata: os.stat_result) -> bool:
    """Recognize POSIX symlinks and Windows directory/file reparse points."""

    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_reparse_tag", 0),
    )


def require_real_directory(path: Path, subject: str) -> os.stat_result:
    """Return metadata only for a concrete, non-reparse directory."""

    metadata = path.lstat()
    if metadata_is_reparse_point(metadata) or not stat.S_ISDIR(metadata.st_mode):
        raise ValueError(f"{subject} must be a real directory: {path}")
    return metadata


def require_real_regular(path: Path, subject: str) -> os.stat_result:
    """Return metadata only for a concrete, non-reparse regular file."""

    metadata = path.lstat()
    if metadata_is_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError(f"{subject} must be a real regular file: {path}")
    return metadata


def _identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _validate_directory_identity(
    path: Path,
    expected: os.stat_result,
) -> None:
    current = require_real_directory(path, "filesystem tree directory")
    if _identity(current) != _identity(expected):
        raise ValueError(f"filesystem tree directory changed while being traversed: {path}")


def real_tree_entries(
    root: Path,
    *,
    exclude: Callable[[Path], bool] | None = None,
) -> list[PathMetadata]:
    """Enumerate a stable tree without following any link or reparse entry."""

    root_metadata = require_real_directory(root, "filesystem tree root")
    discovered: list[PathMetadata] = [(root, root_metadata)]
    pending = [(root, root_metadata)]
    while pending:
        directory, expected = pending.pop()
        _validate_directory_identity(directory, expected)
        children: list[PathMetadata] = []
        with os.scandir(directory) as entries:
            for entry in entries:
                path = directory / entry.name
                if exclude is not None and exclude(path):
                    continue
                metadata = entry.stat(follow_symlinks=False)
                if metadata_is_reparse_point(metadata):
                    raise ReparsePointError(path)
                children.append((path, metadata))
        _validate_directory_identity(directory, expected)
        discovered.extend(children)
        pending.extend((path, metadata) for path, metadata in children if stat.S_ISDIR(metadata.st_mode))
    return sorted(discovered, key=lambda entry: entry[0].as_posix())


__all__ = [
    "PathMetadata",
    "ReparsePointError",
    "metadata_is_reparse_point",
    "real_tree_entries",
    "require_real_directory",
    "require_real_regular",
]
