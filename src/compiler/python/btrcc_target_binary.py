"""Owned binary-format contracts for published ``btrcc`` targets."""

from __future__ import annotations

import os
import platform
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO

from .artifacts.publication.storage import ArtifactStorage
from .btrcc_binary_formats import ExecutableFormatInspector


@dataclass(frozen=True)
class TargetSpec:
    executable: str
    archive_suffix: str
    binary_format: str
    machine: int
    description: str


_DEFAULT_TARGETS = MappingProxyType(
    {
        "linux-x64": TargetSpec(
            "bin/btrcc",
            ".tar.gz",
            "elf",
            62,
            "ELF x86-64",
        ),
        "linux-arm64": TargetSpec(
            "bin/btrcc",
            ".tar.gz",
            "elf",
            183,
            "ELF AArch64",
        ),
        "macos-x64": TargetSpec(
            "bin/btrcc",
            ".tar.gz",
            "mach-o",
            0x01000007,
            "Mach-O x86_64",
        ),
        "macos-arm64": TargetSpec(
            "bin/btrcc",
            ".tar.gz",
            "mach-o",
            0x0100000C,
            "Mach-O arm64",
        ),
        "windows-x64": TargetSpec(
            "bin/btrcc.exe",
            ".zip",
            "pe",
            0x8664,
            "PE x86-64",
        ),
    },
)

_DEFAULT_HOST_TARGETS = MappingProxyType(
    {
        ("darwin", "arm64"): "macos-arm64",
        ("darwin", "x86_64"): "macos-x64",
        ("linux", "aarch64"): "linux-arm64",
        ("linux", "x86_64"): "linux-x64",
        ("windows", "amd64"): "windows-x64",
        ("windows", "x86_64"): "windows-x64",
    },
)


class TargetCatalog:
    """Own immutable release-target and native-host mappings."""

    def __init__(
        self,
        targets: Mapping[str, TargetSpec] | None = None,
        host_targets: Mapping[tuple[str, str], str] | None = None,
        system_name: Callable[[], str] | None = None,
        machine_name: Callable[[], str] | None = None,
    ) -> None:
        self._targets = MappingProxyType(
            dict(_DEFAULT_TARGETS if targets is None else targets),
        )
        self._host_targets = MappingProxyType(
            dict(
                _DEFAULT_HOST_TARGETS if host_targets is None else host_targets,
            ),
        )
        self._system_name = system_name if system_name is not None else platform.system
        self._machine_name = machine_name if machine_name is not None else platform.machine

    def spec(self, target: str) -> TargetSpec:
        try:
            return self._targets[target]
        except KeyError as error:
            raise ValueError(
                f"unsupported bundle target: {target!r}",
            ) from error

    def host_target(self) -> str:
        """Return the release target matching the native Python process."""

        host = self._system_name().lower(), self._machine_name().lower()
        try:
            return self._host_targets[host]
        except KeyError as error:
            raise ValueError(
                f"unsupported bundle host: {host[0]} {host[1]}",
            ) from error


class TargetBinaryValidator:
    """Own native-format validation for release-target binaries."""

    def __init__(
        self,
        catalog: TargetCatalog | None = None,
        storage: ArtifactStorage | None = None,
    ) -> None:
        self._catalog = catalog if catalog is not None else TargetCatalog()
        self._storage = storage if storage is not None else ArtifactStorage()

    def validate_stream(self, stream: BinaryIO, target: str) -> None:
        """Validate one complete binary stream against its release target."""

        spec = self._catalog.spec(target)
        try:
            machine = ExecutableFormatInspector(stream).machine(
                spec.binary_format,
            )
        except OSError as error:
            raise ValueError(
                f"cannot inspect compiler binary for {target}: {error}",
            ) from error
        self._validate_machine(machine, target, spec)

    def validate_path(self, path: Path, target: str) -> None:
        """Reject a file whose format or machine conflicts with ``target``."""

        spec = self._catalog.spec(target)
        descriptor = -1
        try:
            descriptor = self._storage.open_regular(path)
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                machine = ExecutableFormatInspector(stream).machine(
                    spec.binary_format,
                )
        except OSError as error:
            raise ValueError(
                f"cannot inspect compiler binary for {target}: {path}: {error}",
            ) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        self._validate_machine(machine, target, spec)

    @staticmethod
    def _validate_machine(
        machine: int | None,
        target: str,
        spec: TargetSpec,
    ) -> None:
        if machine != spec.machine:
            raise ValueError(
                f"compiler binary does not match target {target!r}: expected {spec.description}",
            )


__all__ = ["TargetBinaryValidator", "TargetCatalog", "TargetSpec"]
