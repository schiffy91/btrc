"""Bounded, deterministic UTF-8 reads for btrc source files."""

from __future__ import annotations

MAX_SOURCE_BYTES = 64 * 1024 * 1024


class SourceReadError(OSError):
    """A source file could not be read under the compiler's input contract."""


def read_source(path: str) -> str:
    """Read one bounded UTF-8 source file and normalize universal newlines."""
    try:
        with open(path, "rb") as source_file:
            encoded = source_file.read(MAX_SOURCE_BYTES + 1)
    except FileNotFoundError as error:
        raise SourceReadError(f"source file {path!r} not found") from error
    except OSError as error:
        raise SourceReadError(f"cannot read source file {path!r}: {error}") from error
    if len(encoded) > MAX_SOURCE_BYTES:
        raise SourceReadError(f"source file {path!r} exceeds the {MAX_SOURCE_BYTES}-byte limit")
    try:
        text = encoded.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceReadError(f"source file {path!r} is not valid UTF-8 at byte {error.start}") from error
    nul = text.find("\0")
    if nul >= 0:
        raise SourceReadError(f"source file {path!r} contains a NUL byte at character {nul}")
    return text.replace("\r\n", "\n").replace("\r", "\n")
