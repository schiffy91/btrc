"""Canonical runtime symbol selection for managed source types."""

from .type_resolution import canonical_type
from .types import is_generic_class_type


def destroy_name(gen, type_expr) -> str:
    """Return the terminal destructor for one analyzed class value."""
    from .managed_values import is_mutex_type

    if is_mutex_type(gen, type_expr):
        gen.helpers.use("__btrc_mutex_arc_type")
        return "__btrc_mutex_arc_destroy"
    type_expr = canonical_type(type_expr, gen.analyzed.typedef_table) or type_expr
    if is_generic_class_type(type_expr, gen.analyzed.class_table):
        mangled = gen.type_identity.specialization_symbol(type_expr.base, type_expr.generic_args)
        return f"{mangled}_destroy"
    return f"{type_expr.base}_destroy"


__all__ = ["destroy_name"]
