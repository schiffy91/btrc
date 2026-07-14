"""Resource limits shared by include/import source composition."""

from __future__ import annotations

from dataclasses import dataclass

from .pkg import IncludeResolutionError

MAX_RESOLVED_SOURCE_BYTES = 64 * 1024 * 1024
MAX_RESOLVED_FILES = 10_000
MAX_IMPORT_SCAN_ENTRIES = 100_000
MAX_IMPORT_DEPTH = 256


@dataclass(slots=True)
class ResolutionBudget:
    """Track unique source files before their lines are materialized."""

    total_bytes: int = 0
    files: int = 0

    def enter(self, source: str, path: str, depth: int) -> None:
        if depth > MAX_IMPORT_DEPTH:
            raise IncludeResolutionError(
                f"include/import graph exceeds the maximum depth of {MAX_IMPORT_DEPTH} at {path!r}"
            )
        self.files += 1
        if self.files > MAX_RESOLVED_FILES:
            raise IncludeResolutionError(f"include/import graph exceeds the {MAX_RESOLVED_FILES}-file limit")
        encoded_bytes = len(source.encode("utf-8"))
        if encoded_bytes > MAX_RESOLVED_SOURCE_BYTES - self.total_bytes:
            raise IncludeResolutionError(f"resolved source exceeds the {MAX_RESOLVED_SOURCE_BYTES}-byte limit")
        self.total_bytes += encoded_bytes


def check_combined_source_size(*sources: str) -> None:
    """Reject the final user-plus-stdlib source before concatenating it."""
    total = 0
    for source in sources:
        encoded_bytes = len(source.encode("utf-8"))
        if encoded_bytes > MAX_RESOLVED_SOURCE_BYTES - total:
            raise IncludeResolutionError(f"resolved source exceeds the {MAX_RESOLVED_SOURCE_BYTES}-byte limit")
        total += encoded_bytes
