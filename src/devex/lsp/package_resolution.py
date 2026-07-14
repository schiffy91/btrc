"""Per-workspace, invalidation-safe package resolution for LSP composition."""

from __future__ import annotations

import hashlib
import os
import threading

from src.compiler.python import pkg


class PackageResolver:
    """Cache package maps by manifest/lock content without global state."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[tuple, dict[str, dict]]] = {}
        self._manifest_locks: dict[str, threading.Lock] = {}
        self._lock = threading.RLock()

    def packages_for(self, input_path: str) -> dict[str, dict]:
        manifest = pkg.find_manifest(os.path.dirname(os.path.abspath(input_path)))
        if manifest is None:
            return {}
        key = os.path.normcase(os.path.realpath(manifest))
        manifest_lock = self._manifest_lock(key)
        with manifest_lock:
            fingerprint = _fingerprint(manifest)
            with self._lock:
                cached = self._entries.get(key)
                if cached is not None and cached[0] == fingerprint:
                    return cached[1]

            packages = pkg.packages_for(input_path)
            # Resolution may create or atomically migrate btrc.lock, so cache
            # against the post-resolution bytes rather than the initial state.
            fingerprint = _fingerprint(manifest)
            with self._lock:
                self._entries[key] = (fingerprint, packages)
            return packages

    def _manifest_lock(self, key: str) -> threading.Lock:
        with self._lock:
            lock = self._manifest_locks.get(key)
            if lock is None:
                lock = self._manifest_locks[key] = threading.Lock()
            return lock


def _fingerprint(manifest: str) -> tuple:
    lock_path = os.path.join(os.path.dirname(manifest), "btrc.lock")
    return (
        _file_digest(manifest),
        _file_digest(lock_path),
        os.environ.get("BTRC_PKG_CACHE"),
    )


def _file_digest(path: str) -> str | None:
    try:
        with open(path, "rb") as source_file:
            return hashlib.sha256(source_file.read()).hexdigest()
    except OSError:
        return None
