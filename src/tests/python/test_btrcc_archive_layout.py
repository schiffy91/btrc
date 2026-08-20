"""Regression contracts for exact release-archive physical layout."""

from __future__ import annotations

import ast
import gzip
import struct
import tarfile
import zipfile
from pathlib import Path

import pytest

import src.compiler.python.artifacts.archive as archive_validation_module
from src.compiler.python.artifacts.archive import ArchiveCodec
from src.compiler.python.artifacts.selfhost import SelfhostBundleBuilder, SelfhostBundleValidator

ARCHIVE_CODEC = ArchiveCodec()
write_checksum = ARCHIVE_CODEC.write_checksum
from src.tests.python.test_btrcc_bundle import _fixture


def test_bundle_archive_validation_behavior_has_one_explicit_owner() -> None:
    module = ast.parse(Path(archive_validation_module.__file__).read_text())
    loose_behavior = [node.name for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "ArchiveValidator")
    operations = {node.name for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

    assert loose_behavior == []
    assert {
        "validate",
        "_validate_tar",
        "_validate_zip",
        "_canonical_member",
        "_hash_bounded",
        "_validate_names",
    } <= operations


def _bundle(tmp_path: Path, target: str):
    source_root, binary = _fixture(tmp_path / "source", target)
    return SelfhostBundleBuilder().build(
        binary=binary,
        target=target,
        output_dir=tmp_path / "dist",
        source_root=source_root,
    )


def _validate(result) -> None:
    SelfhostBundleValidator().validate_generation(
        result.bundle,
        result.archive,
        result.checksum,
        result.bundle.name,
        result.archive.name,
    )


def _write_tar_payload(path: Path, payload: bytes, modified_time: int = 0) -> None:
    with (
        path.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=modified_time) as compressed,
    ):
        compressed.write(payload)


def _set_tar_header_checksum(payload: bytearray, offset: int) -> None:
    payload[offset + 148 : offset + 156] = b"        "
    checksum = sum(payload[offset : offset + tarfile.BLOCKSIZE])
    payload[offset + 148 : offset + 156] = f"{checksum:06o}\0 ".encode("ascii")


@pytest.mark.parametrize("target", ["linux-x64", "windows-x64"])
def test_rechecksummed_archive_rejects_appended_polyglot_bytes(tmp_path: Path, target: str) -> None:
    result = _bundle(tmp_path, target)
    with result.archive.open("ab") as stream:
        stream.write(b"polyglot-trailer")
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_tar_rejects_a_concatenated_gzip_member(tmp_path: Path) -> None:
    result = _bundle(tmp_path, "linux-x64")
    with result.archive.open("ab") as stream:
        stream.write(gzip.compress(b"polyglot-member", mtime=0))
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_tar_rejects_data_after_canonical_end_blocks(tmp_path: Path) -> None:
    result = _bundle(tmp_path, "linux-x64")
    expanded = gzip.decompress(result.archive.read_bytes()) + bytes(512)
    _write_tar_payload(result.archive, expanded)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_tar_rejects_nonzero_member_padding(tmp_path: Path) -> None:
    result = _bundle(tmp_path, "linux-x64")
    expanded = bytearray(gzip.decompress(result.archive.read_bytes()))
    with tarfile.open(result.archive, "r:gz") as archive:
        member = next(entry for entry in archive.getmembers() if entry.isfile() and entry.size % tarfile.BLOCKSIZE)
    expanded[member.offset_data + member.size] = 0xA5
    _write_tar_payload(result.archive, expanded)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_tar_rejects_noncanonical_raw_header(tmp_path: Path) -> None:
    result = _bundle(tmp_path, "linux-x64")
    with tarfile.open(result.archive, "r:gz") as archive:
        offset = archive.getmembers()[0].offset
    expanded = bytearray(gzip.decompress(result.archive.read_bytes()))
    assert expanded[offset + 263 : offset + 265] == b"00"
    expanded[offset + 263 : offset + 265] = b"\0\0"
    _set_tar_header_checksum(expanded, offset)
    _write_tar_payload(result.archive, expanded)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_tar_rejects_consistent_wrong_timestamp(tmp_path: Path) -> None:
    result = _bundle(tmp_path, "linux-x64")
    with tarfile.open(result.archive, "r:gz") as archive:
        offsets = [member.offset for member in archive.getmembers()]
    expanded = bytearray(gzip.decompress(result.archive.read_bytes()))
    for offset in offsets:
        expanded[offset + 136 : offset + 148] = b"00000000001\0"
        _set_tar_header_checksum(expanded, offset)
    _write_tar_payload(result.archive, expanded, modified_time=1)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical"):
        _validate(result)


