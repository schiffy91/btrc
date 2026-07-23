"""Owned bounded structural inspection of native ``btrcc`` executables."""

from __future__ import annotations

import struct
from typing import BinaryIO

_CHUNK_SIZE = 1024 * 1024
_MAX_BINARY_BYTES = 2 * 1024 * 1024 * 1024
_MAX_HEADER_REGION = 16 * 1024 * 1024
_ELF_HEADER_SIZE = 64
_ELF_PROGRAM_HEADER_SIZE = 56
_MACH_HEADER_SIZE = 32
_PE_MAX_SECTIONS = 96
_UINT32_MAX = (1 << 32) - 1
_UINT64_MAX = (1 << 64) - 1


class InvalidBinary(ValueError):
    """The stream is not a structurally complete supported executable."""


class _BoundedReader:
    """Own monotonic, size-bounded access to one executable stream."""

    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.offset = 0

    def read_exact(self, size: int) -> bytes:
        if size < 0 or self.offset + size > _MAX_BINARY_BYTES:
            raise InvalidBinary
        payload = bytearray()
        while len(payload) < size:
            chunk = self.stream.read(size - len(payload))
            if not chunk:
                raise InvalidBinary
            payload.extend(chunk)
        self.offset += size
        return bytes(payload)

    def skip_to(self, offset: int) -> None:
        if offset < self.offset or offset > _MAX_HEADER_REGION:
            raise InvalidBinary
        remaining = offset - self.offset
        while remaining:
            chunk = self.read_exact(min(_CHUNK_SIZE, remaining))
            remaining -= len(chunk)

    def finish(self) -> int:
        while True:
            remaining = _MAX_BINARY_BYTES - self.offset
            chunk = self.stream.read(min(_CHUNK_SIZE, remaining + 1))
            if not chunk:
                return self.offset
            self.offset += len(chunk)
            if self.offset > _MAX_BINARY_BYTES:
                raise InvalidBinary


