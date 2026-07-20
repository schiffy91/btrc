"""Bounded filesystem scans for directory import specifications."""

from __future__ import annotations

import os

from . import frontend_limits
from .pkg import IncludeResolutionError

_SOURCE_SUFFIXES = (".btrc", ".c")


def scan_import_directory(root: str, *, recursive: bool) -> list[str]:
    """Return sorted source files without materializing an unbounded listing."""
    matches: list[str] = []
    pending = [root]
    scanned_entries = 0
    try:
        while pending:
            current = pending.pop()
            child_directories: list[str] = []
            with os.scandir(current) as entries:
                for entry in entries:
                    scanned_entries += 1
                    if scanned_entries > frontend_limits.MAX_IMPORT_SCAN_ENTRIES:
                        raise IncludeResolutionError(
                            f"import directory exceeds the "
                            f"{frontend_limits.MAX_IMPORT_SCAN_ENTRIES}-entry scan limit: {root!r}"
                        )
                    if recursive and entry.is_dir(follow_symlinks=False):
                        child_directories.append(entry.path)
                    elif entry.is_file() and entry.name.endswith(_SOURCE_SUFFIXES):
                        if len(matches) >= frontend_limits.MAX_RESOLVED_FILES:
                            raise IncludeResolutionError(
                                f"import directory exceeds the "
                                f"{frontend_limits.MAX_RESOLVED_FILES}-file limit: {root!r}"
                            )
                        matches.append(entry.path)
            if recursive:
                pending.extend(sorted(child_directories, reverse=True))
    except OSError as error:
        raise IncludeResolutionError(f"cannot scan import directory {root!r}: {error}") from error
    return sorted(matches)
