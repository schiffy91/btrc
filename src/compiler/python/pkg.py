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
checkouts) and resolved back to absolute paths at load; git dependencies are
recorded as (url, rev) and re-derived from the clone cache at load.

Git dependencies are cloned into a cache under ~/.btrc/pkgs/ (override with
$BTRC_PKG_CACHE), keyed by name + rev + a hash of the URL, so same-named deps
from different URLs never share a clone. Refresh semantics: a rev that is a
full 40-char commit SHA is immutable (cloned once, never refetched); any other
rev (branch, tag, HEAD) is pinned by the initial clone and re-pinned by
`git fetch` + checkout on every --fetch.

Imports then resolve as:

    import mathx          → <mathx_root>/src/mathx.btrc  (or <root>/mathx.btrc)
    import mathx.vec      → <mathx_root>/src/vec.btrc    (or <root>/vec.btrc)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib


class IncludeResolutionError(Exception):
    """Include/import resolution failed before lexing.

    Defined here — the lowest layer of import resolution — so package errors
    can raise it without importing frontend (which imports this module).
    frontend re-exports it as the canonical import point. Raised instead of
    ``sys.exit`` so host processes (LSP, tests) survive resolution failures.
    """


# Resolved {name: {"path": abs_root, "git"?: url, "rev"?: rev}} for the
# manifest governing the current compilation. Set by configure_for().
_PACKAGES: dict[str, dict] = {}


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


def _cache_dir() -> str:
    base = os.environ.get("BTRC_PKG_CACHE") or os.path.expanduser("~/.btrc/pkgs")
    os.makedirs(base, exist_ok=True)
    return base


def _is_commit_sha(rev: str) -> bool:
    return len(rev) == 40 and all(c in "0123456789abcdef" for c in rev.lower())


def _git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], check=True,
                          capture_output=True, text=True)


def _checkout(dest: str, rev: str) -> None:
    """Detached checkout of rev, preferring the remote-tracking ref so a
    moving branch actually advances after a fetch."""
    for target in (f"origin/{rev}", rev):
        r = subprocess.run(["git", "-C", dest, "checkout", "--quiet",
                            "--detach", target],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return
    raise subprocess.CalledProcessError(r.returncode, r.args,
                                        output=r.stdout, stderr=r.stderr)


def _resolve_git(name: str, url: str, rev: str, refresh: bool = False) -> str:
    """Clone url@rev into the cache and return its absolute path.

    The cache key includes a hash of the URL, so two deps with the same
    name+rev but different URLs get distinct clones. Non-SHA revs are
    refetched + re-pinned when ``refresh`` is set (--fetch).
    """
    url_tag = hashlib.sha256(url.encode()).hexdigest()[:8]
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in f"{name}-{rev}")
    dest = os.path.join(_cache_dir(), f"{safe}-{url_tag}")
    if not os.path.isdir(os.path.join(dest, ".git")):
        _git(["clone", "--quiet", url, dest])
        _checkout(dest, rev)
    elif refresh and not _is_commit_sha(rev):
        _git(["-C", dest, "fetch", "--quiet", "origin"])
        _checkout(dest, rev)
    return os.path.abspath(dest)


def _resolve_dep(name: str, spec, manifest_dir: str, refresh: bool = False) -> dict:
    if isinstance(spec, str):
        # bare path string
        p = spec if os.path.isabs(spec) else os.path.normpath(os.path.join(manifest_dir, spec))
        return {"path": p}
    if "path" in spec:
        p = spec["path"]
        p = p if os.path.isabs(p) else os.path.normpath(os.path.join(manifest_dir, p))
        return {"path": p}
    if "git" in spec:
        rev = spec.get("rev") or spec.get("tag") or spec.get("branch") or "HEAD"
        return {"path": _resolve_git(name, spec["git"], rev, refresh=refresh),
                "git": spec["git"], "rev": rev}
    raise ValueError(f"dependency '{name}' must specify a path or git source")


