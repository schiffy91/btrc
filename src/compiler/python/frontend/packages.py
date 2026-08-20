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
import shutil
import stat
import subprocess
import tempfile
import tomllib
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from types import MappingProxyType


class IncludeResolutionError(Exception):
    """Include/import resolution failed before lexing."""


class LockfileError(ValueError):
    """A present lockfile is corrupt or violates its declared schema."""


class LockfileVersionError(LockfileError):
    """A lockfile was written by an unsupported schema version."""


LOCK_SCHEMA = 2
MAX_LOCK_BYTES = 16 * 1024 * 1024


class PackageFileStore:
    """Own bounded metadata reads and atomic package-state publication."""

    def open_regular_binary(self, path: str, *, follow_symlinks: bool = False):
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
            file = os.fdopen(descriptor, "rb")
            descriptor = -1
            return file
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)

    def read_json(self, path: str, *, max_bytes: int = 64 * 1024 * 1024):
        try:
            file = self.open_regular_binary(path)
            if file is None:
                return None
            with file:
                if os.fstat(file.fileno()).st_size > max_bytes:
                    return None
                encoded = file.read(max_bytes + 1)
            if len(encoded) > max_bytes:
                return None
            return json.loads(encoded.decode("utf-8"), parse_constant=self._reject_json_constant)
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return None

    def write_json(self, path: str, payload, *, file_mode: int | None = None) -> None:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(prefix=".btrc-package-", dir=directory)
        try:
            if file_mode is not None:
                fchmod = getattr(os, "fchmod", None)
                if fchmod is not None:
                    fchmod(descriptor, file_mode)
                else:
                    os.chmod(temporary_path, file_mode)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                descriptor = -1
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
            self._sync_parent(path)
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
            with suppress(FileNotFoundError):
                os.remove(temporary_path)

    @staticmethod
    def _sync_parent(path: str) -> None:
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


