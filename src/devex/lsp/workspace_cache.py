"""Bounded, synchronized in-memory caches used by the LSP workspace."""

from __future__ import annotations

import os
import threading
from collections import OrderedDict

from src.devex.lsp.units import FileUnit


class WorkspaceCacheMixin:
    _FILE_CACHE_MAX = 1024
    _SNAPSHOT_CACHE_MAX = 256

    def _init_caches(self) -> None:
        self._file_cache: OrderedDict[str, tuple[tuple, FileUnit]] = OrderedDict()
        self.snapshot_cache: OrderedDict[str, tuple] = OrderedDict()
        self._cache_lock = threading.RLock()

    def _cached_file(self, key: str):
        with self._cache_lock:
            cached = self._file_cache.get(key)
            if cached is not None:
                self._file_cache.move_to_end(key)
            return cached

    def _store_file(self, key: str, signature: tuple, unit: FileUnit) -> None:
        with self._cache_lock:
            self._file_cache[key] = (signature, unit)
            self._file_cache.move_to_end(key)
            while len(self._file_cache) > self._FILE_CACHE_MAX:
                self._file_cache.popitem(last=False)

    def cached_units(self, root: str | None = None) -> list[FileUnit]:
        """Return cached units, optionally constrained to one project tree."""
        with self._cache_lock:
            units = [unit for _signature, unit in self._file_cache.values()]
        if root is None:
            return units
        root_key = path_identity(root)
        return [unit for unit in units if _path_is_within(unit.path, root_key)]

    def get_snapshot(self, path: str):
        key = path_identity(path)
        with self._cache_lock:
            snapshot = self.snapshot_cache.get(key)
            if snapshot is not None:
                self.snapshot_cache.move_to_end(key)
            return snapshot

    def store_snapshot(self, path: str, fingerprint: tuple, result) -> None:
        key = path_identity(path)
        with self._cache_lock:
            self.snapshot_cache[key] = (fingerprint, result)
            self.snapshot_cache.move_to_end(key)
            while len(self.snapshot_cache) > self._SNAPSHOT_CACHE_MAX:
                self.snapshot_cache.popitem(last=False)

    def close_document(self, path: str) -> None:
        key = path_identity(path)
        with self._cache_lock:
            self._file_cache.pop(key, None)
            self.snapshot_cache.pop(key, None)


def path_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _path_is_within(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((path_identity(path), root)) == root
    except ValueError:
        return False
