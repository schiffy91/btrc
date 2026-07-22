"""Canonical archive metadata shared by bundle writers and validators."""

from __future__ import annotations

import datetime
import tarfile
from collections.abc import Iterable

_MAX_ARCHIVE_EPOCH = 0xFFFFFFFF
_ZIP_MINIMUM_EPOCH = 315532800


def canonical_epoch(modified_times_ns: Iterable[int]) -> int:
    """Derive one exact, archive-representable epoch from staged metadata."""

    modified_times = set(modified_times_ns)
    if len(modified_times) != 1:
        raise ValueError("bundle artifacts have noncanonical timestamps")
    modified_time_ns = next(iter(modified_times))
    if (
        modified_time_ns < 0
        or modified_time_ns % 1_000_000_000
        or modified_time_ns > _MAX_ARCHIVE_EPOCH * 1_000_000_000
    ):
        raise ValueError("bundle artifacts have noncanonical timestamps")
    return modified_time_ns // 1_000_000_000


def canonical_tar_info(
    name: str,
    *,
    is_directory: bool,
    mode: int,
    size: int,
    modified_time: int,
) -> tarfile.TarInfo:
    """Return the exact tar metadata shape used for bundle members."""

    info = tarfile.TarInfo(name)
    info.mtime = modified_time
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = mode
    if is_directory:
        info.type = tarfile.DIRTYPE
    else:
        info.type = tarfile.REGTYPE
        info.size = size
    return info


def canonical_zip_timestamp(modified_time: int) -> tuple[int, int, int, int, int, int]:
    """Convert an epoch to the canonical even-second UTC ZIP timestamp."""

    value = datetime.datetime.fromtimestamp(
        max(modified_time, _ZIP_MINIMUM_EPOCH),
        datetime.UTC,
    )
    return value.year, value.month, value.day, value.hour, value.minute, value.second & ~1
