"""Translation-unit typedef context for source-preserving C type spelling."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType

from ...ast_nodes import TypeExpr
from ...type_composition import resolved_reference_shape

_typedef_types: ContextVar[Mapping[str, TypeExpr]] = ContextVar(
    "btrc_typedef_types",
    default=MappingProxyType({}),
)


@contextmanager
def type_render_scope(typedefs: Mapping[str, TypeExpr]) -> Iterator[None]:
    """Expose immutable typedef shapes while rendering one translation unit."""
    token = _typedef_types.set(MappingProxyType(dict(typedefs)))
    try:
        yield
    finally:
        _typedef_types.reset(token)


def typedef_base_is_reference(base: str) -> bool:
    typedefs = _typedef_types.get()
    if base not in typedefs:
        return False
    from .type_resolution import canonical_type

    resolved = canonical_type(TypeExpr(base=base), dict(typedefs))
    return bool(resolved and resolved_reference_shape(resolved))


__all__ = ["type_render_scope", "typedef_base_is_reference"]
