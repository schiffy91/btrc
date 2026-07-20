"""Validated environment configuration for the language-server process."""

from __future__ import annotations

import math

DEFAULT_DEBOUNCE_SECONDS = 0.2
MAX_DEBOUNCE_SECONDS = 5.0


def parse_debounce_seconds(value: str | None) -> float:
    """Return a finite interactive debounce delay or the safe default."""
    if value is None:
        return DEFAULT_DEBOUNCE_SECONDS
    try:
        seconds = float(value)
    except ValueError:
        return DEFAULT_DEBOUNCE_SECONDS
    if not math.isfinite(seconds) or not 0 <= seconds <= MAX_DEBOUNCE_SECONDS:
        return DEFAULT_DEBOUNCE_SECONDS
    return seconds
