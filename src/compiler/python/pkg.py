"""Reproducible, invocation-scoped package resolution for btrc.

A package is a directory containing a ``btrc.toml`` manifest and modules under
``src/`` (or at its root). Dependencies are declared by path or Git and pinned
in ``btrc.lock``. Resolving a source file returns an immutable
``ResolvedPackages`` value; no package selection is installed in process or
task-global state.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .cache_io import atomic_write_json, load_json
from .manifest_io import load_manifest
from .pkg_git import GitDependencyCache


class IncludeResolutionError(Exception):
    """Include/import resolution failed before lexing."""


class LockfileError(ValueError):
    """A present lockfile is corrupt or violates its declared schema."""


class LockfileVersionError(LockfileError):
    """A lockfile was written by an unsupported schema version."""


LOCK_SCHEMA = 2
MAX_LOCK_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class ResolvedPackages:
    """Immutable dependency universe governing one compiler invocation."""

    manifest_path: str | None
    entries: Mapping[str, Mapping[str, str]]

    def __post_init__(self) -> None:
        frozen = {name: MappingProxyType(dict(entry)) for name, entry in self.entries.items()}
        object.__setattr__(self, "entries", MappingProxyType(frozen))

    @classmethod
    def empty(cls) -> ResolvedPackages:
        return cls(manifest_path=None, entries={})

    def paths_for_import(self, spec: str) -> tuple[str, ...]:
        """Resolve a package import, or return empty when its head is local."""

        spec = spec.strip()
        head, _, rest = spec.partition(".")
        package = self.entries.get(head)
        if package is None:
            return ()
        root = package["path"]
        module = rest if rest else head
        relative = module.replace(".", "/")
        for candidate in (
            os.path.join(root, "src", relative + ".btrc"),
            os.path.join(root, relative + ".btrc"),
        ):
            if os.path.exists(candidate):
                return (os.path.abspath(candidate),)
        raise IncludeResolutionError(
            f"package import '{spec}' not found in dependency '{head}'\n  package root: {root}"
        )


class PackageResolver:
    """Own manifest discovery, lockfile policy, and dependency materialization."""

    def __init__(self, git_dependencies: GitDependencyCache | None = None) -> None:
        self.git_dependencies = git_dependencies or GitDependencyCache()

    @staticmethod
    def find_manifest(start_directory: str) -> str | None:
        """Walk upward from a directory to the nearest ``btrc.toml``."""

        directory = os.path.abspath(start_directory)
        while True:
            candidate = os.path.join(directory, "btrc.toml")
            if os.path.exists(candidate):
                return candidate
            parent = os.path.dirname(directory)
            if parent == directory:
                return None
            directory = parent

    def resolve_for(
        self,
        input_path: str,
        *,
        refresh: bool = False,
    ) -> ResolvedPackages:
        """Resolve the dependencies governing one input file."""

        manifest = self.find_manifest(os.path.dirname(os.path.abspath(input_path)))
        if manifest is None:
            return ResolvedPackages.empty()
        try:
            return self.resolve_manifest(manifest, refresh=refresh)
        except (subprocess.SubprocessError, ValueError, OSError) as error:
            detail = (getattr(error, "stderr", None) or "").strip()
            message = f"package resolution failed: {error}"
            if detail:
                message = f"{message}\n  {detail}"
            raise IncludeResolutionError(message) from error

    def resolve_manifest(
        self,
        manifest_path: str,
        *,
        refresh: bool = False,
    ) -> ResolvedPackages:
        """Resolve one manifest, using its lock when current."""

        manifest_path = os.path.abspath(manifest_path)
        manifest_directory = os.path.dirname(manifest_path)
        lock_path = os.path.join(manifest_directory, "btrc.lock")
        manifest = load_manifest(manifest_path)
        dependencies = manifest.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ValueError("manifest 'dependencies' must be a table")
        dependencies_hash = self.dependencies_hash(dependencies)

        if not refresh and os.path.exists(lock_path):
            locked = self._load_lock(
                lock_path,
                dependencies_hash,
                manifest_directory,
            )
            if locked is not None:
                return ResolvedPackages(manifest_path, locked)

        resolved = {
            name: self._resolve_dependency(
                name,
                specification,
                manifest_directory,
                refresh=refresh,
            )
            for name, specification in dependencies.items()
        }
        self._write_lock(
            lock_path,
            dependencies_hash,
            resolved,
            manifest_directory,
        )
        return ResolvedPackages(manifest_path, resolved)

    @staticmethod
    def dependencies_hash(dependencies: Mapping) -> str:
        """Return the lock staleness stamp for a dependency table."""

        canonical = json.dumps(dependencies, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def _resolve_dependency(
        self,
        name: str,
        specification,
        manifest_directory: str,
        *,
        refresh: bool = False,
    ) -> dict[str, str]:
        if isinstance(specification, str):
            if not specification:
                raise ValueError(f"dependency '{name}' has an empty path")
            path = specification
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(manifest_directory, path))
            return {"path": path}
        if not isinstance(specification, dict):
            raise ValueError(f"dependency '{name}' must be a path string or dependency table")
        if "path" in specification:
            path = specification["path"]
            if not isinstance(path, str) or not path:
                raise ValueError(f"dependency '{name}' must specify a non-empty path")
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(manifest_directory, path))
            return {"path": path}
        if "git" in specification:
            revision = specification.get("rev") or specification.get("tag") or specification.get("branch") or "HEAD"
            path = self.git_dependencies.resolve(
                name,
                specification["git"],
                revision,
                refresh=refresh,
            )
            return {
                "commit": self.git_dependencies.resolved_commit(path),
                "git": specification["git"],
                "path": path,
                "rev": revision,
            }
        raise ValueError(f"dependency '{name}' must specify a path or git source")

    def _load_lock(
        self,
        lock_path: str,
        dependencies_hash: str,
        manifest_directory: str,
    ) -> dict[str, dict[str, str]] | None:
        """Return a schema-v2 resolution, or ``None`` for stale data."""

        lock = load_json(lock_path, max_bytes=MAX_LOCK_BYTES)
        if lock is None:
            if not os.path.exists(lock_path):
                return None
            raise LockfileError(f"cannot parse '{lock_path}' as a bounded UTF-8 JSON lockfile")
        if not isinstance(lock, dict):
            raise LockfileError(f"invalid '{lock_path}': lockfile root must be an object")
        schema = lock.get("schema")
        if schema is None:
            if set(lock) <= {"manifest_hash", "packages"} and "packages" in lock:
                return None
            raise LockfileError(f"invalid legacy lockfile '{lock_path}'")
        if schema != LOCK_SCHEMA:
            if schema == 1:
                return None
            raise LockfileVersionError(
                f"unsupported btrc.lock schema {schema!r} in '{lock_path}' "
                f"(this compiler supports schema {LOCK_SCHEMA})"
            )
        if set(lock) != {"manifest_hash", "packages", "schema"}:
            raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': unexpected fields")
        if not isinstance(lock["manifest_hash"], str):
            raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': manifest hash must be text")
        if lock["manifest_hash"] != dependencies_hash:
            return None
        locked_packages = lock["packages"]
        if not isinstance(locked_packages, dict):
            raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': packages must be an object")
        self._validate_locked_packages(locked_packages, lock_path)

        packages: dict[str, dict[str, str]] = {}
        for name, value in locked_packages.items():
            entry = dict(value)
            if "git" in entry:
                entry["commit"] = entry["commit"].lower()
                entry["path"] = self.git_dependencies.resolve(
                    name,
                    entry["git"],
                    entry["rev"],
                    pinned_commit=entry["commit"],
                )
            elif not os.path.isabs(entry["path"]):
                entry["path"] = os.path.normpath(os.path.join(manifest_directory, entry["path"]))
            packages[name] = entry
        return packages

    def _validate_locked_packages(
        self,
        locked_packages: dict,
        lock_path: str,
    ) -> None:
        for name, entry in locked_packages.items():
            if not isinstance(name, str) or not name or not isinstance(entry, dict):
                raise LockfileError(f"invalid schema-{LOCK_SCHEMA} package entry in '{lock_path}'")
            if "git" in entry:
                valid = (
                    set(entry) == {"commit", "git", "rev"}
                    and isinstance(entry["git"], str)
                    and bool(entry["git"])
                    and isinstance(entry["rev"], str)
                    and bool(entry["rev"])
                    and not entry["rev"].startswith("-")
                    and self.git_dependencies.is_commit_sha(entry["commit"])
                )
                if not valid:
                    raise LockfileError(f"invalid locked Git dependency '{name}' in '{lock_path}'")
            elif not (set(entry) == {"path"} and isinstance(entry["path"], str) and bool(entry["path"])):
                raise LockfileError(f"invalid locked path dependency '{name}' in '{lock_path}'")

    @staticmethod
    def _write_lock(
        lock_path: str,
        dependencies_hash: str,
        resolved: Mapping[str, Mapping[str, str]],
        manifest_directory: str,
    ) -> None:
        """Atomically record portable paths and immutable Git resolutions."""

        packages = {}
        for name, entry in resolved.items():
            if "git" in entry:
                packages[name] = {
                    "commit": entry["commit"],
                    "git": entry["git"],
                    "rev": entry["rev"],
                }
            else:
                packages[name] = {"path": os.path.relpath(entry["path"], manifest_directory)}
        atomic_write_json(
            lock_path,
            {
                "manifest_hash": dependencies_hash,
                "packages": packages,
                "schema": LOCK_SCHEMA,
            },
            file_mode=0o644,
        )


__all__ = (
    "LOCK_SCHEMA",
    "MAX_LOCK_BYTES",
    "IncludeResolutionError",
    "LockfileError",
    "LockfileVersionError",
    "PackageResolver",
    "ResolvedPackages",
)
