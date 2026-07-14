"""Bounded JSON reads and crash-safe atomic writes for compiler caches."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress

DEFAULT_MAX_JSON_BYTES = 64 * 1024 * 1024


def load_json(path: str, max_bytes: int = DEFAULT_MAX_JSON_BYTES):
    """Read bounded strict JSON, returning ``None`` for missing/corrupt data."""
    try:
        with open(path, "rb") as cache_file:
            encoded = cache_file.read(max_bytes + 1)
        if len(encoded) > max_bytes:
            return None
        return json.loads(
            encoded.decode("utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
        return None


def atomic_write_json(path: str, payload) -> None:
    """Serialize deterministic JSON and atomically replace ``path``."""
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    atomic_write_text(path, encoded)


def atomic_write_text(path: str, content: str) -> None:
    """Write text durably before an atomic same-directory replacement."""
    cache_dir = os.path.dirname(path) or "."
    os.makedirs(cache_dir, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".btrc-cache-", dir=cache_dir)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as cache_file:
            cache_file.write(content)
            cache_file.flush()
            os.fsync(cache_file.fileno())
        os.replace(temporary_path, path)
    finally:
        with suppress(FileNotFoundError):
            os.remove(temporary_path)


def _reject_json_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")
