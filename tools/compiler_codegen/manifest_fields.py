"""Typed field reads shared by every TOML manifest the generators validate."""

from __future__ import annotations

from typing import Any


class ManifestFields:
    """Read one parsed TOML table's fields, raising the owning manifest's error type."""

    def __init__(self, error: type[Exception], *, empty_strings: bool = False) -> None:
        self._error = error
        self._empty_strings = empty_strings

    def require_keys(
        self,
        table: dict[str, Any],
        allowed: frozenset[str],
        context: str,
        *,
        required: frozenset[str] | None = None,
    ) -> None:
        """Reject keys outside `allowed` and missing `required` keys (all of `allowed` by default)."""

        unknown = set(table) - allowed
        if unknown:
            raise self._error(f"unknown {context} keys: {', '.join(sorted(unknown))}")
        missing = (allowed if required is None else required) - set(table)
        if missing:
            raise self._error(f"missing {context} keys: {', '.join(sorted(missing))}")

    def table(self, table: dict[str, Any], key: str, context: str) -> dict[str, Any]:
        value = table.get(key)
        if not isinstance(value, dict):
            raise self._error(f"{context}.{key} must be a table")
        return value

    def string(self, table: dict[str, Any], key: str, context: str) -> str:
        value = table.get(key)
        if not isinstance(value, str) or (not value and not self._empty_strings):
            qualifier = "a string" if self._empty_strings else "a non-empty string"
            raise self._error(f"{context}.{key} must be {qualifier}")
        return value

    def integer(self, table: dict[str, Any], key: str, context: str) -> int:
        value = table.get(key)
        if type(value) is not int:
            raise self._error(f"{context}.{key} must be an integer")
        return value

    def boolean(self, table: dict[str, Any], key: str, context: str) -> bool:
        value = table.get(key)
        if type(value) is not bool:
            raise self._error(f"{context}.{key} must be a boolean")
        return value
