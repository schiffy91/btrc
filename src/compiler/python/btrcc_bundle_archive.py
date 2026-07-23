"""Deterministic archive writers for relocatable ``btrcc`` bundles."""

from __future__ import annotations

import gzip
import hashlib
import os
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path

from .btrcc_archive_metadata import canonical_tar_info, canonical_zip_timestamp
from .bundle_archive_source import ArchiveEntry, BundleArchiveSource


def _reject_destination_in_bundle(bundle: Path, destination: Path) -> None:
    bundle_path = os.path.realpath(bundle)
    destination_path = os.path.realpath(destination)
    try:
        inside = os.path.commonpath((bundle_path, destination_path)) == bundle_path
    except ValueError:
        inside = False
    if inside:
        raise ValueError(f"archive destination must be outside its source bundle: {destination}")


def _portable_mode(entry: ArchiveEntry, bundle: Path) -> int:
    if entry.is_directory:
        return 0o755
    relative = entry.path.relative_to(bundle)
    if len(relative.parts) == 2 and relative.parts[0] == "bin" and relative.name in {"btrcc", "btrcc.exe"}:
        return 0o755
    return 0o644


def _tar_info(entry: ArchiveEntry, bundle: Path, epoch: int) -> tarfile.TarInfo:
    relative = entry.path.relative_to(bundle.parent).as_posix()
    name = relative + ("/" if entry.is_directory else "")
    return canonical_tar_info(
        name,
        is_directory=entry.is_directory,
        mode=_portable_mode(entry, bundle),
        size=entry.size,
        modified_time=epoch,
    )


def write_tar_gz(bundle: Path, destination: Path, epoch: int) -> None:
    """Write a byte-reproducible gzip-compressed POSIX tar archive."""

    _reject_destination_in_bundle(bundle, destination)
    source = BundleArchiveSource(bundle)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{destination.name}.tmp-",
            dir=destination.parent,
            delete=False,
        ) as raw:
            temporary = Path(raw.name)
            with (
                gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed,
                tarfile.open(
                    fileobj=compressed,
                    mode="w",
                    format=tarfile.PAX_FORMAT,
                ) as archive,
            ):
                entries = source.discover()
                for entry in entries:
                    info = _tar_info(entry, bundle, epoch)
                    if not entry.is_directory:
                        with source.open_regular(entry) as payload:
                            archive.addfile(info, payload)
                    else:
                        source.validate_directory(entry)
                        archive.addfile(info)
                source.validate_snapshot(entries)
        os.replace(temporary, destination)
        destination.chmod(0o644)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_zip(bundle: Path, destination: Path, epoch: int) -> None:
    """Write a deterministic ZIP archive with portable Unix mode metadata."""

    _reject_destination_in_bundle(bundle, destination)
    source = BundleArchiveSource(bundle)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b",
            prefix=f".{destination.name}.tmp-",
            dir=destination.parent,
            delete=False,
        ) as raw:
            temporary = Path(raw.name)
            with zipfile.ZipFile(
                raw,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                entries = source.discover()
                for entry in entries:
                    relative = entry.path.relative_to(bundle.parent).as_posix()
                    name = relative + ("/" if entry.is_directory else "")
                    info = zipfile.ZipInfo(name, canonical_zip_timestamp(epoch))
                    info.create_system = 3
                    if entry.is_directory:
                        source.validate_directory(entry)
                        mode = stat.S_IFDIR | _portable_mode(entry, bundle)
                        dos_attributes = 0x10
                        payload = b""
                    else:
                        mode = stat.S_IFREG | _portable_mode(entry, bundle)
                        dos_attributes = 0
                        with source.open_regular(entry) as payload_stream:
                            payload = payload_stream.read()
                        source.validate_payload(entry, payload)
                    info.external_attr = (mode & 0xFFFF) << 16 | dos_attributes
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, payload)
                source.validate_snapshot(entries)
        os.replace(temporary, destination)
        destination.chmod(0o644)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_checksum(archive: Path) -> Path:
    """Write the conventional SHA-256 sidecar for ``archive``."""

    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    destination = archive.with_name(f"{archive.name}.sha256")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{destination.name}.tmp-",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(f"{digest}  {archive.name}\n")
        os.replace(temporary, destination)
        destination.chmod(0o644)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination
