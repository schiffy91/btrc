"""Binary-format and architecture contracts for release bundle targets."""

from __future__ import annotations

import ast
import io
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

import src.compiler.python.btrcc_binary_formats as binary_formats_module
import src.compiler.python.btrcc_target_binary as target_module
from src.compiler.python.btrcc_target_binary import (
    TargetBinaryValidator,
    TargetCatalog,
)
from src.tests.python.btrcc_binary_fixtures import binary_payload


def _binary(target: str) -> bytes:
    return binary_payload(target)


class _ShortReader(io.BytesIO):
    def read(self, size: int = -1) -> bytes:
        return super().read(3 if size < 0 else min(size, 3))


@pytest.mark.parametrize(
    "module",
    [binary_formats_module, target_module],
)
def test_target_binary_behavior_has_explicit_owners(module) -> None:
    syntax = ast.parse(Path(module.__file__).read_text())
    loose_behavior = [node.name for node in syntax.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]

    assert loose_behavior == []


@pytest.mark.parametrize(
    "target",
    ["linux-x64", "linux-arm64", "macos-x64", "macos-arm64", "windows-x64"],
)
def test_target_binary_accepts_its_declared_format_and_machine(
    tmp_path: Path,
    target: str,
) -> None:
    binary = tmp_path / "btrcc"
    binary.write_bytes(_binary(target))

    TargetBinaryValidator().validate_path(binary, target)


@pytest.mark.parametrize(
    ("binary_target", "declared_target"),
    [
        ("linux-x64", "linux-arm64"),
        ("linux-arm64", "linux-x64"),
        ("macos-x64", "macos-arm64"),
        ("macos-arm64", "macos-x64"),
        ("windows-x64", "linux-x64"),
    ],
)
def test_target_binary_rejects_mislabeled_format_or_machine(
    tmp_path: Path,
    binary_target: str,
    declared_target: str,
) -> None:
    binary = tmp_path / "btrcc"
    binary.write_bytes(_binary(binary_target))

    with pytest.raises(ValueError, match=f"does not match target {declared_target!r}"):
        TargetBinaryValidator().validate_path(binary, declared_target)


@pytest.mark.parametrize(
    ("target", "payload"),
    [
        ("linux-x64", b""),
        ("linux-x64", b"\x7fELF\x01\x01" + bytes(58)),
        ("macos-arm64", b"\xcf\xfa\xed\xfe"),
        ("macos-arm64", b"\xca\xfe\xba\xbe" + bytes(28)),
        ("windows-x64", b"MZ" + bytes(62)),
        ("windows-x64", b"not-a-portable-executable"),
    ],
)
def test_target_binary_rejects_truncated_or_wrong_headers(
    tmp_path: Path,
    target: str,
    payload: bytes,
) -> None:
    binary = tmp_path / "btrcc"
    binary.write_bytes(payload)

    with pytest.raises(ValueError, match=f"does not match target {target!r}"):
        TargetBinaryValidator().validate_path(binary, target)


def test_pe_header_must_start_at_its_declared_offset(tmp_path: Path) -> None:
    payload = bytearray(70)
    payload[:2] = b"MZ"
    struct.pack_into("<I", payload, 0x3C, 0x80)
    payload[64:68] = b"PE\0\0"
    struct.pack_into("<H", payload, 68, 0x8664)
    binary = tmp_path / "btrcc.exe"
    binary.write_bytes(payload)

    with pytest.raises(ValueError, match="does not match target 'windows-x64'"):
        TargetBinaryValidator().validate_path(binary, "windows-x64")


@pytest.mark.parametrize(
    ("target", "offset", "encoding", "value"),
    [
        ("linux-x64", 16, "<H", 1),
        ("linux-x64", 56, "<H", 0),
        ("linux-x64", 80, "<Q", 4096),
        ("macos-arm64", 12, "<I", 6),
        ("macos-arm64", 36, "<I", 7),
        ("macos-arm64", 104, "<I", 5),
        ("macos-arm64", 112, "<Q", 0),
        ("macos-arm64", 112, "<Q", 4096),
        ("windows-x64", 0x98, "<H", 0x10B),
        ("windows-x64", 0x96, "<H", 0x2020),
        ("windows-x64", 0xA8, "<I", 0x3000),
        ("windows-x64", 0xD0, "<I", 0x1000),
        ("windows-x64", 0xDC, "<H", 2),
        ("windows-x64", 0x19C, "<I", 4096),
    ],
)
def test_target_binary_rejects_structurally_incomplete_executables(
    tmp_path: Path,
    target: str,
    offset: int,
    encoding: str,
    value: int,
) -> None:
    payload = bytearray(_binary(target))
    struct.pack_into(encoding, payload, offset, value)
    binary = tmp_path / "btrcc"
    binary.write_bytes(payload)

    with pytest.raises(ValueError, match=f"does not match target {target!r}"):
        TargetBinaryValidator().validate_path(binary, target)


