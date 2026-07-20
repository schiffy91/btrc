"""Per-workspace, invalidation-safe package resolution for LSP composition."""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from weakref import WeakValueDictionary

from src.compiler.python import pkg
from src.compiler.python.cache_io import open_regular_binary
from src.compiler.python.manifest_io import MAX_MANIFEST_BYTES


class PackageResolver:
    """Cache package maps by manifest/lock content without global state."""

    _ENTRY_CACHE_MAX = 256
    _STABLE_RESOLUTION_ATTEMPTS = 3

    def __init__(self) -> None:
        self._entries: OrderedDict[str, tuple[tuple, dict[str, dict]]] = OrderedDict()
        self._manifest_locks: WeakValueDictionary[str, threading.Lock] = WeakValueDictionary()
        self._lock = threading.RLock()

    def packages_for(self, input_path: str) -> dict[str, dict]:
        manifest = pkg.find_manifest(os.path.dirname(os.path.abspath(input_path)))
        if manifest is None:
            return {}
        key = os.path.normcase(os.path.realpath(manifest))
        manifest_lock = self._manifest_lock(key)
        with manifest_lock:
            for _attempt in range(self._STABLE_RESOLUTION_ATTEMPTS):
                before = _fingerprint(manifest)
                with self._lock:
                    cached = self._entries.get(key)
                    if cached is not None and cached[0] == before:
                        self._entries.move_to_end(key)
                        return cached[1]

                packages = pkg.packages_for(input_path)
                after = _fingerprint(manifest)
                # Resolution can create/migrate btrc.lock. Resolve once more
                # against those published bytes instead of associating a map
                # from the old inputs with the new fingerprint. The same retry
                # closes the editor-save race for btrc.toml and btrc.lock.
                if before != after:
                    continue
                with self._lock:
                    self._entries[key] = (after, packages)
                    self._entries.move_to_end(key)
                    while len(self._entries) > self._ENTRY_CACHE_MAX:
                        self._entries.popitem(last=False)
                return packages
        raise pkg.IncludeResolutionError(
            "package resolution failed: btrc.toml or btrc.lock changed "
            "repeatedly during resolution; retry after the save completes"
        )

    def _manifest_lock(self, key: str) -> threading.Lock:
        with self._lock:
            lock = self._manifest_locks.get(key)
            if lock is None:
                lock = self._manifest_locks[key] = threading.Lock()
            return lock


def _fingerprint(manifest: str) -> tuple:
    lock_path = os.path.join(os.path.dirname(manifest), "btrc.lock")
    return (
        _file_digest(manifest, MAX_MANIFEST_BYTES),
        _file_digest(lock_path, pkg.MAX_LOCK_BYTES),
        os.environ.get("BTRC_PKG_CACHE"),
    )


def _file_digest(path: str, max_bytes: int) -> tuple:
    """Fingerprint one bounded package input without trusting its size."""
    try:
        source_file = open_regular_binary(path)
        if source_file is None:
            return ("not-regular",)
        with source_file:
            if os.fstat(source_file.fileno()).st_size > max_bytes:
                return ("too-large",)
            encoded = source_file.read(max_bytes + 1)
    except FileNotFoundError:
        return ("missing",)
    except OSError as error:
        return ("unreadable", error.errno)
    if len(encoded) > max_bytes:
        return ("too-large",)
    return ("sha256", hashlib.sha256(encoded).hexdigest())


def shares_project_manifest(path: str, active_manifest: str | None) -> bool:
    """Whether *path* has the active document's nearest manifest boundary."""
    candidate = pkg.find_manifest(os.path.dirname(os.path.abspath(path)))
    if active_manifest is None or candidate is None:
        return active_manifest is None and candidate is None
    return os.path.normcase(os.path.realpath(candidate)) == os.path.normcase(os.path.realpath(active_manifest))
