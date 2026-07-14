"""Cycle classification and compatibility scope-release entry points."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import IRStmt

if TYPE_CHECKING:
    from .generator import IRGenerator
    from .managed_local import ManagedLocal


def lookup_class_info(gen: IRGenerator, class_name: str):
    """Look up class metadata by source or mangled instance name."""

    info = gen.analyzed.class_table.get(class_name)
    if info:
        return info
    for source_name, candidate in gen.analyzed.class_table.items():
        if class_name.startswith(f"btrc_{source_name}"):
            return candidate
    return None


def managed_type_has_visitor(gen: IRGenerator, class_name: str) -> bool:
    """Whether normal or generic lowering provides a visitor for this C type."""
    from .cycle_metadata import emitted_type_has_visitor

    if emitted_type_has_visitor(gen, class_name):
        return True
    info = lookup_class_info(gen, class_name)
    if info is not None and not info.generic_params:
        from ...ast_nodes import TypeExpr
        from .cycle_metadata import type_needs_visitor

        return type_needs_visitor(gen, TypeExpr(base=info.name), set())
    return False


def emit_phased_scope_release(
    managed: list[ManagedLocal],
    gen: IRGenerator,
) -> list[IRStmt]:
    """Compatibility entry point for the unified typed release pipeline."""
    from .arc import _emit_scope_release

    return _emit_scope_release(managed, gen, force=True)


__all__ = [
    "emit_phased_scope_release",
    "lookup_class_info",
    "managed_type_has_visitor",
]
