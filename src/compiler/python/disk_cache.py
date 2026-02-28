"""On-disk compilation cache for the btrc CLI.

Caches compiled C output keyed by SHA256 of the fully resolved source
(including stdlib). When source hasn't changed, the cached .c output
is returned immediately, skipping the entire compilation pipeline.

Cache location: .btrc-cache/ in the project root.
Invalidation: automatic — any source change produces a different hash.
"""

from __future__ import annotations

import hashlib
import os

# Version stamp — bump when compiler output changes for the same input
_CACHE_VERSION = "1"

_CACHE_DIR = ".btrc-cache"


def _cache_dir() -> str:
    """Get the cache directory path, creating it if needed."""
    cache = os.path.join(os.getcwd(), _CACHE_DIR)
    os.makedirs(cache, exist_ok=True)
    return cache


def _cache_key(resolved_source: str) -> str:
    """Compute cache key from compiler version + full resolved source."""
    content = f"v{_CACHE_VERSION}\n{resolved_source}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_cached(resolved_source: str) -> str | None:
    """Look up cached C output for the given resolved source.

    Returns the cached C source string, or None if not cached.
    """
    key = _cache_key(resolved_source)
    path = os.path.join(_cache_dir(), f"{key}.c")
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return None


def store(resolved_source: str, c_output: str) -> None:
    """Store compiled C output in the disk cache."""
    key = _cache_key(resolved_source)
    path = os.path.join(_cache_dir(), f"{key}.c")
    with open(path, "w") as f:
        f.write(c_output)
