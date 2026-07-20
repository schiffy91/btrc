"""Stable regular-file copies for release bundle inputs."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import BinaryIO

_CHUNK_SIZE = 1024 * 1024


def _identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _validate_identity(
    path: Path, descriptor: int, expected: tuple[int, int, int] | None = None
) -> tuple[int, int, int]:
    opened = os.fstat(descriptor)
    current = path.lstat()
    opened_identity = _identity(opened)
    if (
        not stat.S_ISREG(opened.st_mode)
        or not stat.S_ISREG(current.st_mode)
        or opened_identity != _identity(current)
        or (expected is not None and opened_identity != expected)
    ):
        raise ValueError(f"bundle source changed identity while being copied: {path}")
    return opened_identity


def _hash_stream(stream: BinaryIO) -> tuple[bytes, int]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(_CHUNK_SIZE):
        digest.update(chunk)
        size += len(chunk)
    return digest.digest(), size


def _hash_regular_path(path: Path) -> tuple[bytes, int]:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        identity = _validate_identity(path, descriptor)
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            digest = _hash_stream(stream)
            _validate_identity(path, stream.fileno(), identity)
            return digest
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def copy_file(source: Path, destination: Path, mode: int, epoch: int) -> None:
    """Copy one stable source, tolerating content-neutral metadata churn."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    created = False
    try:
        identity = _validate_identity(source, descriptor)
        with os.fdopen(descriptor, "rb") as source_stream:
            descriptor = -1
            before = _hash_stream(source_stream)
            source_stream.seek(0)
            copied_digest = hashlib.sha256()
            copied_size = 0
            with destination.open("xb") as destination_stream:
                created = True
                while chunk := source_stream.read(_CHUNK_SIZE):
                    destination_stream.write(chunk)
                    copied_digest.update(chunk)
                    copied_size += len(chunk)
            destination_hash = _hash_regular_path(destination)
            source_stream.seek(0)
            after = _hash_stream(source_stream)
            _validate_identity(source, source_stream.fileno(), identity)
        copied = copied_digest.digest(), copied_size
        if before != copied or copied != after or after != destination_hash:
            raise ValueError(f"bundle source changed while being copied: {source}")
        destination.chmod(mode)
        os.utime(destination, (epoch, epoch), follow_symlinks=False)
    except BaseException:
        if created:
            destination.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
