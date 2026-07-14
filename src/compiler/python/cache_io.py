"""Bounded JSON reads and crash-safe atomic writes for compiler caches."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import suppress

DEFAULT_MAX_JSON_BYTES = 64 * 1024 * 1024


def load_json(
    path: str,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
    *,
    follow_symlinks: bool = False,
):
    """Read bounded strict JSON, returning ``None`` for missing/corrupt data."""
    try:
        cache_file = open_regular_binary(path, follow_symlinks=follow_symlinks)
        if cache_file is None:
            return None
        with cache_file:
            if os.fstat(cache_file.fileno()).st_size > max_bytes:
                return None
            encoded = cache_file.read(max_bytes + 1)
        if len(encoded) > max_bytes:
            return None
        return json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        return None


def open_regular_binary(path: str, *, follow_symlinks: bool = False):
    """Open a regular file without blocking on a substituted FIFO/device.

    Cache callers keep the no-follow default. User-selected manifests and
    archive artifacts may opt into following their final symlink; the opened
    descriptor is still pinned, nonblocking, and validated as a regular file.
    """
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


def atomic_write_json(path: str, payload, *, file_mode: int | None = None) -> None:
    """Serialize deterministic JSON and atomically replace ``path``."""
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    atomic_write_text(path, encoded, file_mode=file_mode)


def atomic_write_text(path: str, content: str, *, file_mode: int | None = None) -> None:
    """Write text durably before an atomic same-directory replacement."""
    cache_dir = os.path.dirname(path) or "."
    os.makedirs(cache_dir, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".btrc-cache-", dir=cache_dir)
    try:
        if file_mode is not None:
            fchmod = getattr(os, "fchmod", None)
            if fchmod is not None:
                fchmod(descriptor, file_mode)
            else:
                os.chmod(temporary_path, file_mode)
        # ``newline="\n"`` disables platform newline translation. Without it,
        # a cache populated on Windows rewrites generated C to CRLF, so a cache
        # hit is no longer byte-identical to a fresh compilation.
        cache_file = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor = -1
        with cache_file:
            cache_file.write(content)
            cache_file.flush()
            os.fsync(cache_file.fileno())
        os.replace(temporary_path, path)
        fsync_parent_directory(path)
    finally:
        if descriptor >= 0:
            with suppress(OSError):
                os.close(descriptor)
        with suppress(FileNotFoundError):
            os.remove(temporary_path)


def fsync_parent_directory(path: str) -> None:
    """Best-effort durability barrier for a published directory entry."""
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


def _reject_json_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")