@pytest.mark.parametrize(
    ("target", "patches"),
    [
        ("linux-x64", ((96, "<Q", 120),)),
        (
            "windows-x64",
            (
                (0xA8, "<I", 0x1100),
                (0x190, "<I", 0x200),
                (0x198, "<I", 0x100),
            ),
        ),
    ],
)
def test_entrypoint_must_map_to_file_backed_executable_bytes(
    tmp_path: Path,
    target: str,
    patches: tuple[tuple[int, str, int], ...],
) -> None:
    payload = bytearray(_binary(target))
    for offset, encoding, value in patches:
        struct.pack_into(encoding, payload, offset, value)
    binary = tmp_path / "btrcc"
    binary.write_bytes(payload)

    with pytest.raises(ValueError, match=f"does not match target {target!r}"):
        TargetBinaryValidator().validate_path(binary, target)


@pytest.mark.parametrize("extent_offset", [64, 80])
def test_mach_o_executable_extent_must_have_virtual_and_file_bytes(
    tmp_path: Path,
    extent_offset: int,
) -> None:
    payload = bytearray(_binary("macos-arm64"))
    struct.pack_into("<Q", payload, extent_offset, 0)
    binary = tmp_path / "btrcc"
    binary.write_bytes(payload)

    with pytest.raises(ValueError, match="does not match target 'macos-arm64'"):
        TargetBinaryValidator().validate_path(binary, "macos-arm64")


@pytest.mark.parametrize(
    ("target", "patches"),
    [
        (
            "linux-x64",
            (
                (24, "<Q", (1 << 64) - 65),
                (80, "<Q", (1 << 64) - 65),
            ),
        ),
        ("macos-arm64", ((56, "<Q", (1 << 64) - 129),)),
        (
            "windows-x64",
            (
                (0xA8, "<I", (1 << 32) - 256),
                (0x194, "<I", (1 << 32) - 256),
                (0xD0, "<I", (1 << 32) - 1),
            ),
        ),
    ],
)
def test_virtual_extent_arithmetic_must_not_overflow(
    tmp_path: Path,
    target: str,
    patches: tuple[tuple[int, str, int], ...],
) -> None:
    payload = bytearray(_binary(target))
    for offset, encoding, value in patches:
        struct.pack_into(encoding, payload, offset, value)
    binary = tmp_path / "btrcc"
    binary.write_bytes(payload)

    with pytest.raises(ValueError, match=f"does not match target {target!r}"):
        TargetBinaryValidator().validate_path(binary, target)


@pytest.mark.parametrize(
    "target",
    ["linux-x64", "linux-arm64", "macos-x64", "macos-arm64", "windows-x64"],
)
def test_target_binary_accepts_short_stream_reads(target: str) -> None:
    TargetBinaryValidator().validate_stream(
        _ShortReader(_binary(target)),
        target,
    )


def test_target_binary_accepts_a_real_native_executable(tmp_path: Path) -> None:
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("a native C compiler is unavailable")
    source = tmp_path / "probe.c"
    executable = tmp_path / ("probe.exe" if target_module.os.name == "nt" else "probe")
    source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
    result = subprocess.run(
        [compiler, str(source), "-o", str(executable)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.skip(f"native C compiler is unusable: {result.stderr}")

    catalog = TargetCatalog()
    TargetBinaryValidator(catalog).validate_path(
        executable,
        catalog.host_target(),
    )


@pytest.mark.parametrize(
    ("system", "machine", "target"),
    [
        ("Darwin", "arm64", "macos-arm64"),
        ("Darwin", "x86_64", "macos-x64"),
        ("Linux", "aarch64", "linux-arm64"),
        ("Linux", "x86_64", "linux-x64"),
        ("Windows", "AMD64", "windows-x64"),
    ],
)
def test_host_target_maps_supported_native_runners(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    target: str,
) -> None:
    monkeypatch.setattr(target_module.platform, "system", lambda: system)
    monkeypatch.setattr(target_module.platform, "machine", lambda: machine)

    assert TargetCatalog().host_target() == target


def test_host_target_rejects_unpublished_architectures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(target_module.platform, "system", lambda: "Linux")
    monkeypatch.setattr(target_module.platform, "machine", lambda: "riscv64")

    with pytest.raises(ValueError, match="unsupported bundle host: linux riscv64"):
        TargetCatalog().host_target()
