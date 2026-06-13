"""On-disk compilation cache for the btrc CLI.

Caches compiled C output keyed by SHA256 of the fully resolved source
(including stdlib). When source hasn't changed, the cached .c output
is returned immediately, skipping the entire compilation pipeline.

Cache location: resolved by ``cache_keys.resolve_cache_dir`` ($BTRC_CACHE_DIR,
else the btrc.toml project root's .btrc-cache/, else the user cache dir).
Invalidation: automatic — the key covers both the resolved source and a
content hash of the compiler itself (lexer through emitter), so any source
or compiler change produces a different key.
"""

from __future__ import annotations

import hashlib
import os

from .cache_keys import resolve_cache_dir, toolchain_hash


def _cache_key(resolved_source: str) -> str:
    """Compute cache key from the toolchain content hash + resolved source."""
    content = f"v{toolchain_hash('full')}\n{resolved_source}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_cached(resolved_source: str, input_path: str | None = None) -> str | None:
    """Look up cached C output for the given resolved source.

    Returns the cached C source string, or None if not cached.
    ``input_path`` anchors project-root cache-dir resolution.
    """
    key = _cache_key(resolved_source)
    path = os.path.join(resolve_cache_dir(input_path), f"{key}.c")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return None


def store(resolved_source: str, c_output: str,
          input_path: str | None = None) -> None:
    """Store compiled C output in the disk cache."""
    key = _cache_key(resolved_source)
    path = os.path.join(resolve_cache_dir(input_path), f"{key}.c")
    with open(path, "w") as f:
        f.write(c_output)
