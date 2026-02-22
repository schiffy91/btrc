"""Core data types for btrc runtime helper definitions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HelperDef:
    """A single C runtime helper that the btrc codegen can emit."""

    c_source: str
    """The C source text exactly as it would appear in the generated output."""

    depends_on: list[str] = field(default_factory=list)
    """Names of other helpers (keys inside their category) that must be emitted first."""