@pytest.mark.parametrize(
    ("offset", "replacement"),
    [(4, b"\x01\x00\x00\x00"), (8, b"\x00"), (9, b"\x03")],
)
def test_rechecksummed_tar_rejects_noncanonical_gzip_metadata(
    tmp_path: Path,
    offset: int,
    replacement: bytes,
) -> None:
    result = _bundle(tmp_path, "linux-x64")
    payload = bytearray(result.archive.read_bytes())
    payload[offset : offset + len(replacement)] = replacement
    result.archive.write_bytes(payload)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_zip_rejects_a_self_extracting_prefix(tmp_path: Path) -> None:
    result = _bundle(tmp_path, "windows-x64")
    result.archive.write_bytes(b"MZ-polyglot-prefix" + result.archive.read_bytes())
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_zip_rejects_an_archive_comment(tmp_path: Path) -> None:
    result = _bundle(tmp_path, "windows-x64")
    with zipfile.ZipFile(result.archive, "a") as archive:
        archive.comment = b"polyglot-comment"
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_zip_rejects_local_central_timestamp_mismatch(
    tmp_path: Path,
) -> None:
    result = _bundle(tmp_path, "windows-x64")
    with zipfile.ZipFile(result.archive) as archive:
        local_headers = [entry.header_offset for entry in archive.infolist()]
    payload = bytearray(result.archive.read_bytes())
    for offset in local_headers:
        # Keep every local timestamp mutually consistent while changing it from
        # the central directory's canonical 1980-01-01 timestamp to 1981-01-01.
        struct.pack_into("<HH", payload, offset + 10, 0, 0x0221)
    result.archive.write_bytes(payload)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_zip_rejects_consistent_wrong_timestamp(tmp_path: Path) -> None:
    result = _bundle(tmp_path, "windows-x64")
    with zipfile.ZipFile(result.archive) as archive:
        entries = archive.infolist()
        central_offset = archive.start_dir
    payload = bytearray(result.archive.read_bytes())
    for entry in entries:
        struct.pack_into("<HH", payload, entry.header_offset + 10, 0, 0x0221)
    cursor = central_offset
    for _entry in entries:
        assert payload[cursor : cursor + 4] == b"PK\x01\x02"
        struct.pack_into("<HH", payload, cursor + 12, 0, 0x0221)
        name_size, extra_size, comment_size = struct.unpack_from("<HHH", payload, cursor + 28)
        cursor += 46 + name_size + extra_size + comment_size
    result.archive.write_bytes(payload)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical"):
        _validate(result)


@pytest.mark.parametrize(
    ("field_offset", "replacement"),
    [
        (4, b"\x15"),
        (6, b"\x15"),
        (7, b"\x01"),
        (34, b"\x01\x00"),
        (36, b"\x01\x00"),
        (38, b"\x00\x00"),
    ],
    ids=[
        "create-version",
        "extract-version",
        "reserved",
        "volume",
        "internal-attributes",
        "external-dos-attributes",
    ],
)
def test_rechecksummed_zip_rejects_noncanonical_central_metadata(
    tmp_path: Path,
    field_offset: int,
    replacement: bytes,
) -> None:
    result = _bundle(tmp_path, "windows-x64")
    with zipfile.ZipFile(result.archive) as archive:
        central_offset = archive.start_dir
    payload = bytearray(result.archive.read_bytes())
    assert payload[central_offset : central_offset + 4] == b"PK\x01\x02"
    payload[central_offset + field_offset : central_offset + field_offset + len(replacement)] = replacement
    result.archive.write_bytes(payload)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)


def test_rechecksummed_zip_rejects_noncanonical_local_extract_version(
    tmp_path: Path,
) -> None:
    result = _bundle(tmp_path, "windows-x64")
    with zipfile.ZipFile(result.archive) as archive:
        local_offset = archive.infolist()[0].header_offset
    payload = bytearray(result.archive.read_bytes())
    payload[local_offset + 4] = 21
    result.archive.write_bytes(payload)
    write_checksum(result.archive)

    with pytest.raises(ValueError, match="noncanonical physical layout"):
        _validate(result)
