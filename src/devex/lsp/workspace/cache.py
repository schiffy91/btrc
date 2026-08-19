"""Retained in-memory, unit, and package caches for one LSP workspace."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import OrderedDict
from weakref import WeakValueDictionary

from src.compiler.python.frontend.packages import (
    MAX_LOCK_BYTES,
    IncludeResolutionError,
    PackageFileStore,
    PackageUniverse,
    ResolvedPackages,
)
from src.compiler.python.frontend.sources import FrontendCacheDirectory, SourceDependencyKind
from src.compiler.python.syntax.ast.codec import AstJsonCodec
from src.compiler.python.syntax.ast.generated import PackagePath, QuotedPath, RelativePath, StdGlob, StdModules
from src.devex.lsp.workspace.units import _UNIT_CACHE_VERSION, FileDependencies, FileDependency, FileUnit


class FileUnitCacheCodec:
    """Encode and validate the persistent subset of one parsed file unit."""

    SCHEMA_VERSION = 2
    _IMPORT_SPEC_TYPES = (StdGlob, StdModules, PackagePath, RelativePath, QuotedPath)
    _DEPENDENCY_KINDS = frozenset(kind.value for kind in SourceDependencyKind)

    def __init__(self, ast_codec: AstJsonCodec | None = None) -> None:
        self._ast_codec = ast_codec if ast_codec is not None else AstJsonCodec()

    def encode(self, unit: FileUnit) -> dict:
        return {
            "content_hash": unit.content_hash,
            "decls": [self._ast_codec.encode(declaration) for declaration in unit.decls],
            "dependencies": [
                {
                    "kind": dependency.kind.value,
                    "line": dependency.line,
                    "spec": self._ast_codec.encode(dependency.spec),
                }
                for dependency in unit.dependencies
            ],
            "defined_names": sorted(unit.defined_names),
            "schema": self.SCHEMA_VERSION,
        }

    def decode(self, payload, source_path: str, content_hash: str) -> FileUnit | None:
        if not self._payload_is_valid(payload, content_hash):
            return None
        try:
            declarations = [self._ast_codec.decode(value) for value in payload["decls"]]
            if not all(hasattr(declaration, "source_file") for declaration in declarations):
                return None
            absolute_path = os.path.abspath(source_path)
            for declaration in declarations:
                declaration.source_file = absolute_path
            return FileUnit(
                path=absolute_path,
                source="",
                content_hash=content_hash,
                decls=declarations,
                dependencies=self._decode_dependencies(payload["dependencies"]),
                defined_names=frozenset(payload["defined_names"]),
            )
        except (ValueError, TypeError, RecursionError):
            return None

    @classmethod
    def _payload_is_valid(cls, payload, content_hash: str) -> bool:
        return (
            isinstance(payload, dict)
            and set(payload) == {"content_hash", "decls", "dependencies", "defined_names", "schema"}
            and (payload["schema"] == cls.SCHEMA_VERSION)
            and (payload["content_hash"] == content_hash)
            and isinstance(payload["decls"], list)
            and isinstance(payload["dependencies"], list)
            and all(cls._dependency_is_valid(record) for record in payload["dependencies"])
            and isinstance(payload["defined_names"], list)
            and all(isinstance(name, str) for name in payload["defined_names"])
        )

    @classmethod
    def _dependency_is_valid(cls, record) -> bool:
        return (
            isinstance(record, dict)
            and set(record) == {"kind", "line", "spec"}
            and (record["kind"] in cls._DEPENDENCY_KINDS)
            and isinstance(record["line"], int)
            and (not isinstance(record["line"], bool))
            and (record["line"] > 0)
            and isinstance(record["spec"], dict)
        )

    def _decode_dependencies(self, records: list[dict]) -> FileDependencies:
        dependencies: list[FileDependency] = []
        for record in records:
            spec = self._ast_codec.decode(record["spec"])
            if not isinstance(spec, self._IMPORT_SPEC_TYPES):
                raise ValueError("cached file dependency has an invalid import spec")
            dependencies.append(
                FileDependency(line=record["line"], spec=spec, kind=SourceDependencyKind(record["kind"]))
            )
        return FileDependencies(tuple(dependencies))


class UnitCache:
    """Own one optional persistent unit-cache directory and its lifecycle."""

    _PREFIX = "lspunit-"
    _JSON_SUFFIX = ".json"
    _LEGACY_SUFFIX = ".pkl"
    _MAX_AGE_SECONDS = 30 * 24 * 3600

    def __init__(
        self,
        directory: str | None,
        *,
        unit_version: str = _UNIT_CACHE_VERSION,
        codec: FileUnitCacheCodec | None = None,
        file_store: PackageFileStore | None = None,
    ) -> None:
        self._directory = os.path.abspath(directory) if directory is not None else None
        self._unit_version = unit_version
        self._codec = codec if codec is not None else FileUnitCacheCodec()
        self._file_store = file_store if file_store is not None else PackageFileStore()
        self._pruned = False
        self._prune_lock = threading.Lock()

    @classmethod
    def from_environment(
        cls,
        cache_directory: FrontendCacheDirectory | None = None,
        *,
        codec: FileUnitCacheCodec | None = None,
        file_store: PackageFileStore | None = None,
    ) -> UnitCache:
        """Resolve the shared compiler cache, disabling persistence on failure."""
        try:
            return cls((cache_directory or FrontendCacheDirectory()).resolve(), codec=codec, file_store=file_store)
        except OSError:
            return cls(None, codec=codec, file_store=file_store)

    @classmethod
    def disabled(cls) -> UnitCache:
        return cls(None)

    def entry_path(self, source: str) -> str | None:
        """Return the content-addressed path for one source snapshot."""
        if self._directory is None:
            return None
        digest = hashlib.sha256()
        for part in (str(FileUnitCacheCodec.SCHEMA_VERSION), self._unit_version, source):
            encoded = part.encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return os.path.join(self._directory, f"{self._PREFIX}{digest.hexdigest()}{self._JSON_SUFFIX}")

    def load(self, source_path: str, source: str) -> FileUnit | None:
        """Load one validated entry, returning ``None`` when absent or corrupt."""
        path = self.entry_path(source)
        if path is None:
            return None
        self.prune()
        content_hash = hashlib.sha256(source.encode()).hexdigest()
        return self._codec.decode(self._file_store.read_json(path), source_path, content_hash)

    def store(self, source: str, unit: FileUnit) -> str | None:
        """Best-effort atomic persistence; cache failure never blocks analysis."""
        path = self.entry_path(source)
        if path is None:
            return None
        try:
            self._file_store.write_json(path, self._codec.encode(unit))
        except (OSError, TypeError, ValueError):
            return None
        return path

    def prune(self) -> bool:
        """Remove unsafe/expired entries once, retrying failed directory scans."""
        if self._directory is None or self._pruned:
            return self._pruned
        with self._prune_lock:
            if self._pruned:
                return True
            try:
                names = os.listdir(self._directory)
            except OSError:
                return False
            cutoff = time.time() - self._MAX_AGE_SECONDS
            for name in names:
                if not name.startswith(self._PREFIX):
                    continue
                path = os.path.join(self._directory, name)
                try:
                    legacy = name.endswith(self._LEGACY_SUFFIX)
                    expired = name.endswith(self._JSON_SUFFIX) and os.path.getmtime(path) < cutoff
                    if legacy or expired:
                        os.remove(path)
                except OSError:
                    pass
            self._pruned = True
            return True


class PackageResolutionCache:
    """Cache immutable package resolutions by stable manifest/lock content."""

    _ENTRY_CACHE_MAX = 256
    _STABLE_RESOLUTION_ATTEMPTS = 3

    def __init__(self, resolver: PackageUniverse | None = None) -> None:
        self.resolver = resolver or PackageUniverse()
        self._entries: OrderedDict[str, tuple[tuple, ResolvedPackages]] = OrderedDict()
        self._manifest_locks: WeakValueDictionary[str, threading.Lock] = WeakValueDictionary()
        self._lock = threading.RLock()

    def resolve_for(self, input_path: str) -> ResolvedPackages:
        manifest = self.manifest_for(input_path)
        if manifest is None:
            return ResolvedPackages.empty()
        key = os.path.normcase(os.path.realpath(manifest))
        manifest_lock = self._manifest_lock(key)
        with manifest_lock:
            for _attempt in range(self._STABLE_RESOLUTION_ATTEMPTS):
                before = self._fingerprint(manifest)
                with self._lock:
                    cached = self._entries.get(key)
                    if cached is not None and cached[0] == before:
                        self._entries.move_to_end(key)
                        return cached[1]
                packages = self.resolver.resolve_for(input_path)
                after = self._fingerprint(manifest)
                if before != after:
                    continue
                with self._lock:
                    self._entries[key] = (after, packages)
                    self._entries.move_to_end(key)
                    while len(self._entries) > self._ENTRY_CACHE_MAX:
                        self._entries.popitem(last=False)
                return packages
        raise IncludeResolutionError(
            "package resolution failed: btrc.toml or btrc.lock changed repeatedly during resolution; retry after the save completes"
        )

    def manifest_for(self, input_path: str) -> str | None:
        """Return the nearest manifest governing one source file."""
        return self.resolver.find_manifest(os.path.dirname(os.path.abspath(input_path)))

    def shares_manifest(self, path: str, active_manifest: str | None) -> bool:
        """Whether ``path`` has the active document's manifest boundary."""
        candidate = self.manifest_for(path)
        if active_manifest is None or candidate is None:
            return active_manifest is None and candidate is None
        return os.path.normcase(os.path.realpath(candidate)) == os.path.normcase(os.path.realpath(active_manifest))

    def _manifest_lock(self, key: str) -> threading.Lock:
        with self._lock:
            lock = self._manifest_locks.get(key)
            if lock is None:
                lock = self._manifest_locks[key] = threading.Lock()
            return lock

    def _fingerprint(self, manifest: str) -> tuple:
        lock_path = os.path.join(os.path.dirname(manifest), "btrc.lock")
        return (
            self._file_digest(manifest, self.resolver.manifest_reader.max_bytes, follow_symlinks=True),
            self._file_digest(lock_path, MAX_LOCK_BYTES),
            os.environ.get("BTRC_PKG_CACHE"),
        )

    def _file_digest(self, path: str, max_bytes: int, *, follow_symlinks: bool = False) -> tuple:
        """Fingerprint one bounded package input without trusting its size."""
        try:
            source_file = self.resolver.file_store.open_regular_binary(path, follow_symlinks=follow_symlinks)
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


