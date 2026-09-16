"""The generated root-stdlib symbol index is current, trusted only when it matches, and shared."""

from __future__ import annotations

import os
import shutil
import zlib
from pathlib import Path

from src.compiler.python.frontend import symbol_index
from src.compiler.python.frontend.sources import SourceDependencyGraph, StdlibRepository

REPO = Path(__file__).resolve().parents[3]
STDLIB = REPO / "src/stdlib"


def _canonical(root: str, owners: dict[str, set[str]]) -> dict[str, frozenset[str]]:
    return {
        name: frozenset(SourceDependencyGraph.canonical_file(os.path.join(root, relative)) for relative in relatives)
        for name, relatives in owners.items()
    }


def _copy_root_stdlib(destination: Path) -> Path:
    destination.mkdir()
    for entry in STDLIB.iterdir():
        if entry.is_file() and entry.suffix in {".btrc", ".toml", ".lock", ".symbols"}:
            shutil.copy(entry, destination / entry.name)
    return destination


def test_digest_uses_zlib_crc32_over_names_and_bytes() -> None:
    assert zlib.crc32(b"123456789") == 0xCBF43926
    digest = symbol_index.snapshot_digest([("A.btrc", b"one"), ("B.btrc", b"two")])
    crc = zlib.crc32(b"A.btrc\0one\0B.btrc\0two\0")
    assert digest == f"{crc:08x}-6-2"


def test_committed_index_is_current_and_used() -> None:
    sources = StdlibRepository()
    rendered = sources.render_symbol_index()
    assert (STDLIB / symbol_index.INDEX_FILE_NAME).read_text(encoding="utf-8") == rendered
    loaded = symbol_index.load(str(STDLIB), sources.symbol_index_digest())
    assert loaded is not None
    assert sources.symbol_files() == _canonical(str(STDLIB), loaded)
    assert sources.symbol_files() == _canonical(str(STDLIB), sources.parsed_symbol_owners())
    assert "Vector" in sources.symbol_files()


def test_index_is_consulted_only_when_its_digest_matches(tmp_path: Path) -> None:
    root = _copy_root_stdlib(tmp_path / "stdlib")
    index = root / symbol_index.INDEX_FILE_NAME
    lines = index.read_text(encoding="utf-8").split("\n")
    header = lines[0]
    # A current index is authoritative: dropping a line changes the answer.
    index.write_text("\n".join(line for line in lines if not line.startswith("Vector\t")), encoding="utf-8")
    assert "Vector" not in StdlibRepository(directory=str(root)).symbol_files()
    # A stale digest is ignored and the modules are parsed instead.
    stale = header.replace(header.split(" ")[2][:8], "00000000")
    index.write_text("\n".join([stale, *lines[1:]]), encoding="utf-8")
    assert "Vector" in StdlibRepository(directory=str(root)).symbol_files()
    # A missing index parses too, and nothing writes one back.
    index.unlink()
    assert "Vector" in StdlibRepository(directory=str(root)).symbol_files()
    assert not index.exists()


def test_malformed_index_lines_are_rejected() -> None:
    digest = "deadbeef-1-1"
    assert symbol_index.parse(f"{symbol_index.FORMAT_TAG} {digest}\nName\t../Escape.btrc\n", digest) is None
    assert symbol_index.parse(f"{symbol_index.FORMAT_TAG} {digest}\nName\tsub/File.btrc\n", digest) is None
    assert symbol_index.parse(f"{symbol_index.FORMAT_TAG} {digest}\nName File.btrc\n", digest) is None
    assert symbol_index.parse(f"{symbol_index.FORMAT_TAG} other\n", digest) is None
    assert symbol_index.parse(f"{symbol_index.FORMAT_TAG} {digest}\nName\tFile.btrc\n", digest) == {
        "Name": {"File.btrc"}
    }
