"""Reproducible package management for btrc.

A package is a directory containing a `btrc.toml` manifest and modules under
`src/` (or at its root). Dependencies are declared by path or git:

    [package]
    name = "myapp"

    [dependencies]
    mathx = { path = "../mathx" }
    netkit = { git = "https://example.com/netkit.git", rev = "v1.2.0" }

Resolution is recorded in `btrc.lock` for reproducible builds. The lock stores
a hash of the manifest's [dependencies] table — editing the dependencies makes
the lock stale and resolution re-runs automatically (no --fetch needed). Path
dependencies are recorded relative to the lock file (reproducible across
checkouts) and resolved back to absolute paths at load; Git dependencies retain
the requested ref and pin its resolved commit SHA.

Git dependencies are cloned into a cache under ~/.btrc/pkgs/ (override with
$BTRC_PKG_CACHE). Cache identities hash the exact name, URL, and requested ref;
checkouts add the immutable resolved commit. ``--fetch`` is the only operation
that advances a moving ref and rewrites its lock entry.

Imports then resolve as:

    import mathx          → <mathx_root>/src/mathx.btrc  (or <root>/mathx.btrc)
    import mathx.vec      → <mathx_root>/src/vec.btrc    (or <root>/vec.btrc)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess

from .cache_io import atomic_write_json, load_json
from .manifest_io import load_manifest
from .pkg_context import (
    configured_packages,
)
from .pkg_context import (
    package_context as package_context,
)
from .pkg_context import (
    replace_packages as _replace_packages,
)
from .pkg_git import is_commit_sha as _is_commit_sha
from .pkg_git import resolve_git as _resolve_git
from .pkg_git import resolved_commit as _resolved_git_commit


class IncludeResolutionError(Exception):
    """Include/import resolution failed before lexing.

    Defined here — the lowest layer of import resolution — so package errors
    can raise it without importing frontend (which imports this module).
    frontend re-exports it as the canonical import point. Raised instead of
    ``sys.exit`` so host processes (LSP, tests) survive resolution failures.
    """


class LockfileError(ValueError):
    """A present lockfile is corrupt or violates its declared schema."""


class LockfileVersionError(LockfileError):
    """A lockfile was written by an unsupported schema version."""


LOCK_SCHEMA = 2
MAX_LOCK_BYTES = 16 * 1024 * 1024


def find_manifest(start_dir: str) -> str | None:
    """Walk up from start_dir to find the nearest btrc.toml."""
    d = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(d, "btrc.toml")
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _resolve_dep(name: str, spec, manifest_dir: str, refresh: bool = False) -> dict:
    if isinstance(spec, str):
        # bare path string
        if not spec:
            raise ValueError(f"dependency '{name}' has an empty path")
        p = spec if os.path.isabs(spec) else os.path.normpath(os.path.join(manifest_dir, spec))
        return {"path": p}
    if not isinstance(spec, dict):
        raise ValueError(f"dependency '{name}' must be a path string or dependency table")
    if "path" in spec:
        p = spec["path"]
        if not isinstance(p, str) or not p:
            raise ValueError(f"dependency '{name}' must specify a non-empty path")
        p = p if os.path.isabs(p) else os.path.normpath(os.path.join(manifest_dir, p))
        return {"path": p}
    if "git" in spec:
        rev = spec.get("rev") or spec.get("tag") or spec.get("branch") or "HEAD"
        path = _resolve_git(name, spec["git"], rev, refresh=refresh)
        return {
            "commit": _resolved_git_commit(path),
            "git": spec["git"],
            "path": path,
            "rev": rev,
        }
    raise ValueError(f"dependency '{name}' must specify a path or git source")


def _deps_hash(deps: dict) -> str:
    """Hash of the manifest's dependency table; stamps the lock for staleness."""
    canonical = json.dumps(deps, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _load_lock(lock_path: str, deps_hash: str, manifest_dir: str) -> dict | None:
    """Return a schema-v2 resolution, or None to migrate stale/legacy data."""
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
            return None  # recognized pre-schema lock: resolve and migrate atomically
        raise LockfileError(f"invalid legacy lockfile '{lock_path}'")
    if schema != LOCK_SCHEMA:
        if schema == 1:
            return None
        raise LockfileVersionError(
            f"unsupported btrc.lock schema {schema!r} in '{lock_path}' (this compiler supports schema {LOCK_SCHEMA})"
        )
    if set(lock) != {"manifest_hash", "packages", "schema"}:
        raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': unexpected fields")
    if not isinstance(lock["manifest_hash"], str):
        raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': manifest hash must be text")
    if lock["manifest_hash"] != deps_hash:
        return None
    locked_packages = lock["packages"]
    if not isinstance(locked_packages, dict):
        raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': packages must be an object")
    for name, entry in locked_packages.items():
        if not isinstance(name, str) or not name or not isinstance(entry, dict):
            raise LockfileError(f"invalid schema-{LOCK_SCHEMA} package entry in '{lock_path}'")
        if "git" in entry:
            if not (
                set(entry) == {"commit", "git", "rev"}
                and isinstance(entry["git"], str)
                and entry["git"]
                and isinstance(entry["rev"], str)
                and entry["rev"]
                and not entry["rev"].startswith("-")
                and _is_commit_sha(entry["commit"])
            ):
                raise LockfileError(f"invalid locked Git dependency '{name}' in '{lock_path}'")
        elif not (set(entry) == {"path"} and isinstance(entry["path"], str) and entry["path"]):
            raise LockfileError(f"invalid locked path dependency '{name}' in '{lock_path}'")
    packages: dict[str, dict] = {}
    for name, entry in locked_packages.items():
        entry = dict(entry)
        if "git" in entry:
            entry["commit"] = entry["commit"].lower()
            entry["path"] = _resolve_git(
                name,
                entry["git"],
                entry["rev"],
                pinned_commit=entry["commit"],
            )
        else:
            p = entry.get("path", "")
            if not os.path.isabs(p):
                p = os.path.normpath(os.path.join(manifest_dir, p))
            entry["path"] = p
        packages[name] = entry
    return packages


def _write_lock(lock_path: str, deps_hash: str, resolved: dict[str, dict], manifest_dir: str) -> None:
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
            packages[name] = {"path": os.path.relpath(entry["path"], manifest_dir)}
    atomic_write_json(
        lock_path,
        {
            "manifest_hash": deps_hash,
            "packages": packages,
            "schema": LOCK_SCHEMA,
        },
        file_mode=0o644,
    )


def resolve(manifest_path: str, refresh: bool = False) -> dict[str, dict]:
    """Resolve all dependencies, using btrc.lock when fresh (unless refresh)."""
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    lock_path = os.path.join(manifest_dir, "btrc.lock")

    manifest = load_manifest(manifest_path)
    deps = manifest.get("dependencies", {})
    if not isinstance(deps, dict):
        raise ValueError("manifest 'dependencies' must be a table")
    deps_hash = _deps_hash(deps)

    if not refresh and os.path.exists(lock_path):
        locked = _load_lock(lock_path, deps_hash, manifest_dir)
        if locked is not None:
            return locked

    resolved = {name: _resolve_dep(name, spec, manifest_dir, refresh=refresh) for name, spec in deps.items()}
    _write_lock(lock_path, deps_hash, resolved, manifest_dir)
    return resolved


def packages_for(input_path: str, refresh: bool = False) -> dict[str, dict]:
    """Resolve packages governing ``input_path`` without installing them."""
    manifest = find_manifest(os.path.dirname(os.path.abspath(input_path)))
    if manifest is None:
        return {}
    try:
        return resolve(manifest, refresh=refresh)
    except (subprocess.SubprocessError, ValueError, OSError) as error:
        detail = (getattr(error, "stderr", None) or "").strip()
        message = f"package resolution failed: {error}"
        if detail:
            message = f"{message}\n  {detail}"
        raise IncludeResolutionError(message) from error


def configure_for(input_path: str, refresh: bool = False) -> None:
    """Install packages governing input_path in this execution context.

    Raises IncludeResolutionError on failure (never exits): hosts such as the
    LSP must survive a broken manifest. The context is cleared first so a
    failed resolution cannot leave a previous project's packages active.
    """
    _replace_packages({})
    _replace_packages(packages_for(input_path, refresh=refresh))


def package_import_paths(spec: str) -> list[str]:
    """Resolve `import <pkg>` or `import <pkg>.<module>` against dependencies.

    Returns [] if the spec's first segment is not a declared dependency, so the
    caller can fall through to stdlib/relative resolution. Raises
    IncludeResolutionError when the dependency exists but the module doesn't.
    """
    spec = spec.strip()
    head, _, rest = spec.partition(".")
    pkg = configured_packages().get(head)
    if pkg is None:
        return []
    root = pkg["path"]
    module = rest if rest else head
    rel = module.replace(".", "/")
    for candidate in (
        os.path.join(root, "src", rel + ".btrc"),
        os.path.join(root, rel + ".btrc"),
    ):
        if os.path.exists(candidate):
            return [os.path.abspath(candidate)]
    raise IncludeResolutionError(f"package import '{spec}' not found in dependency '{head}'\n  package root: {root}")
