"""Safe, deterministic on-disk cache for parsed LSP stdlib units."""

from __future__ import annotations

import hashlib
import os
import threading
import time

from src.compiler.python.ast_codec import decode_ast, encode_ast
from src.compiler.python.ast_nodes import (
    PackagePath,
    QuotedPath,
    RelativePath,
    StdGlob,
    StdModules,
)
from src.compiler.python.cache_io import atomic_write_json, load_json
from src.compiler.python.cache_keys import resolve_cache_dir
from src.compiler.python.frontend.dependencies import SourceDependencyKind
from src.devex.lsp.units import (
    _UNIT_CACHE_VERSION,
    FileDependencies,
    FileDependency,
    FileUnit,
)


class FileUnitCacheCodec:
    """Encode and validate the persistent subset of one parsed file unit."""

    SCHEMA_VERSION = 2
    _IMPORT_SPEC_TYPES = (StdGlob, StdModules, PackagePath, RelativePath, QuotedPath)
    _DEPENDENCY_KINDS = frozenset(kind.value for kind in SourceDependencyKind)

    @classmethod
    def encode(cls, unit: FileUnit) -> dict:
        return {
            "content_hash": unit.content_hash,
            "decls": [encode_ast(declaration) for declaration in unit.decls],
            "dependencies": [
                {
                    "kind": dependency.kind.value,
                    "line": dependency.line,
                    "spec": encode_ast(dependency.spec),
                }
                for dependency in unit.dependencies
            ],
            "defined_names": sorted(unit.defined_names),
            "schema": cls.SCHEMA_VERSION,
        }

    @classmethod
    def decode(
        cls,
        payload,
        source_path: str,
        content_hash: str,
    ) -> FileUnit | None:
        if not cls._payload_is_valid(payload, content_hash):
            return None
        try:
            declarations = [decode_ast(value) for value in payload["decls"]]
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
                dependencies=cls._decode_dependencies(payload["dependencies"]),
                defined_names=frozenset(payload["defined_names"]),
            )
        except (ValueError, TypeError, RecursionError):
            return None

    @classmethod
    def _payload_is_valid(cls, payload, content_hash: str) -> bool:
        return (
            isinstance(payload, dict)
            and set(payload) == {"content_hash", "decls", "dependencies", "defined_names", "schema"}
            and payload["schema"] == cls.SCHEMA_VERSION
            and payload["content_hash"] == content_hash
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
            and record["kind"] in cls._DEPENDENCY_KINDS
            and isinstance(record["line"], int)
            and not isinstance(record["line"], bool)
            and record["line"] > 0
            and isinstance(record["spec"], dict)
        )

    @classmethod
    def _decode_dependencies(cls, records: list[dict]) -> FileDependencies:
        dependencies: list[FileDependency] = []
        for record in records:
            spec = decode_ast(record["spec"])
            if not isinstance(spec, cls._IMPORT_SPEC_TYPES):
                raise ValueError("cached file dependency has an invalid import spec")
            dependencies.append(
                FileDependency(
                    line=record["line"],
                    spec=spec,
                    kind=SourceDependencyKind(record["kind"]),
                )
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
    ) -> None:
        self._directory = os.path.abspath(directory) if directory is not None else None
        self._unit_version = unit_version
        self._pruned = False
        self._prune_lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> UnitCache:
        """Resolve the shared compiler cache, disabling persistence on failure."""

        try:
            return cls(resolve_cache_dir())
        except OSError:
            return cls(None)

    @classmethod
    def disabled(cls) -> UnitCache:
        return cls(None)

    def entry_path(self, source: str) -> str | None:
        """Return the content-addressed path for one source snapshot."""

        if self._directory is None:
            return None
        digest = hashlib.sha256()
        for part in (
            str(FileUnitCacheCodec.SCHEMA_VERSION),
            self._unit_version,
            source,
        ):
            encoded = part.encode()
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return os.path.join(
            self._directory,
            f"{self._PREFIX}{digest.hexdigest()}{self._JSON_SUFFIX}",
        )

    def load(self, source_path: str, source: str) -> FileUnit | None:
        """Load one validated entry, returning ``None`` when absent or corrupt."""

        path = self.entry_path(source)
        if path is None:
            return None
        self.prune()
        content_hash = hashlib.sha256(source.encode()).hexdigest()
        return FileUnitCacheCodec.decode(
            load_json(path),
            source_path,
            content_hash,
        )

    def store(self, source: str, unit: FileUnit) -> str | None:
        """Best-effort atomic persistence; cache failure never blocks analysis."""

        path = self.entry_path(source)
        if path is None:
            return None
        try:
            atomic_write_json(path, FileUnitCacheCodec.encode(unit))
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
