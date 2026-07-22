"""Small structurally complete native executable fixtures."""

from __future__ import annotations

import struct


def _elf64(machine: int) -> bytes:
    payload = bytearray(128)
    ident = b"\x7fELF\x02\x01\x01" + bytes(9)
    struct.pack_into(
        "<16sHHIQQQIHHHHHH",
        payload,
        0,
        ident,
        2,
        machine,
        1,
        0x400078,
        64,
        0,
        0,
        64,
        56,
        1,
        0,
        0,
        0,
    )
    struct.pack_into(
        "<IIQQQQQQ",
        payload,
        64,
        1,
        5,
        0,
        0x400000,
        0x400000,
        len(payload),
        len(payload),
        0x1000,
    )
    payload[120:] = b"BTRCELF!"
    return bytes(payload)


def _mach_o64(machine: int) -> bytes:
    payload = bytearray(144)
    struct.pack_into("<IIIIIIII", payload, 0, 0xFEEDFACF, machine, 0, 2, 2, 96, 0x200000, 0)
    struct.pack_into(
        "<II16sQQQQIIII",
        payload,
        32,
        0x19,
        72,
        b"__TEXT",
        0x100000000,
        len(payload),
        0,
        len(payload),
        7,
        5,
        0,
        0,
    )
    struct.pack_into("<IIQQ", payload, 104, 0x80000028, 24, 128, 0)
    payload[128:] = b"BTRC-MACH-O-64!!"
    return bytes(payload)


def _pe32_plus() -> bytes:
    payload = bytearray(1024)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", payload, 0x84, 0x8664, 1, 0, 0, 0, 240, 0x0022)
    optional = 0x98
    struct.pack_into("<H", payload, optional, 0x20B)
    struct.pack_into("<I", payload, optional + 4, 512)
    struct.pack_into("<IIQ", payload, optional + 16, 0x1000, 0x1000, 0x140000000)
    struct.pack_into("<II", payload, optional + 32, 0x1000, 0x200)
    struct.pack_into("<II", payload, optional + 56, 0x2000, 0x200)
    struct.pack_into("<H", payload, optional + 68, 3)
    struct.pack_into("<I", payload, optional + 108, 16)
    section = optional + 240
    struct.pack_into("<8sIIIIIIHHI", payload, section, b".text", 16, 0x1000, 512, 512, 0, 0, 0, 0, 0x60000020)
    payload[512:520] = b"BTRCPE64"
    return bytes(payload)


def binary_payload(target: str) -> bytes:
    if target == "linux-x64":
        return _elf64(62)
    if target == "linux-arm64":
        return _elf64(183)
    if target == "macos-x64":
        return _mach_o64(0x01000007)
    if target == "macos-arm64":
        return _mach_o64(0x0100000C)
    if target == "windows-x64":
        return _pe32_plus()
    raise AssertionError(f"unknown fixture target: {target}")