class WorkspaceCache:
    _FILE_CACHE_MAX = 1024
    _SNAPSHOT_CACHE_MAX = 256

    def __init__(self) -> None:
        self._file_cache: OrderedDict[str, tuple[tuple, FileUnit]] = OrderedDict()
        self.snapshot_cache: OrderedDict[str, tuple] = OrderedDict()
        self._cache_lock = threading.RLock()

    def lookup_file(self, key: str):
        with self._cache_lock:
            cached = self._file_cache.get(key)
            if cached is not None:
                self._file_cache.move_to_end(key)
            return cached

    def store_file(self, key: str, signature: tuple, unit: FileUnit) -> None:
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
        root_key = WorkspaceCache.path_identity(root)
        return [unit for unit in units if WorkspaceCache._path_is_within(unit.path, root_key)]

    def get_snapshot(self, path: str):
        key = WorkspaceCache.path_identity(path)
        with self._cache_lock:
            snapshot = self.snapshot_cache.get(key)
            if snapshot is not None:
                self.snapshot_cache.move_to_end(key)
            return snapshot

    def store_snapshot(self, path: str, fingerprint: tuple, result) -> None:
        key = WorkspaceCache.path_identity(path)
        with self._cache_lock:
            self.snapshot_cache[key] = (fingerprint, result)
            self.snapshot_cache.move_to_end(key)
            while len(self.snapshot_cache) > self._SNAPSHOT_CACHE_MAX:
                self.snapshot_cache.popitem(last=False)

    def close_document(self, path: str) -> None:
        key = WorkspaceCache.path_identity(path)
        with self._cache_lock:
            self._file_cache.pop(key, None)
            self.snapshot_cache.pop(key, None)

    @staticmethod
    def path_identity(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    @staticmethod
    def _path_is_within(path: str, root: str) -> bool:
        try:
            return os.path.commonpath((WorkspaceCache.path_identity(path), root)) == root
        except ValueError:
            return False
