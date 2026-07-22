"""Canonical physical-layout checks for published bundle archives."""

from __future__ import annotations

import stat
import struct
import tarfile
import zipfile
import zlib
from dataclasses import dataclass
from typing import BinaryIO

_CHUNK_SIZE = 1024 * 1024
_MAX_TAR_BYTES = 2 * 1024 * 1024 * 1024
_TAR_RECORD_SIZE = 20 * tarfile.BLOCKSIZE
_TAR_TAIL_SIZE = 2 * _TAR_RECORD_SIZE
_ZIP_VERSION = 20


def _invalid() -> ValueError:
    return ValueError("bundle archive is not a valid tar or ZIP file: noncanonical physical layout")


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    payload = bytearray()
    while len(payload) < size:
        chunk = stream.read(size - len(payload))
        if not chunk:
            raise _invalid()
        payload.extend(chunk)
    return bytes(payload)


@dataclass(frozen=True)
class GzipLayout:
    uncompressed_size: int
    tail: bytes
    modified_time: int


def validate_gzip_layout(stream: BinaryIO) -> GzipLayout:
    """Require the exact single-member gzip shape emitted by ``GzipFile``."""

    header = _read_exact(stream, 10)
    if header[:3] != b"\x1f\x8b\x08" or header[3] != 0 or header[8] != 2 or header[9] != 0xFF:
        raise _invalid()
    modified_time = struct.unpack_from("<I", header, 4)[0]
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    total = 0
    tail = b""

    def consume(decoded: bytes) -> None:
        nonlocal total, tail
        total += len(decoded)
        if total > _MAX_TAR_BYTES:
            raise _invalid()
        tail = (tail + decoded)[-_TAR_TAIL_SIZE:]

    def feed(encoded: bytes) -> None:
        pending = encoded
        while pending:
            decoded = inflater.decompress(pending, _CHUNK_SIZE)
            consume(decoded)
            if inflater.unused_data:
                raise _invalid()
            pending = inflater.unconsumed_tail

    try:
        feed(header)
        while chunk := stream.read(_CHUNK_SIZE):
            if inflater.eof:
                raise _invalid()
            feed(chunk)
        consume(inflater.flush())
    except zlib.error as error:
        raise _invalid() from error
    if not inflater.eof or inflater.unused_data:
        raise _invalid()
    return GzipLayout(total, tail, modified_time)


def validate_tar_end(layout: GzipLayout, logical_end: int, modified_time: int) -> None:
    """Require two end blocks and only writer-added record padding."""

    padded_end = ((logical_end + 2 * tarfile.BLOCKSIZE + _TAR_RECORD_SIZE - 1) // _TAR_RECORD_SIZE) * _TAR_RECORD_SIZE
    tail_start = layout.uncompressed_size - len(layout.tail)
    if (
        padded_end != layout.uncompressed_size
        or modified_time != layout.modified_time
        or logical_end < tail_start
        or any(layout.tail[logical_end - tail_start :])
    ):
        raise _invalid()


def validate_tar_member_padding(
    stream: BinaryIO,
    extents: list[tuple[int, int]],
) -> None:
    """Require every file's alignment padding to remain zero-filled."""

    for offset, size in extents:
        stream.seek(offset)
        if any(_read_exact(stream, size)):
            raise _invalid()


def validate_tar_headers(
    stream: BinaryIO,
    headers: list[tuple[int, int, bytes]],
) -> None:
    """Require each raw header span to match the canonical PAX encoding."""

    for offset, data_offset, expected in headers:
        if data_offset - offset != len(expected):
            raise _invalid()
        stream.seek(offset)
        if _read_exact(stream, len(expected)) != expected:
            raise _invalid()


def _encoded_name(entry: zipfile.ZipInfo) -> bytes:
    encoding = "utf-8" if entry.flag_bits & 0x800 else "cp437"
    try:
        encoded = entry.filename.encode(encoding)
    except UnicodeError as error:
        raise _invalid() from error
    return encoded


def validate_zip_layout(
    stream: BinaryIO,
    archive: zipfile.ZipFile,
    entries: list[zipfile.ZipInfo],
    expected_modes: dict[str, int],
    expected_timestamp: tuple[int, int, int, int, int, int],
) -> None:
    """Reject ZIP prefixes, trailers, comments, descriptors, and layout gaps."""

    stream.seek(0, 2)
    archive_size = stream.tell()
    if archive_size < 22:
        raise _invalid()
    stream.seek(archive_size - 22)
    eocd = struct.unpack("<IHHHHIIH", _read_exact(stream, 22))
    signature, disk, central_disk, disk_entries, entry_count, central_size, central_offset, comment_size = eocd
    if (
        signature != 0x06054B50
        or disk
        or central_disk
        or disk_entries != len(entries)
        or entry_count != len(entries)
        or comment_size
        or central_offset + central_size != archive_size - 22
        or archive.start_dir != central_offset
    ):
        raise _invalid()
    cursor = 0
    central_expected = 0
    year, month, day, hour, minute, second = expected_timestamp
    expected_time = (hour << 11) | (minute << 5) | (second // 2)
    expected_date = ((year - 1980) << 9) | (month << 5) | day
    for entry in entries:
        encoded_name = _encoded_name(entry)
        year, month, day, hour, minute, second = entry.date_time
        central_time = (hour << 11) | (minute << 5) | (second // 2)
        central_date = ((year - 1980) << 9) | (month << 5) | day
        expected_mode = expected_modes.get(entry.filename)
        expected_type = stat.S_IFDIR if entry.is_dir() else stat.S_IFREG
        expected_dos_attributes = 0x10 if entry.is_dir() else 0
        expected_external_attributes = (
            ((expected_type | expected_mode) & 0xFFFF) << 16 | expected_dos_attributes
            if expected_mode is not None
            else None
        )
        if (
            entry.header_offset != cursor
            or entry.date_time != expected_timestamp
            or entry.flag_bits & ~0x800
            or entry.compress_type != zipfile.ZIP_DEFLATED
            or entry.create_system != 3
            or entry.create_version != _ZIP_VERSION
            or entry.extract_version != _ZIP_VERSION
            or entry.reserved
            or entry.volume
            or entry.internal_attr
            or entry.external_attr != expected_external_attributes
            or entry.extra
            or entry.comment
        ):
            raise _invalid()
        stream.seek(cursor)
        local = struct.unpack("<IHHHHHIIIHH", _read_exact(stream, 30))
        local_signature, local_version, flags, method, modified_time, modified_date = local[:6]
        crc, compressed_size, file_size, name_size, extra_size = local[6:]
        local_name = _read_exact(stream, name_size)
        if (
            local_signature != 0x04034B50
            or local_version != _ZIP_VERSION
            or flags != entry.flag_bits
            or method != entry.compress_type
            or (modified_date, modified_time) != (expected_date, expected_time)
            or (modified_date, modified_time) != (central_date, central_time)
            or crc != entry.CRC
            or compressed_size != entry.compress_size
            or file_size != entry.file_size
            or local_name != encoded_name
            or extra_size
        ):
            raise _invalid()
        cursor += 30 + name_size + entry.compress_size
        central_expected += 46 + len(encoded_name)
    if cursor != central_offset or central_expected != central_size:
        raise _invalid()
