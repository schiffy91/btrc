"""No-follow filesystem access and durability for published artifacts."""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Callable
from pathlib import Path

PathMetadata = tuple[Path, os.stat_result]


class ReparsePointError(ValueError):
    """A path would escape the real directory tree being validated."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"filesystem tree must not contain a link or reparse point: {path}")
        self.path = path


class ArtifactStorage:
    """Own stable, no-follow access to artifact files and directories."""

    def metadata_is_reparse_point(self, metadata: os.stat_result) -> bool:
        """Recognize POSIX symlinks and Windows directory/file reparse points."""

        return stat.S_ISLNK(metadata.st_mode) or bool(
            getattr(metadata, "st_reparse_tag", 0),
        )

    def require_real_directory(self, path: Path, subject: str) -> os.stat_result:
        """Return metadata only for a concrete, non-reparse directory."""

        metadata = path.lstat()
        if self.metadata_is_reparse_point(metadata) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"{subject} must be a real directory: {path}")
        return metadata

    def require_real_regular(self, path: Path, subject: str) -> os.stat_result:
        """Return metadata only for a concrete, non-reparse regular file."""

        metadata = path.lstat()
        if self.metadata_is_reparse_point(metadata) or not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{subject} must be a real regular file: {path}")
        return metadata

    def real_tree_entries(
        self,
        root: Path,
        *,
        exclude: Callable[[Path], bool] | None = None,
    ) -> list[PathMetadata]:
        """Enumerate a stable tree without following any link or reparse entry."""

        root_metadata = self.require_real_directory(root, "filesystem tree root")
        discovered: list[PathMetadata] = [(root, root_metadata)]
        pending = [(root, root_metadata)]
        while pending:
            directory, expected = pending.pop()
            self._validate_directory_identity(directory, expected)
            children: list[PathMetadata] = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = directory / entry.name
                    if exclude is not None and exclude(path):
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    if self.metadata_is_reparse_point(metadata):
                        raise ReparsePointError(path)
                    children.append((path, metadata))
            self._validate_directory_identity(directory, expected)
            discovered.extend(children)
            pending.extend((path, metadata) for path, metadata in children if stat.S_ISDIR(metadata.st_mode))
        return sorted(discovered, key=lambda entry: entry[0].as_posix())

    def lstat_or_none(self, path: Path) -> os.stat_result | None:
        try:
            return path.lstat()
        except FileNotFoundError:
            return None

    def remove(self, path: Path) -> None:
        metadata = self.lstat_or_none(path)
        if metadata is None:
            return
        if self.metadata_is_reparse_point(metadata):
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                path.unlink()
            else:
                os.rmdir(path)
        elif stat.S_ISDIR(metadata.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()

    def fsync_directory(self, directory: Path) -> None:
        expected = self.require_real_directory(directory, "publication directory")
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
            current = self.require_real_directory(directory, "publication directory")
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

    def open_regular(self, path: Path) -> int:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or self.metadata_is_reparse_point(current)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise ValueError(f"publication artifact is not a stable regular file: {path}")
        except BaseException:
            os.close(descriptor)
            raise
        return descriptor

    def fsync_artifact(self, path: Path, is_directory: bool) -> None:
        """Validate an artifact recursively and force its bytes to storage."""

        if not is_directory:
            descriptor = self.open_regular(path)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            return
        entries = self.real_tree_entries(path)
        directories = []
        for child, child_metadata in entries:
            if stat.S_ISDIR(child_metadata.st_mode):
                directories.append(child)
            elif stat.S_ISREG(child_metadata.st_mode):
                descriptor = self.open_regular(child)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
            else:
                raise ValueError(f"publication artifact contains a special file: {child}")
        for child in reversed(directories):
            self.fsync_directory(child)

    def validate_artifact(self, path: Path, is_directory: bool) -> None:
        metadata = self.lstat_or_none(path)
        if metadata is None:
            raise ValueError(f"publication artifact is missing: {path}")
        expected = stat.S_ISDIR(metadata.st_mode) if is_directory else stat.S_ISREG(metadata.st_mode)
        if self.metadata_is_reparse_point(metadata) or not expected:
            kind = "directory" if is_directory else "regular file"
            raise ValueError(f"publication artifact must be a real {kind}: {path}")

    def destination_exists(self, path: Path, is_directory: bool) -> bool:
        """Return whether a destination is a stable prior artifact to preserve.

        A file-destination symlink is only a replaceable directory entry. It is
        never followed or treated as a rollback backup.
        """

        metadata = self.lstat_or_none(path)
        if metadata is None:
            return False
        if self.metadata_is_reparse_point(metadata):
            if stat.S_ISLNK(metadata.st_mode) and not is_directory:
                return False
            raise ValueError(f"invalid publication destination: {path}")
        expected = stat.S_ISDIR(metadata.st_mode) if is_directory else stat.S_ISREG(metadata.st_mode)
        if not expected:
            raise ValueError(f"invalid publication destination: {path}")
        if not is_directory:
            descriptor = self.open_regular(path)
            os.close(descriptor)
        return True

    def _validate_directory_identity(self, path: Path, expected: os.stat_result) -> None:
        current = self.require_real_directory(path, "filesystem tree directory")
        if self._identity(current) != self._identity(expected):
            raise ValueError(f"filesystem tree directory changed while being traversed: {path}")

    def _identity(self, metadata: os.stat_result) -> tuple[int, int, int]:
        return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)
