"""Owned bounded reads and crash-safe atomic writes for compiler files."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import suppress


class AtomicFileStore:
    """Own secure regular-file reads and durable atomic publication."""

    def __init__(self, *, default_max_json_bytes: int = 64 * 1024 * 1024) -> None:
        if default_max_json_bytes <= 0:
            raise ValueError("JSON byte limit must be positive")
        self.default_max_json_bytes = default_max_json_bytes

    def read_json(
        self,
        path: str,
        max_bytes: int | None = None,
        *,
        follow_symlinks: bool = False,
    ):
        """Read bounded strict JSON, returning ``None`` for invalid data."""
        limit = self.default_max_json_bytes if max_bytes is None else max_bytes
        if limit <= 0:
            raise ValueError("JSON byte limit must be positive")
        try:
            cache_file = self.open_regular_binary(
                path,
                follow_symlinks=follow_symlinks,
            )
            if cache_file is None:
                return None
            with cache_file:
                if os.fstat(cache_file.fileno()).st_size > limit:
                    return None
                encoded = cache_file.read(limit + 1)
            if len(encoded) > limit:
                return None
            return json.loads(
                encoded.decode("utf-8"),
                parse_constant=self._reject_json_constant,
            )
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return None

    def open_regular_binary(self, path: str, *, follow_symlinks: bool = False):
        """Open a regular file without blocking on a substituted device."""
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOINHERIT", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if not follow_symlinks:
            flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                descriptor = -1
                return None
            binary_file = os.fdopen(descriptor, "rb")
            descriptor = -1
            return binary_file
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)

    def write_json(self, path: str, payload, *, file_mode: int | None = None) -> None:
        """Serialize deterministic JSON and atomically replace ``path``."""
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.write_text(path, encoded, file_mode=file_mode)

    def write_text(
        self,
        path: str,
        content: str,
        *,
        file_mode: int | None = None,
    ) -> None:
        """Write text durably before an atomic same-directory replacement."""
        cache_dir = os.path.dirname(path) or "."
        os.makedirs(cache_dir, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=".btrc-cache-",
            dir=cache_dir,
        )
        try:
            if file_mode is not None:
                fchmod = getattr(os, "fchmod", None)
                if fchmod is not None:
                    fchmod(descriptor, file_mode)
                else:
                    os.chmod(temporary_path, file_mode)
            cache_file = os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            )
            descriptor = -1
            with cache_file:
                cache_file.write(content)
                cache_file.flush()
                os.fsync(cache_file.fileno())
            os.replace(temporary_path, path)
            self.sync_parent(path)
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
            with suppress(FileNotFoundError):
                os.remove(temporary_path)

    def sync_parent(self, path: str) -> None:
        """Apply a best-effort durability barrier to a directory entry."""
        directory = os.path.dirname(os.path.abspath(path))
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError:
            return
        try:
            with suppress(OSError):
                os.fsync(descriptor)
        finally:
            with suppress(OSError):
                os.close(descriptor)

    @staticmethod
    def _reject_json_constant(value: str):
        raise ValueError(f"invalid JSON constant: {value}")


__all__ = ["AtomicFileStore"]
