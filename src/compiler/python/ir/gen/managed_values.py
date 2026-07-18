"""Ownership-domain dispatch for ARC references and managed strings."""

from __future__ import annotations

from ...type_identity import is_semantic_scalar_string
from ..nodes import CType, IRCall, IRCast, IRLiteral

STRING_RUNTIME_NAME = "__btrc_managed_string"
MUTEX_RUNTIME_NAME = "__btrc_managed_mutex"


def is_string_type(gen, type_expr) -> bool:
    """Whether ``type_expr`` is the scalar source string value domain."""
    canonical = _canonical(gen, type_expr)
    return is_semantic_scalar_string(canonical)


def is_class_type(gen, type_expr) -> bool:
    """Whether ``type_expr`` uses the class ARC header domain."""
    canonical = _canonical(gen, type_expr)
    depth = (
        canonical.pointer_depth - int(canonical.is_nullable and canonical.pointer_depth > 1)
        if canonical is not None
        else 0
    )
    return bool(
        canonical is not None and not canonical.is_array and depth <= 1 and canonical.base in gen.analyzed.class_table
    )


def is_mutex_type(gen, type_expr) -> bool:
    """Whether ``type_expr`` is one direct ARC-managed ``Mutex<T>``."""
    canonical = _canonical(gen, type_expr)
    depth = (
        canonical.pointer_depth - int(canonical.is_nullable and canonical.pointer_depth > 0)
        if canonical is not None
        else 0
    )
    return bool(
        canonical is not None
        and not canonical.is_array
        and depth == 0
        and canonical.base == "Mutex"
        and len(canonical.generic_args or ()) == 1
    )


def is_arc_type(gen, type_expr) -> bool:
    """Whether a value starts with the common ARC object header."""
    return is_class_type(gen, type_expr) or is_mutex_type(gen, type_expr)


def is_managed_type(gen, type_expr) -> bool:
    return is_string_type(gen, type_expr) or is_arc_type(gen, type_expr)


def runtime_name(gen, type_expr) -> str:
    """Return the scope bookkeeping name for a managed value type."""
    if is_string_type(gen, type_expr):
        return STRING_RUNTIME_NAME
    if is_mutex_type(gen, type_expr):
        return MUTEX_RUNTIME_NAME
    from .ownership import managed_type_name

    return managed_type_name(gen, _canonical(gen, type_expr))


def managed_local_value_type(type_expr, emitted_name: str | None):
    """Recover the managed value domain retained by an ownership-provenance slot."""
    if emitted_name == STRING_RUNTIME_NAME:
        from ...ast_nodes import TypeExpr

        return TypeExpr(base="string")
    return type_expr


def retain_value(gen, value, type_expr):
    if is_string_type(gen, type_expr):
        gen.use_helper("__btrc_string_retain")
        return IRCall(
            callee="__btrc_string_retain",
            args=[value],
            helper_ref="__btrc_string_retain",
        )
    from .arc_ops import retain_if_present

    return retain_if_present(gen, value)


def retain_edge_value(gen, value, type_expr, owner):
    if is_string_type(gen, type_expr):
        return retain_value(gen, value, type_expr)
    from .arc_ops import retain_edge_if_present

    return retain_edge_if_present(gen, value, owner)


def adopt_edge_value(gen, value, type_expr, owner):
    if is_string_type(gen, type_expr):
        # Heap-producing string expressions already carry their +1. Storing
        # that reference transfers it into the slot without another retain.
        return _no_op()
    from .arc_ops import adopt_edge_if_present

    return adopt_edge_if_present(gen, value, owner)


def release_value(gen, value, type_expr):
    if is_string_type(gen, type_expr):
        gen.use_helper("__btrc_string_release")
        return IRCall(
            callee="__btrc_string_release",
            args=[value],
            helper_ref="__btrc_string_release",
        )
    from .arc_ops import release_if_present

    return release_if_present(gen, value, type_expr)


def release_edge_value(gen, value, type_expr, replacement=None):
    if is_string_type(gen, type_expr):
        return release_value(gen, value, type_expr)
    from .arc_ops import release_edge_if_present

    return release_edge_if_present(gen, value, type_expr, replacement)


def unlink_edge_value(gen, value, type_expr, owner=None):
    """Unpublish a persistent edge from the domain that tracks its graph."""
    if is_string_type(gen, type_expr):
        # Strings are scalar references in a process-wide side table.  They do
        # not participate in the class cycle graph and have no edge witness.
        return _no_op()
    from .arc_ops import unlink_edge_if_present

    return unlink_edge_if_present(gen, value, owner)


def replace_edge_value(gen, slot, replacement, type_expr, owner, *, adopt: bool):
    """Replace one class edge atomically; strings use their side-table path."""
    if not is_arc_type(gen, type_expr):
        raise ValueError("transactional edge replacement requires an ARC type")
    from .arc_ops import replace_edge

    return replace_edge(
        gen,
        slot,
        replacement,
        type_expr,
        owner,
        adopt=adopt,
    )


def poll_released_values(gen, *type_exprs):
    """Bound class-cycle work after a mixed managed-value release batch."""
    from .arc_ops import poll_release_batch

    return poll_release_batch(
        gen,
        types=[value for value in type_exprs if is_arc_type(gen, value)],
    )


def flush_released_values(gen, *type_exprs):
    """Drain class-cycle work at an observable mixed-value boundary."""
    from .arc_ops import flush_release_batch

    return flush_release_batch(
        gen,
        types=[value for value in type_exprs if is_arc_type(gen, value)],
    )


def release_emitted_value(gen, value, emitted_name: str):
    if emitted_name == STRING_RUNTIME_NAME:
        gen.use_helper("__btrc_string_release")
        return IRCall(
            callee="__btrc_string_release",
            args=[value],
            helper_ref="__btrc_string_release",
        )
    from .arc_ops import release_emitted

    return release_emitted(gen, value, emitted_name)


def cleanup_destroy_symbol(emitted_name: str) -> str:
    if emitted_name == STRING_RUNTIME_NAME:
        return "__btrc_string_release_cleanup"
    if emitted_name == MUTEX_RUNTIME_NAME:
        return "__btrc_mutex_arc_destroy"
    return f"{emitted_name}_destroy"


def destroy_symbol(gen, type_expr) -> str:
    """Return the direct destructor/callback for one concrete managed value."""
    if is_string_type(gen, type_expr):
        gen.use_helper("__btrc_string_release_cleanup")
        return "__btrc_string_release_cleanup"
    from .arc_ops import destroy_name

    return destroy_name(gen, _canonical(gen, type_expr))


def _canonical(gen, type_expr):
    if type_expr is None:
        return None
    from .type_resolution import canonical_type

    return canonical_type(type_expr, gen.analyzed.typedef_table)


def _no_op():
    return IRCast(target_type=CType(text="void"), expr=IRLiteral(text="0"))


__all__ = [
    "MUTEX_RUNTIME_NAME",
    "STRING_RUNTIME_NAME",
    "adopt_edge_value",
    "cleanup_destroy_symbol",
    "destroy_symbol",
    "flush_released_values",
    "is_arc_type",
    "is_class_type",
    "is_managed_type",
    "is_mutex_type",
    "is_string_type",
    "managed_local_value_type",
    "poll_released_values",
    "release_edge_value",
    "release_emitted_value",
    "release_value",
    "replace_edge_value",
    "retain_edge_value",
    "retain_value",
    "runtime_name",
    "unlink_edge_value",
]
