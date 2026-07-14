"""Task-local package resolution state for one compiler invocation."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType

PackageMap = Mapping[str, Mapping[str, object]]

_EMPTY_PACKAGES: PackageMap = MappingProxyType({})
_PACKAGES: ContextVar[PackageMap] = ContextVar(
    "btrc_packages",
    default=_EMPTY_PACKAGES,
)


def _freeze(packages: Mapping[str, Mapping[str, object]]) -> PackageMap:
    return MappingProxyType({name: MappingProxyType(dict(entry)) for name, entry in packages.items()})


def configured_packages() -> PackageMap:
    """Return the immutable package map active in this execution context."""
    return _PACKAGES.get()


def replace_packages(packages: Mapping[str, Mapping[str, object]]) -> None:
    """Replace this context's package map without affecting other threads."""
    _PACKAGES.set(_freeze(packages) if packages else _EMPTY_PACKAGES)


@contextmanager
def package_context(
    packages: Mapping[str, Mapping[str, object]],
) -> Iterator[None]:
    """Temporarily install packages and restore the previous context safely."""
    token = _PACKAGES.set(_freeze(packages) if packages else _EMPTY_PACKAGES)
    try:
        yield
    finally:
        _PACKAGES.reset(token)


__all__ = ["configured_packages", "package_context", "replace_packages"]
