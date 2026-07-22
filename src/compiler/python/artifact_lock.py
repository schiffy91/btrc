"""Exclusive cross-process locks for artifact publishers."""

from __future__ import annotations

import os
import re
import stat
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import artifact_paths as _paths

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PROCESS_LOCK = threading.Lock()


def _lock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        if os.fstat(descriptor).st_size == 0:
            os.write(descriptor, b"\0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX)


def _unlock_descriptor(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def publication_lock(directory: Path, name: str) -> Iterator[None]:
    """Hold the no-follow writer lock for one artifact set."""

    if not _NAME_PATTERN.fullmatch(name):
        raise ValueError(f"invalid publication name: {name!r}")
    directory.mkdir(parents=True, exist_ok=True)
    _paths.require_real_directory(directory, "publication output directory")
    path = directory / f".{name}.publish.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    with _PROCESS_LOCK:
        descriptor = os.open(path, flags, 0o600)
        locked = False
        try:
            opened = os.fstat(descriptor)
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or _paths.metadata_is_reparse_point(current)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise ValueError(f"publication lock is not a stable regular file: {path}")
            _lock_descriptor(descriptor)
            locked = True
            yield
        finally:
            if locked:
                _unlock_descriptor(descriptor)
            os.close(descriptor)
