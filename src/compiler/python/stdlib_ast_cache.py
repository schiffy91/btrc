"""Safe persistent cache for parsed standard-library AST declarations."""

from __future__ import annotations

import hashlib
import os
import time

from .ast_codec import decode_ast, encode_ast
from .cache_io import atomic_write_json, load_json

SCHEMA_VERSION = 1
_PREFIX = "stdlib-"
_SUFFIX = ".ast.json"
_LEGACY_SUFFIX = ".ast"
_MAX_AGE = 30 * 24 * 3600
_pruned_dirs: set[str] = set()


def cache_path(cache_dir: str, frontend_version: str, source: str) -> str:
    """Return a content-addressed path covering schema, frontend, and source."""
    digest = hashlib.sha256()
    for part in (str(SCHEMA_VERSION), frontend_version, source):
        encoded = part.encode()
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return os.path.join(cache_dir, f"{_PREFIX}{digest.hexdigest()}{_SUFFIX}")


def load_declarations(path: str, content_hash: str) -> list | None:
    """Load validated declarations, or return ``None`` to request a reparse."""
    payload = load_json(path)
    if not _valid_payload(payload, content_hash):
        return None
    try:
        declarations = [decode_ast(value) for value in payload["declarations"]]
    except (ValueError, TypeError, RecursionError):
        return None
    if not all(hasattr(decl, "source_file") for decl in declarations):
        return None
    return declarations


def store_declarations(path: str, content_hash: str, declarations: list) -> None:
    """Atomically store declarations in the deterministic JSON schema."""
    atomic_write_json(
        path,
        {
            "content_hash": content_hash,
            "declarations": [encode_ast(decl) for decl in declarations],
            "schema": SCHEMA_VERSION,
        },
    )


def prune_cache(cache_dir: str) -> None:
    """Remove unsafe legacy pickles immediately and expired JSON entries."""
    if cache_dir in _pruned_dirs:
        return
    _pruned_dirs.add(cache_dir)
    cutoff = time.time() - _MAX_AGE
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return
    for name in names:
        if not name.startswith(_PREFIX):
            continue
        path = os.path.join(cache_dir, name)
        try:
            if name.endswith(_LEGACY_SUFFIX) or (name.endswith(_SUFFIX) and os.path.getmtime(path) < cutoff):
                os.remove(path)
        except OSError:
            pass


def source_hash(source: str) -> str:
    return hashlib.sha256(source.encode()).hexdigest()


def _valid_payload(payload, content_hash: str) -> bool:
    return (
        isinstance(payload, dict)
        and set(payload) == {"content_hash", "declarations", "schema"}
        and payload["schema"] == SCHEMA_VERSION
        and payload["content_hash"] == content_hash
        and isinstance(payload["declarations"], list)
    )