class ExecutableFormatInspector:
    """Own structural format detection for one complete binary stream."""

    def __init__(self, stream: BinaryIO) -> None:
        self._reader = _BoundedReader(stream)

    def machine(self, binary_format: str) -> int | None:
        """Return the machine id only for a complete supported executable."""

        try:
            if binary_format == "elf":
                machine = self._elf64_machine()
            elif binary_format == "mach-o":
                machine = self._mach_o64_machine()
            elif binary_format == "pe":
                machine = self._pe32_plus_machine()
            else:
                raise InvalidBinary
        except InvalidBinary:
            machine = None
        try:
            self._reader.finish()
        except InvalidBinary:
            machine = None
        return machine

    @staticmethod
    def _bounded_extent(offset: int, size: int, total: int) -> bool:
        return 0 <= offset <= total and 0 <= size <= total - offset

    @staticmethod
    def _bounded_address_extent(
        offset: int,
        size: int,
        limit: int = _UINT64_MAX,
    ) -> bool:
        """Return whether adding ``size`` to ``offset`` stays representable."""

        return 0 <= offset <= limit and 0 <= size <= limit - offset

    @staticmethod
    def _contains(offset: int, size: int, point: int) -> bool:
        """Return whether ``point`` lies in a non-empty extent."""

        return size > 0 and offset <= point and point - offset < size

    def _elf64_machine(self) -> int:
        reader = self._reader
        header = reader.read_exact(_ELF_HEADER_SIZE)
        values = struct.unpack("<16sHHIQQQIHHHHHH", header)
        ident, kind, machine, version, entry, program_offset, section_offset = values[:7]
        header_size, program_size, program_count, section_size, section_count = values[8:13]
        if (
            ident[:7] != b"\x7fELF\x02\x01\x01"
            or kind not in {2, 3}
            or version != 1
            or entry == 0
            or header_size != _ELF_HEADER_SIZE
            or program_size != _ELF_PROGRAM_HEADER_SIZE
            or not 0 < program_count <= 4096
        ):
            raise InvalidBinary
        program_end = program_offset + program_size * program_count
        if program_offset < _ELF_HEADER_SIZE or program_end > _MAX_HEADER_REGION:
            raise InvalidBinary
        if section_count:
            section_end = section_offset + section_size * section_count
            if section_size != 64 or section_offset < _ELF_HEADER_SIZE or section_end > _MAX_BINARY_BYTES:
                raise InvalidBinary
        elif section_offset or section_size:
            raise InvalidBinary
        reader.skip_to(program_offset)
        file_extents: list[tuple[int, int]] = []
        executable_entry = False
        for _ in range(program_count):
            fields = struct.unpack(
                "<IIQQQQQQ",
                reader.read_exact(program_size),
            )
            (
                segment_kind,
                flags,
                file_offset,
                virtual_address,
                _,
                file_size,
                memory_size,
                _,
            ) = fields
            file_extents.append((file_offset, file_size))
            if segment_kind == 1:
                if file_size > memory_size or not self._bounded_address_extent(
                    virtual_address,
                    memory_size,
                ):
                    raise InvalidBinary
                if flags & 1 and self._contains(
                    virtual_address,
                    file_size,
                    entry,
                ):
                    executable_entry = True
        total = reader.finish()
        if not executable_entry or not all(self._bounded_extent(*extent, total) for extent in file_extents):
            raise InvalidBinary
        if section_count and not self._bounded_extent(
            section_offset,
            section_size * section_count,
            total,
        ):
            raise InvalidBinary
        return machine

    def _mach_o64_machine(self) -> int:
        reader = self._reader
        header = reader.read_exact(_MACH_HEADER_SIZE)
        (
            magic,
            machine,
            _,
            kind,
            command_count,
            command_bytes,
            _,
            reserved,
        ) = struct.unpack("<IIIIIIII", header)
        if (
            magic != 0xFEEDFACF
            or kind != 2
            or reserved != 0
            or not 0 < command_count <= 4096
            or command_bytes < command_count * 8
            or _MACH_HEADER_SIZE + command_bytes > _MAX_HEADER_REGION
        ):
            raise InvalidBinary
        commands = reader.read_exact(command_bytes)
        cursor = 0
        file_extents: list[tuple[int, int]] = []
        executable_extents: list[tuple[int, int]] = []
        main_entry: int | None = None
        for _ in range(command_count):
            if cursor + 8 > len(commands):
                raise InvalidBinary
            command, size = struct.unpack_from("<II", commands, cursor)
            if size < 8 or size % 8 or cursor + size > len(commands):
                raise InvalidBinary
            if command == 0x19:
                if size < 72:
                    raise InvalidBinary
                (
                    virtual_address,
                    virtual_size,
                    file_offset,
                    file_size,
                ) = struct.unpack_from("<QQQQ", commands, cursor + 24)
                _, initial_protection, section_count = struct.unpack_from(
                    "<III",
                    commands,
                    cursor + 56,
                )
                if (
                    size != 72 + section_count * 80
                    or file_size > virtual_size
                    or not self._bounded_address_extent(
                        virtual_address,
                        virtual_size,
                    )
                ):
                    raise InvalidBinary
                file_extents.append((file_offset, file_size))
                if initial_protection & 4:
                    if not virtual_size or not file_size:
                        raise InvalidBinary
                    executable_extents.append((file_offset, file_size))
            elif command == 0x80000028:
                if size != 24:
                    raise InvalidBinary
                main_entry = struct.unpack_from(
                    "<Q",
                    commands,
                    cursor + 8,
                )[0]
                file_extents.append((main_entry, 1))
            cursor += size
        total = reader.finish()
        if (
            cursor != len(commands)
            or not executable_extents
            or not main_entry
            or not any(self._contains(offset, size, main_entry) for offset, size in executable_extents)
            or not all(self._bounded_extent(*extent, total) for extent in file_extents)
        ):
            raise InvalidBinary
        return machine

    def _pe32_plus_machine(self) -> int:
        reader = self._reader
        dos_header = reader.read_exact(64)
        pe_offset = struct.unpack_from("<I", dos_header, 0x3C)[0]
        if dos_header[:2] != b"MZ" or pe_offset < 64 or pe_offset > 1024 * 1024 or pe_offset % 4:
            raise InvalidBinary
        reader.skip_to(pe_offset)
        signature_and_coff = reader.read_exact(24)
        (
            machine,
            section_count,
            _,
            symbol_offset,
            symbol_count,
            optional_size,
            characteristics,
        ) = struct.unpack_from("<HHIIIHH", signature_and_coff, 4)
        if (
            signature_and_coff[:4] != b"PE\0\0"
            or not 0 < section_count <= _PE_MAX_SECTIONS
            or optional_size < 112
            or optional_size > 4096
            or not characteristics & 0x0002
            or characteristics & 0x2000
        ):
            raise InvalidBinary
        optional = reader.read_exact(optional_size)
        magic = struct.unpack_from("<H", optional)[0]
        entrypoint = struct.unpack_from("<I", optional, 16)[0]
        image_size, header_size = struct.unpack_from("<II", optional, 56)
        subsystem = struct.unpack_from("<H", optional, 68)[0]
        directory_count = struct.unpack_from("<I", optional, 108)[0]
        if (
            magic != 0x20B
            or not entrypoint
            or not image_size
            or subsystem != 3
            or 112 + directory_count * 8 > optional_size
        ):
            raise InvalidBinary
        section_table_end = reader.offset + section_count * 40
        if section_table_end > _MAX_HEADER_REGION or header_size < section_table_end:
            raise InvalidBinary
        file_extents: list[tuple[int, int]] = []
        executable_entry = False
        for _ in range(section_count):
            section = reader.read_exact(40)
            virtual_size, virtual_address, raw_size, raw_offset = struct.unpack_from(
                "<IIII",
                section,
                8,
            )
            section_flags = struct.unpack_from("<I", section, 36)[0]
            file_extents.append((raw_offset, raw_size))
            mapped_size = max(virtual_size, raw_size)
            if (
                not self._bounded_address_extent(
                    virtual_address,
                    mapped_size,
                    _UINT32_MAX,
                )
                or virtual_address > image_size
                or mapped_size > image_size - virtual_address
            ):
                raise InvalidBinary
            if section_flags & 0x20000000 and self._contains(
                virtual_address,
                raw_size,
                entrypoint,
            ):
                executable_entry = True
        total = reader.finish()
        if (
            not executable_entry
            or header_size > total
            or not all(size == 0 or self._bounded_extent(offset, size, total) for offset, size in file_extents)
            or (
                symbol_count
                and not self._bounded_extent(
                    symbol_offset,
                    symbol_count * 18,
                    total,
                )
            )
        ):
            raise InvalidBinary
        return machine


__all__ = ["ExecutableFormatInspector", "InvalidBinary"]
