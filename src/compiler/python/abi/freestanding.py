"""Owned freestanding runtime resource and feature-definition policy."""

from __future__ import annotations

from ..runtime.generated import (
    C_RUNTIME_CALLS,
    C_RUNTIME_LITERALS,
    C_RUNTIME_OBJECTS,
    C_RUNTIME_TYPES,
    HEADER_FEATURES,
    RUNTIME_CALL_FEATURES,
    RUNTIME_HEADER,
)


class FreestandingRuntime:
    """Query the generated freestanding ABI surface without exposing raw data."""

    def __init__(self) -> None:
        self._calls = frozenset(C_RUNTIME_CALLS)
        self._objects = frozenset(C_RUNTIME_OBJECTS)
        self._types = frozenset(C_RUNTIME_TYPES)
        self._literals = frozenset(C_RUNTIME_LITERALS)
        self._call_features = RUNTIME_CALL_FEATURES
        self._header_features = dict(HEADER_FEATURES)

    @property
    def header(self) -> str:
        """The exact generated ``btrc_rt.h`` resource."""

        return RUNTIME_HEADER

    def recognizes_call(self, name: str) -> bool:
        """Whether a call reaches the C runtime or an optional ABI family."""

        return name in self._calls or self.feature_for_call(name) is not None

    def recognizes_object(self, name: str) -> bool:
        return name in self._objects

    def recognizes_type(self, name: str) -> bool:
        return name in self._types

    def recognizes_literal(self, name: str) -> bool:
        return name in self._literals

    def feature_for_call(self, name: str) -> str | None:
        """Return the feature macro selected by a native-call prefix."""

        for prefix, feature in self._call_features:
            if name.startswith(prefix):
                return feature
        return None

    def feature_for_header(self, header: str) -> str | None:
        """Return the feature macro selected by a helper's hosted header."""

        return self._header_features.get(header)


__all__ = ["FreestandingRuntime"]
