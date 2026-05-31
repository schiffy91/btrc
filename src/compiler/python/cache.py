"""In-memory caching for stdlib source and tokens.

Each process maintains its own cache (no IPC needed).
Caching avoids re-reading and re-lexing stdlib files for every compilation,
which is especially beneficial when running tests in parallel with pytest-xdist.
"""

from __future__ import annotations

import os

from .frontend import (
    _defined_stdlib_names,
    _discover_stdlib_files,
    _get_stdlib_dir,
    _strip_btrc_imports,
)

# Cache: frozenset of user class names → (stdlib_source, stdlib_tokens)
_stdlib_source_cache: dict[frozenset[str], str] = {}
_stdlib_file_cache: dict[str, str] = {}  # filename → file content


def _read_stdlib_file(fname: str) -> str:
    """Read a stdlib file, caching the result."""
    if fname not in _stdlib_file_cache:
        fpath = os.path.join(_get_stdlib_dir(), fname)
        with open(fpath) as f:
            _stdlib_file_cache[fname] = f.read()
    return _stdlib_file_cache[fname]


def get_stdlib_source_cached(user_source: str = "") -> str:
    """Cached version of get_stdlib_source.

    Caches by the set of user-defined class names, since that determines
    which stdlib files are skipped.
    """
    user_names = frozenset(_defined_stdlib_names(user_source))

    if user_names in _stdlib_source_cache:
        return _stdlib_source_cache[user_names]

    parts = []
    for fname in _discover_stdlib_files():
        content = _read_stdlib_file(fname)
        file_names = _defined_stdlib_names(content)
        if file_names & user_names:
            continue
        parts.append(_strip_btrc_imports(content))

    result = "\n".join(parts)
    _stdlib_source_cache[user_names] = result
    return result