def _deps_hash(deps: dict) -> str:
    """Hash of the manifest's dependency table; stamps the lock for staleness."""
    canonical = json.dumps(deps, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _load_lock(lock_path: str, deps_hash: str, manifest_dir: str) -> dict | None:
    """Return the locked resolution, or None when the lock is unusable/stale."""
    try:
        with open(lock_path) as f:
            lock = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if lock.get("manifest_hash") != deps_hash:
        return None  # dependencies changed (or pre-hash lock): re-resolve
    packages: dict[str, dict] = {}
    for name, entry in lock.get("packages", {}).items():
        entry = dict(entry)
        if "git" in entry:
            entry["path"] = _resolve_git(name, entry["git"],
                                         entry.get("rev") or "HEAD")
        else:
            p = entry.get("path", "")
            if not os.path.isabs(p):
                p = os.path.normpath(os.path.join(manifest_dir, p))
            entry["path"] = p
        packages[name] = entry
    return packages


def _write_lock(lock_path: str, deps_hash: str, resolved: dict[str, dict],
                manifest_dir: str) -> None:
    """Record resolution portably: relative paths for path deps, (url, rev)
    for git deps (their cache path is machine-local and re-derived at load)."""
    packages = {}
    for name, entry in resolved.items():
        if "git" in entry:
            packages[name] = {"git": entry["git"], "rev": entry.get("rev")}
        else:
            packages[name] = {"path": os.path.relpath(entry["path"], manifest_dir)}
    with open(lock_path, "w") as f:
        json.dump({"manifest_hash": deps_hash, "packages": packages},
                  f, indent=2, sort_keys=True)
        f.write("\n")


def resolve(manifest_path: str, refresh: bool = False) -> dict[str, dict]:
    """Resolve all dependencies, using btrc.lock when fresh (unless refresh)."""
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    lock_path = os.path.join(manifest_dir, "btrc.lock")

    with open(manifest_path, "rb") as f:
        manifest = tomllib.load(f)
    deps = manifest.get("dependencies", {})
    deps_hash = _deps_hash(deps)

    if not refresh and os.path.exists(lock_path):
        locked = _load_lock(lock_path, deps_hash, manifest_dir)
        if locked is not None:
            return locked

    resolved = {name: _resolve_dep(name, spec, manifest_dir, refresh=refresh)
                for name, spec in deps.items()}
    _write_lock(lock_path, deps_hash, resolved, manifest_dir)
    return resolved


def configure_for(input_path: str, refresh: bool = False) -> None:
    """Find + resolve the manifest governing input_path; populate _PACKAGES.

    Raises IncludeResolutionError on failure (never exits): hosts such as the
    LSP must survive a broken manifest. _PACKAGES is cleared first so a failed
    resolution can't leave a previous project's packages active.
    """
    global _PACKAGES
    _PACKAGES = {}
    manifest = find_manifest(os.path.dirname(os.path.abspath(input_path)))
    if manifest is None:
        return
    try:
        _PACKAGES = resolve(manifest, refresh=refresh)
    except (subprocess.CalledProcessError, ValueError, OSError) as e:
        detail = (getattr(e, "stderr", None) or "").strip()
        msg = f"package resolution failed: {e}"
        if detail:
            msg = f"{msg}\n  {detail}"
        raise IncludeResolutionError(msg) from e


def package_import_paths(spec: str) -> list[str]:
    """Resolve `import <pkg>` or `import <pkg>.<module>` against dependencies.

    Returns [] if the spec's first segment is not a declared dependency, so the
    caller can fall through to stdlib/relative resolution. Raises
    IncludeResolutionError when the dependency exists but the module doesn't.
    """
    spec = spec.strip()
    head, _, rest = spec.partition(".")
    pkg = _PACKAGES.get(head)
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
    raise IncludeResolutionError(
        f"package import '{spec}' not found in dependency '{head}'\n"
        f"  package root: {root}"
    )
