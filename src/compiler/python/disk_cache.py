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

from .cache_io import atomic_write_text
from .cache_keys import resolve_cache_dir, toolchain_hash

MAX_C_CACHE_BYTES = 256 * 1024 * 1024


def _cache_key(resolved_source: str) -> str:
    """Compute cache key from the toolchain content hash + resolved source."""
    content = f"v{toolchain_hash('full')}\n{resolved_source}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def get_cached(resolved_source: str, input_path: str | None = None) -> str | None:
    """Look up cached C output for the given resolved source.

    Returns the cached C source string, or None if not cached.
    ``input_path`` anchors project-root cache-dir resolution.
    """
    try:
        key = _cache_key(resolved_source)
        path = os.path.join(resolve_cache_dir(input_path), f"{key}.c")
        with open(path, "rb") as cache_file:
            encoded = cache_file.read(MAX_C_CACHE_BYTES + 1)
        if len(encoded) > MAX_C_CACHE_BYTES:
            return None
        return encoded.decode("utf-8")
    except (OSError, UnicodeError):
        return None


def store(
    resolved_source: str,
    c_output: str,
    input_path: str | None = None,
) -> None:
    """Atomically store compiled C output in the disk cache."""
    key = _cache_key(resolved_source)
    path = os.path.join(resolve_cache_dir(input_path), f"{key}.c")
    atomic_write_text(path, c_output)