class PackageManifestReader:
    """Own bounded UTF-8 TOML reads for package resolution."""

    DEFAULT_MAX_BYTES = 1024 * 1024

    def __init__(
        self,
        max_bytes: int = DEFAULT_MAX_BYTES,
        *,
        file_store: PackageFileStore | None = None,
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("package manifest byte limit must be positive")
        self.max_bytes = max_bytes
        self.file_store = file_store or PackageFileStore()

    def read(self, path: str) -> dict:
        """Load one regular manifest without unbounded input allocation."""
        manifest_file = self.file_store.open_regular_binary(
            path,
            follow_symlinks=True,
        )
        if manifest_file is None:
            raise ValueError(f"package manifest '{path}' is not a regular file")
        with manifest_file:
            if os.fstat(manifest_file.fileno()).st_size > self.max_bytes:
                raise ValueError(f"package manifest '{path}' exceeds the {self.max_bytes}-byte limit")
            encoded = manifest_file.read(self.max_bytes + 1)
        if len(encoded) > self.max_bytes:
            raise ValueError(f"package manifest '{path}' exceeds the {self.max_bytes}-byte limit")
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"package manifest '{path}' is not valid UTF-8 at byte {error.start}") from error
        try:
            manifest = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, RecursionError) as error:
            raise ValueError(f"cannot parse package manifest '{path}': {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError(f"package manifest '{path}' must contain a TOML table")
        return manifest


class PackageUniverse:
    """Own manifest discovery, lockfile policy, and dependency materialization."""

    def __init__(
        self,
        git_dependencies: GitDependencyCache | None = None,
        *,
        manifest_reader: PackageManifestReader | None = None,
        file_store: PackageFileStore | None = None,
    ) -> None:
        owned_store = file_store
        if owned_store is None and git_dependencies is not None:
            owned_store = git_dependencies.file_store
        if owned_store is None and manifest_reader is not None:
            owned_store = manifest_reader.file_store
        self.file_store = owned_store or PackageFileStore()
        if git_dependencies is not None and git_dependencies.file_store is not self.file_store:
            raise ValueError("PackageUniverse and Git cache must share one file store")
        if manifest_reader is not None and manifest_reader.file_store is not self.file_store:
            raise ValueError("PackageUniverse and manifest reader must share one file store")
        self.git_dependencies = git_dependencies or GitDependencyCache(file_store=self.file_store)
        self.manifest_reader = manifest_reader or PackageManifestReader(file_store=self.file_store)

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
        manifest = self.manifest_reader.read(manifest_path)
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

        lock = self.file_store.read_json(lock_path, max_bytes=MAX_LOCK_BYTES)
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

    def _write_lock(
        self,
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
        self.file_store.write_json(
            lock_path,
            {
                "manifest_hash": dependencies_hash,
                "packages": packages,
                "schema": LOCK_SCHEMA,
            },
            file_mode=0o644,
        )


class GitDependencyCache:
    """Own Git execution, ref pinning, and immutable checkout publication."""

    REF_RECORD_SCHEMA = 1
    MAX_REF_RECORD_BYTES = 16 * 1024
    GIT_TIMEOUT_SECONDS = 300

    def __init__(
        self,
        cache_directory: str | None = None,
        *,
        file_store: PackageFileStore | None = None,
    ) -> None:
        self._configured_cache_directory = cache_directory
        self.file_store = file_store or PackageFileStore()

    def resolve(
        self,
        name: str,
        url: str,
        revision: str,
        refresh: bool = False,
        *,
        pinned_commit: str | None = None,
    ) -> str:
        """Return an immutable checkout for ``url`` at an exact commit."""

        self._validate_source(name, url, revision)
        immutable_commit = pinned_commit or (revision if self.is_commit_sha(revision) else None)
        if immutable_commit is not None:
            if not isinstance(immutable_commit, str):
                raise ValueError(f"git dependency '{name}' has an invalid pinned commit")
            commit = immutable_commit.lower()
            if not self.is_commit_sha(commit):
                raise ValueError(f"git dependency '{name}' has an invalid pinned commit")
            return self._ensure_commit_checkout(
                name,
                url,
                revision,
                commit,
            )

        record_path = self._ref_record_path(name, url, revision)
        if not refresh:
            record = self.file_store.read_json(
                record_path,
                max_bytes=self.MAX_REF_RECORD_BYTES,
            )
            if self._valid_ref_record(record, name, url, revision):
                return self._ensure_commit_checkout(
                    name,
                    url,
                    revision,
                    record["commit"],
                )

        checkout, commit = self._clone_requested_ref(name, url, revision)
        self._publish_ref_record(record_path, name, url, revision, commit)
        return checkout

    def resolved_commit(self, checkout: str) -> str:
        """Read and validate the exact commit checked out at ``checkout``."""

        commit = self._git(["-C", checkout, "rev-parse", "--verify", "HEAD"]).stdout.strip().lower()
        if not self.is_commit_sha(commit):
            raise ValueError(f"git checkout '{checkout}' did not resolve to a full commit SHA")
        return commit

    def cache_identity(self, name: str, url: str, revision: str) -> str:
        """Return collision-resistant identity over the exact source tuple."""

        digest = hashlib.sha256()
        for part in (name, url, revision):
            encoded = part.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def is_commit_sha(self, value: str) -> bool:
        """Return whether value is a complete SHA-1 or SHA-256 object id."""

        return (
            isinstance(value, str)
            and len(value) in (40, 64)
            and all(character in "0123456789abcdef" for character in value.lower())
        )

    def _validate_source(self, name: str, url: str, revision: str) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("git dependency name must be a non-empty string")
        if not isinstance(url, str) or not url:
            raise ValueError(f"git dependency '{name}' must specify a non-empty URL")
        if not isinstance(revision, str) or not revision or revision.startswith("-"):
            raise ValueError(f"git dependency '{name}' has an invalid revision")

    def _cache_directory(self) -> str:
        directory = self._configured_cache_directory or os.environ.get("BTRC_PKG_CACHE")
        directory = directory or os.path.expanduser("~/.btrc/pkgs")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _safe_label(self, name: str, revision: str) -> str:
        label = "".join(
            character if character.isalnum() or character in "-._" else "_" for character in f"{name}-{revision}"
        )
        return (label or "dependency")[:64]

    def _ref_record_path(self, name: str, url: str, revision: str) -> str:
        identity = self.cache_identity(name, url, revision)
        return os.path.join(
            self._cache_directory(),
            f".{self._safe_label(name, revision)}-{identity}.ref.json",
        )

    def _checkout_path(
        self,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> str:
        identity = self.cache_identity(name, url, revision)
        return os.path.join(
            self._cache_directory(),
            f"{self._safe_label(name, revision)}-{identity}-{commit}",
        )

    def _valid_ref_record(
        self,
        record,
        name: str,
        url: str,
        revision: str,
    ) -> bool:
        return (
            isinstance(record, dict)
            and set(record) == {"commit", "git", "name", "rev", "schema"}
            and record["schema"] == self.REF_RECORD_SCHEMA
            and record["name"] == name
            and record["git"] == url
            and record["rev"] == revision
            and self.is_commit_sha(record["commit"])
        )

    def _publish_ref_record(
        self,
        path: str,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> None:
        self.file_store.write_json(
            path,
            {
                "commit": commit,
                "git": url,
                "name": name,
                "rev": revision,
                "schema": self.REF_RECORD_SCHEMA,
            },
        )

    def _clone_requested_ref(
        self,
        name: str,
        url: str,
        revision: str,
    ) -> tuple[str, str]:
        temporary = self._clone_to_temporary(name, url, revision)
        try:
            self._checkout(temporary, revision)
            commit = self.resolved_commit(temporary)
            destination = self._checkout_path(name, url, revision, commit)
            return self._publish_checkout(temporary, destination, commit), commit
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _ensure_commit_checkout(
        self,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> str:
        destination = self._checkout_path(name, url, revision, commit)
        if self._checkout_matches(destination, commit):
            return os.path.abspath(destination)
        self._remove_cache_entry(destination)
        temporary = self._clone_to_temporary(name, url, revision)
        try:
            self._checkout(temporary, commit)
            actual = self.resolved_commit(temporary)
            if actual != commit:
                raise ValueError(f"git dependency '{name}' resolved pinned commit {commit} to {actual}")
            return self._publish_checkout(temporary, destination, commit)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _clone_to_temporary(self, name: str, url: str, revision: str) -> str:
        prefix = f".{self._safe_label(name, revision)}-{self.cache_identity(name, url, revision)[:16]}-"
        temporary = tempfile.mkdtemp(
            prefix=prefix,
            dir=self._cache_directory(),
        )
        try:
            self._git(["clone", "--quiet", "--", url, temporary])
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return temporary

    def _publish_checkout(
        self,
        temporary: str,
        destination: str,
        commit: str,
    ) -> str:
        try:
            os.rename(temporary, destination)
        except OSError:
            if not self._checkout_matches(destination, commit):
                raise
        return os.path.abspath(destination)

    def _checkout_matches(self, path: str, commit: str) -> bool:
        if not os.path.isdir(os.path.join(path, ".git")):
            return False
        try:
            return self.resolved_commit(path) == commit
        except (OSError, ValueError, subprocess.CalledProcessError):
            return False

    def _remove_cache_entry(self, path: str) -> None:
        if not os.path.lexists(path):
            return
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    def _git(self, arguments: list[str]) -> subprocess.CompletedProcess:
        return self._run_git(arguments, check=True)

    def _run_git(
        self,
        arguments: list[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess:
        """Run Git noninteractively with a finite network bound."""

        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GCM_INTERACTIVE"] = "Never"
        return subprocess.run(
            ["git", *arguments],
            check=check,
            capture_output=True,
            text=True,
            timeout=self.GIT_TIMEOUT_SECONDS,
            env=environment,
        )

    def _checkout(self, destination: str, revision: str) -> None:
        for target in (f"origin/{revision}", revision):
            result = self._run_git(
                ["-C", destination, "checkout", "--quiet", "--detach", target],
                check=False,
            )
            if result.returncode == 0:
                return
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )


__all__ = (
    "LOCK_SCHEMA",
    "MAX_LOCK_BYTES",
    "GitDependencyCache",
    "IncludeResolutionError",
    "LockfileError",
    "LockfileVersionError",
    "PackageFileStore",
    "PackageManifestReader",
    "PackageUniverse",
    "ResolvedPackages",
)
