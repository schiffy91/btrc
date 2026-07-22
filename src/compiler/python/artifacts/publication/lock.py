"""Exclusive cross-process locks for artifact publishers."""

from __future__ import annotations

import os
import re
import stat
import threading
from pathlib import Path
from types import TracebackType

from .storage import ArtifactStorage

_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PublicationLock:
    """Own one no-follow writer lock from acquisition through release."""

    def __init__(
        self,
        directory: Path,
        name: str,
        process_lock: threading.Lock,
        storage: ArtifactStorage | None = None,
    ) -> None:
        self._directory = directory
        self._name = name
        self._process_lock = process_lock
        self._storage = storage or ArtifactStorage()
        self._descriptor = -1
        self._locked = False
        self._process_lock_held = False

    def __enter__(self) -> PublicationLock:
        if not _NAME_PATTERN.fullmatch(self._name):
            raise ValueError(f"invalid publication name: {self._name!r}")
        self._directory.mkdir(parents=True, exist_ok=True)
        self._storage.require_real_directory(
            self._directory,
            "publication output directory",
        )
        path = self._directory / f".{self._name}.publish.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        self._process_lock.acquire()
        self._process_lock_held = True
        try:
            self._descriptor = os.open(path, flags, 0o600)
            opened = os.fstat(self._descriptor)
            current = path.lstat()
            if (
                not stat.S_ISREG(opened.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or self._storage.metadata_is_reparse_point(current)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise ValueError(f"publication lock is not a stable regular file: {path}")
            self._lock_descriptor()
            self._locked = True
            return self
        except BaseException:
            if self._descriptor >= 0:
                os.close(self._descriptor)
                self._descriptor = -1
            self._release_process_lock()
            raise

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            if self._locked:
                self._unlock_descriptor()
                self._locked = False
            if self._descriptor >= 0:
                os.close(self._descriptor)
                self._descriptor = -1
        finally:
            self._release_process_lock()

    def _lock_descriptor(self) -> None:
        if os.name == "nt":
            import msvcrt

            if os.fstat(self._descriptor).st_size == 0:
                os.write(self._descriptor, b"\0")
            os.lseek(self._descriptor, 0, os.SEEK_SET)
            msvcrt.locking(self._descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self._descriptor, fcntl.LOCK_EX)

    def _unlock_descriptor(self) -> None:
        if os.name == "nt":
            import msvcrt

            os.lseek(self._descriptor, 0, os.SEEK_SET)
            msvcrt.locking(self._descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._descriptor, fcntl.LOCK_UN)

    def _release_process_lock(self) -> None:
        if self._process_lock_held:
            self._process_lock.release()
            self._process_lock_held = False
