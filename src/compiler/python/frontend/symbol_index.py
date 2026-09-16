"""The generated root-stdlib symbol index, ``btrc.symbols``.

Strict import visibility must know which root stdlib module owns every
canonical stdlib symbol, whether or not that module was imported into the
program being compiled. Deriving that map means parsing the whole root stdlib,
which costs either compiler more than compiling a typical program. The index
is therefore generated beside the stdlib (``tools.compiler_codegen generate``)
and validated against a digest of the files it was derived from; a missing or
stale index falls back to parsing, never to guessing, and nothing is written
at compile time.

The digest is CRC-32 (zlib semantics) over each root module's file name, a
zero byte, its raw bytes and a zero byte, in discovery order, followed by the
byte and file counts. The self-hosted compiler computes the same digest in
``src/compiler/btrc/frontend/Stdlib.btrc``.
"""

from __future__ import annotations

import os
import zlib
from collections.abc import Iterable, Mapping

INDEX_FILE_NAME = "btrc.symbols"
FORMAT_TAG = "btrc-symbols 1"


def snapshot_digest(entries: Iterable[tuple[str, bytes]]) -> str:
    """Digest ``(file name, raw bytes)`` pairs in discovery order."""

    crc = 0
    byte_count = 0
    file_count = 0
    for name, content in entries:
        crc = zlib.crc32(name.encode("utf-8"), crc)
        crc = zlib.crc32(b"\0", crc)
        crc = zlib.crc32(content, crc)
        crc = zlib.crc32(b"\0", crc)
        byte_count += len(content)
        file_count += 1
    return f"{crc & 0xFFFFFFFF:08x}-{byte_count}-{file_count}"


def render(digest: str, owners: Mapping[str, Iterable[str]]) -> str:
    """Render one index: a header line, then ``symbol<TAB>file`` lines, sorted."""

    lines = [f"{FORMAT_TAG} {digest}"]
    for name in sorted(owners):
        for relative in sorted(set(owners[name])):
            lines.append(f"{name}\t{relative}")
    return "\n".join(lines) + "\n"


def parse(text: str, digest: str) -> dict[str, set[str]] | None:
    """Return the owners recorded for ``digest``, or None when the index is stale or malformed."""

    header, separator, body = text.partition("\n")
    if not separator or header != f"{FORMAT_TAG} {digest}":
        return None
    owners: dict[str, set[str]] = {}
    for line in body.split("\n"):
        if not line:
            continue
        name, tab, relative = line.partition("\t")
        if not tab or not name or not relative or "/" in relative or "\\" in relative or relative.startswith("."):
            return None
        owners.setdefault(name, set()).add(relative)
    return owners


def load(root: str, digest: str) -> dict[str, set[str]] | None:
    """Load the index beside the root stdlib at ``root`` when it matches ``digest``."""

    try:
        with open(os.path.join(root, INDEX_FILE_NAME), "rb") as index_file:
            text = index_file.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return parse(text, digest)
