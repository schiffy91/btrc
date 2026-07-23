"""Owned resource policy for include/import source composition."""

from __future__ import annotations

from dataclasses import dataclass

from .pkg import IncludeResolutionError


@dataclass(frozen=True, slots=True)
class SourceResolutionPolicy:
    """Own immutable resource limits for one compiler application."""

    max_source_bytes: int = 64 * 1024 * 1024
    max_files: int = 10_000
    max_scan_entries: int = 100_000
    max_depth: int = 256

    def __post_init__(self) -> None:
        if (
            min(
                self.max_source_bytes,
                self.max_files,
                self.max_scan_entries,
                self.max_depth,
            )
            <= 0
        ):
            raise ValueError("source resolution limits must be positive")

    def new_budget(self) -> ResolutionBudget:
        """Create isolated accounting state governed by this policy."""
        return ResolutionBudget(self)

    def validate_combined(self, *sources: str) -> None:
        """Reject final user-plus-stdlib text before concatenating it."""
        total = 0
        for source in sources:
            encoded_bytes = len(source.encode("utf-8"))
            if encoded_bytes > self.max_source_bytes - total:
                raise IncludeResolutionError(f"resolved source exceeds the {self.max_source_bytes}-byte limit")
            total += encoded_bytes


@dataclass(slots=True)
class ResolutionBudget:
    """Track unique source files before their lines are materialized."""

    policy: SourceResolutionPolicy
    total_bytes: int = 0
    files: int = 0

    def enter(self, source: str, path: str, depth: int) -> None:
        if depth > self.policy.max_depth:
            raise IncludeResolutionError(
                f"include/import graph exceeds the maximum depth of {self.policy.max_depth} at {path!r}"
            )
        self.files += 1
        if self.files > self.policy.max_files:
            raise IncludeResolutionError(f"include/import graph exceeds the {self.policy.max_files}-file limit")
        encoded_bytes = len(source.encode("utf-8"))
        if encoded_bytes > self.policy.max_source_bytes - self.total_bytes:
            raise IncludeResolutionError(f"resolved source exceeds the {self.policy.max_source_bytes}-byte limit")
        self.total_bytes += encoded_bytes


__all__ = ["ResolutionBudget", "SourceResolutionPolicy"]
