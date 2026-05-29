"""Reproducible package management for btrc.

A package is a directory containing a `btrc.toml` manifest and modules under
`src/` (or at its root). Dependencies are declared by path or git:

    [package]
    name = "myapp"

    [dependencies]
    mathx = { path = "../mathx" }
    netkit = { git = "https://example.com/netkit.git", rev = "v1.2.0" }

Resolution is recorded in `btrc.lock` (pins each dependency's resolved location
and git rev) for reproducible builds. Git dependencies are cloned once into a
content-addressed cache under ~/.btrc/pkgs/. Imports then resolve as:

    import mathx          → <mathx_root>/src/mathx.btrc  (or <root>/mathx.btrc)
    import mathx.vec      → <mathx_root>/src/vec.btrc    (or <root>/vec.btrc)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib

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


def _resolve_git(name: str, url: str, rev: str) -> str:
    """Clone url@rev into the cache (once) and return its absolute path."""
    safe = "".join(c if c.isalnum() or c in "-._" else "_" for c in f"{name}-{rev}")
    dest = os.path.join(_cache_dir(), safe)
    if not os.path.isdir(os.path.join(dest, ".git")):
        subprocess.run(["git", "clone", "--quiet", url, dest], check=True)
        subprocess.run(["git", "-C", dest, "checkout", "--quiet", rev], check=True)
    return os.path.abspath(dest)


def _resolve_dep(name: str, spec, manifest_dir: str) -> dict:
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
        return {"path": _resolve_git(name, spec["git"], rev), "git": spec["git"], "rev": rev}
    raise ValueError(f"dependency '{name}' must specify a path or git source")


def resolve(manifest_path: str, refresh: bool = False) -> dict[str, dict]:
    """Resolve all dependencies, using btrc.lock if present (unless refresh)."""
    manifest_dir = os.path.dirname(os.path.abspath(manifest_path))
    lock_path = os.path.join(manifest_dir, "btrc.lock")

    if not refresh and os.path.exists(lock_path):
        with open(lock_path) as f:
            return json.load(f).get("packages", {})

    with open(manifest_path, "rb") as f:
        manifest = tomllib.load(f)
    deps = manifest.get("dependencies", {})
    resolved = {name: _resolve_dep(name, spec, manifest_dir) for name, spec in deps.items()}

    with open(lock_path, "w") as f:
        json.dump({"packages": resolved}, f, indent=2, sort_keys=True)
        f.write("\n")
    return resolved


def configure_for(input_path: str, refresh: bool = False) -> None:
    """Find + resolve the manifest governing input_path; populate _PACKAGES."""
    global _PACKAGES
    manifest = find_manifest(os.path.dirname(os.path.abspath(input_path)))
    if manifest is None:
        _PACKAGES = {}
        return
    try:
        _PACKAGES = resolve(manifest, refresh=refresh)
    except (subprocess.CalledProcessError, ValueError, OSError) as e:
        print(f"error: package resolution failed: {e}", file=sys.stderr)
        sys.exit(1)


def package_import_paths(spec: str) -> list[str]:
    """Resolve `import <pkg>` or `import <pkg>.<module>` against dependencies.

    Returns [] if the spec's first segment is not a declared dependency, so the
    caller can fall through to stdlib/relative resolution.
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
    print(f"error: package import '{spec}' not found in dependency '{head}'\n"
          f"  package root: {root}",
          file=sys.stderr)
    sys.exit(1)
