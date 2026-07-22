"""Authoritative binary-format contracts for published ``btrcc`` targets."""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .artifact_storage import open_regular
from .btrcc_binary_formats import read_executable_machine


@dataclass(frozen=True)
class TargetSpec:
    executable: str
    archive_suffix: str
    binary_format: str
    machine: int
    description: str


TARGETS = {
    "linux-x64": TargetSpec("bin/btrcc", ".tar.gz", "elf", 62, "ELF x86-64"),
    "linux-arm64": TargetSpec("bin/btrcc", ".tar.gz", "elf", 183, "ELF AArch64"),
    "macos-x64": TargetSpec("bin/btrcc", ".tar.gz", "mach-o", 0x01000007, "Mach-O x86_64"),
    "macos-arm64": TargetSpec("bin/btrcc", ".tar.gz", "mach-o", 0x0100000C, "Mach-O arm64"),
    "windows-x64": TargetSpec("bin/btrcc.exe", ".zip", "pe", 0x8664, "PE x86-64"),
}

_HOST_TARGETS = {
    ("darwin", "arm64"): "macos-arm64",
    ("darwin", "x86_64"): "macos-x64",
    ("linux", "aarch64"): "linux-arm64",
    ("linux", "x86_64"): "linux-x64",
    ("windows", "amd64"): "windows-x64",
    ("windows", "x86_64"): "windows-x64",
}


def target_spec(target: str) -> TargetSpec:
    try:
        return TARGETS[target]
    except KeyError as error:
        raise ValueError(f"unsupported bundle target: {target!r}") from error


def host_target() -> str:
    """Return the release target matching the current native Python process."""

    host = platform.system().lower(), platform.machine().lower()
    try:
        return _HOST_TARGETS[host]
    except KeyError as error:
        raise ValueError(f"unsupported bundle host: {host[0]} {host[1]}") from error


def _validate_machine(machine: int | None, target: str, spec: TargetSpec) -> None:
    if machine != spec.machine:
        raise ValueError(
            f"compiler binary does not match target {target!r}: expected {spec.description}",
        )


def validate_target_binary_stream(stream: BinaryIO, target: str) -> None:
    """Validate one complete binary stream against its release target."""

    spec = target_spec(target)
    try:
        machine = read_executable_machine(stream, spec.binary_format)
    except OSError as error:
        raise ValueError(f"cannot inspect compiler binary for {target}: {error}") from error
    _validate_machine(machine, target, spec)


def validate_target_binary(path: Path, target: str) -> None:
    """Reject a compiler whose native format or machine conflicts with ``target``."""

    spec = target_spec(target)
    descriptor = -1
    try:
        descriptor = open_regular(path)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            machine = read_executable_machine(stream, spec.binary_format)
    except OSError as error:
        raise ValueError(f"cannot inspect compiler binary for {target}: {path}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    _validate_machine(machine, target, spec)


__all__ = [
    "TARGETS",
    "TargetSpec",
    "host_target",
    "target_spec",
    "validate_target_binary",
    "validate_target_binary_stream",
]
