"""Build-time admission and immutable metadata for a Windows daemon image."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path


class SupervisorImage:
    """Check the loader's PE data, including after an optional signing step."""

    SYSTEM_DLLS = frozenset(
        {
            "advapi32.dll",
            "bcrypt.dll",
            "kernel32.dll",
            "kernelbase.dll",
            "msvcrt.dll",
            "ntdll.dll",
            "ucrtbase.dll",
            "ws2_32.dll",
        }
    )

    def __init__(self, path: Path, architecture: str) -> None:
        self.data = path.read_bytes()
        self.path = path
        if self.data[:2] != b"MZ":
            raise ValueError("supervisor is not a PE image")
        pe = self.integer(60, 4)
        if pe < 64 or self.bytes(pe, 4) != b"PE\0\0":
            raise ValueError("supervisor has an invalid PE header")
        machine = self.integer(pe + 4, 2)
        if machine != {"x86_64": 0x8664, "aarch64": 0xAA64}.get(architecture):
            raise ValueError("supervisor machine does not match its target ABI")
        optional_size = self.integer(pe + 20, 2)
        optional = pe + 24
        if optional_size < 240 or self.integer(optional, 2) != 0x20B:
            raise ValueError("supervisor requires a complete PE32+ optional header")
        self.bytes(optional, optional_size)
        if self.integer(optional + 108, 4) < 16:
            raise ValueError("supervisor lacks PE data directories")
        self.header_size = self.integer(optional + 60, 4)
        self.directories = optional + 112
        self.sections = []
        for index in range(self.integer(pe + 6, 2)):
            section = optional + optional_size + index * 40
            self.bytes(section, 40)
            self.sections.append(
                (self.integer(section + 12, 4), self.integer(section + 16, 4), self.integer(section + 20, 4))
            )

    def bytes(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0 or offset + size > len(self.data):
            raise ValueError("supervisor PE data is truncated")
        return self.data[offset : offset + size]

    def integer(self, offset: int, size: int) -> int:
        return int.from_bytes(self.bytes(offset, size), "little")

    def offset(self, rva: int, size: int) -> int:
        matches = [
            raw + rva - start for start, length, raw in self.sections if start <= rva and rva + size <= start + length
        ]
        if 0 <= rva < self.header_size and rva + size <= self.header_size:
            matches.append(rva)
        if len(matches) != 1:
            raise ValueError("supervisor PE address is missing or ambiguous")
        self.bytes(matches[0], size)
        return matches[0]

    def directory(self, index: int) -> tuple[int, int]:
        return struct.unpack("<II", self.bytes(self.directories + index * 8, 8))

    def qualify(self) -> dict[str, object]:
        rva, size = self.directory(10)
        if not rva or size < 80:
            raise ValueError("supervisor lacks the System32 loader configuration")
        config = self.offset(rva, size)
        if self.integer(config, 4) < 80 or self.integer(config, 4) > size:
            raise ValueError("supervisor load configuration has an invalid size")
        if self.integer(config + 78, 2) != 0x800:
            raise ValueError("supervisor dependent DLL loading must select only System32")
        if any(self.directory(13)):
            raise ValueError("supervisor must not have delay-loaded DLL dependencies")
        rva, size = self.directory(1)
        imports = []
        if rva or size:
            if not rva or size < 20:
                raise ValueError("supervisor import directory is invalid")
            start = self.offset(rva, size)
            for position in range(0, size - 19, 20):
                record = self.bytes(start + position, 20)
                if not any(record):
                    break
                name_rva = struct.unpack_from("<I", record, 12)[0]
                name_bytes = bytearray()
                for index in range(256):
                    byte = self.integer(self.offset(name_rva + index, 1), 1)
                    if not byte:
                        break
                    name_bytes.append(byte)
                else:
                    raise ValueError("supervisor imported DLL name is unterminated")
                try:
                    name = name_bytes.decode("ascii").lower()
                except UnicodeError as error:
                    raise ValueError("supervisor imported DLL name is not ASCII") from error
                api_set = name.startswith(
                    ("api-ms-win-core-", "api-ms-win-crt-", "api-ms-win-security-")
                ) and name.endswith(".dll")
                if (
                    not name
                    or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for character in name)
                    or (name not in self.SYSTEM_DLLS and not api_set)
                ):
                    raise ValueError(f"supervisor has a non-system DLL dependency: {name!r}")
                imports.append(name)
            else:
                raise ValueError("supervisor import directory is unterminated")
        return {"sha256": hashlib.sha256(self.data).hexdigest(), "dependent_load_flags": 0x800, "imports": imports}

    @staticmethod
    def c_string(value: str) -> str:
        return '"' + "".join(f"\\{byte:03o}" for byte in value.encode("utf-8")) + '"'

    def metadata(self, abi: str, basename: str, protocol: int) -> str:
        digest = ", ".join(f"0x{byte:02x}" for byte in hashlib.sha256(self.data).digest())
        return (
            "#include <stddef.h>\n#include <stdint.h>\n"
            '#include "windows_os.h"\n#include "windows_daemon_image.h"\n'
            "const __btrc_windows_daemon_metadata_t __btrc_windows_daemon_metadata = {\n"
            f"    {{ {digest} }}, {protocol}, {self.c_string(abi)}, {self.c_string(basename)}\n"
            "};\n"
        )

    @staticmethod
    def load_configuration() -> str:
        # Zig's GNU driver cannot forward --dependent-load-flag. Emit the same
        # PE field as data and require qualify() to prove the finished image.
        return (
            "#include <windows.h>\n"
            "const IMAGE_LOAD_CONFIG_DIRECTORY64 _load_config_used = {\n"
            "    .Size = sizeof(IMAGE_LOAD_CONFIG_DIRECTORY64),\n"
            "    .DependentLoadFlags = LOAD_LIBRARY_SEARCH_SYSTEM32\n"
            "};\n"
        )
