"""Bounded UTF-8 TOML reads for package manifests."""

from __future__ import annotations

import tomllib

MAX_MANIFEST_BYTES = 1024 * 1024


def load_manifest(path: str) -> dict:
    """Load one manifest without allowing unbounded input allocation."""
    with open(path, "rb") as manifest_file:
        encoded = manifest_file.read(MAX_MANIFEST_BYTES + 1)
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError(f"package manifest '{path}' exceeds the {MAX_MANIFEST_BYTES}-byte limit")
    try:
        text = encoded.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"package manifest '{path}' is not valid UTF-8 at byte {error.start}") from error
    try:
        manifest = tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError) as error:
        raise ValueError(f"cannot parse package manifest '{path}': {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"package manifest '{path}' must contain a TOML table")
    return manifest


__all__ = ["MAX_MANIFEST_BYTES", "load_manifest"]
