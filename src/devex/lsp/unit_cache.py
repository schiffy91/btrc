"""Safe, deterministic on-disk cache for parsed LSP stdlib units."""

from __future__ import annotations

import hashlib
import os
import time

from src.compiler.python.ast_codec import decode_ast, encode_ast
from src.compiler.python.cache_io import atomic_write_json, load_json
from src.devex.lsp.units import FileUnit

_SCHEMA_VERSION = 1
_CACHE_PREFIX = "lspunit-"
_CACHE_SUFFIX = ".json"
_LEGACY_SUFFIX = ".pkl"
_MAX_AGE = 30 * 24 * 3600
_pruned_dirs: set[str] = set()


def cache_path(cache_dir: str, unit_version: str, source: str) -> str:
    """Return the content-addressed path for one cache entry."""
    digest = hashlib.sha256()
    for part in (str(_SCHEMA_VERSION), unit_version, source):
        encoded = part.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return os.path.join(cache_dir, f"{_CACHE_PREFIX}{digest.hexdigest()}{_CACHE_SUFFIX}")


def load_unit(path: str, source_path: str, content_hash: str) -> FileUnit | None:
    """Load a validated JSON unit, returning ``None`` for any stale/corrupt entry."""
    payload = load_json(path)
    if not _valid_payload(payload, content_hash):
        return None
    try:
        decls = [decode_ast(value) for value in payload["decls"]]
        if not all(hasattr(decl, "source_file") for decl in decls):
            return None
        absolute_path = os.path.abspath(source_path)
        for decl in decls:
            decl.source_file = absolute_path
        return FileUnit(
            path=absolute_path,
            source="",
            content_hash=content_hash,
            decls=decls,
            defined_names=frozenset(payload["defined_names"]),
        )
    except (ValueError, TypeError, RecursionError):
        return None


def store_unit(path: str, unit: FileUnit) -> None:
    """Atomically write the serializable subset of a parsed unit as JSON."""
    payload = {
        "content_hash": unit.content_hash,
        "decls": [encode_ast(decl) for decl in unit.decls],
        "defined_names": sorted(unit.defined_names),
        "schema": _SCHEMA_VERSION,
    }
    atomic_write_json(path, payload)


def prune_unit_cache(cache_dir: str) -> None:
    """Remove all unsafe legacy pickles and expired JSON entries, once per dir."""
    if cache_dir in _pruned_dirs:
        return
    _pruned_dirs.add(cache_dir)
    cutoff = time.time() - _MAX_AGE
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return
    for name in names:
        if not name.startswith(_CACHE_PREFIX):
            continue
        path = os.path.join(cache_dir, name)
        try:
            if name.endswith(_LEGACY_SUFFIX) or (name.endswith(_CACHE_SUFFIX) and os.path.getmtime(path) < cutoff):
                os.remove(path)
        except OSError:
            pass


def _valid_payload(payload, content_hash: str) -> bool:
    return (
        isinstance(payload, dict)
        and set(payload) == {"content_hash", "decls", "defined_names", "schema"}
        and payload["schema"] == _SCHEMA_VERSION
        and payload["content_hash"] == content_hash
        and isinstance(payload["decls"], list)
        and isinstance(payload["defined_names"], list)
        and all(isinstance(name, str) for name in payload["defined_names"])
    )
