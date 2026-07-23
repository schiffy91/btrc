"""Structured ARC atoms shared by ownership-lowering paths."""

from __future__ import annotations

from ..nodes import (
    CType,
    IRAddressOf,
    IRCall,
    IRCast,
    IRCompoundLiteral,
    IRFunctionRef,
    IRLiteral,
    IRVar,
)
from .arc_type_names import destroy_name


def retain_if_present(gen, value) -> IRCall:
    """Retain a nullable class value and yield a scalar expression."""
    gen.helpers.use("__btrc_arc_retain")
    return IRCall(
        callee="__btrc_arc_retain",
        helper_ref="__btrc_arc_retain",
        args=[value],
    )


def retain_edge_if_present(gen, value, owner) -> IRCall:
    """Retain a value stored into a persistent managed graph edge."""
    gen.helpers.use("__btrc_arc_retain_edge")
    return IRCall(
        callee="__btrc_arc_retain_edge",
        helper_ref="__btrc_arc_retain_edge",
        args=[value, owner],
    )


def adopt_edge_if_present(gen, value, owner) -> IRCall:
    """Convert an existing external +1 into an owned graph edge."""
    helper = "__btrc_arc_adopt_edge"
    gen.helpers.use(helper)
    return IRCall(
        callee=helper,
        helper_ref=helper,
        args=[value, owner],
    )


def unlink_edge_if_present(gen, value, owner=None) -> IRCall:
    """Invalidate the old incoming-edge witness before unpublishing a slot."""
    helper = "__btrc_arc_unlink_edge"
    gen.helpers.use(helper)
    return IRCall(
        callee=helper,
        helper_ref=helper,
        args=[value, owner if owner is not None else IRLiteral(text="NULL")],
    )


def arc_type_descriptor(gen, type_expr):
    """Build the copied runtime descriptor for one concrete managed type."""
    from .managed_values import is_mutex_type

    if is_mutex_type(gen, type_expr):
        gen.helpers.use("__btrc_mutex_arc_type")
        return IRAddressOf(expr=IRVar(name="__btrc_mutex_arc_descriptor"))
    from .cycle_metadata import visitor_for_type

    visitor = visitor_for_type(gen, type_expr)
    return IRAddressOf(
        expr=IRCompoundLiteral(
            c_type=CType(text="__btrc_arc_type"),
            fields=[
                (
                    "visit",
                    IRFunctionRef(name=visitor) if visitor else IRLiteral(text="NULL"),
                ),
                ("destroy", IRFunctionRef(name=destroy_name(gen, type_expr))),
                ("hook", IRLiteral(text="NULL")),
                ("guard", IRLiteral(text="NULL")),
                ("raise", IRLiteral(text="NULL")),
            ],
        )
    )


def emitted_type_descriptor(gen, emitted_name: str):
    """Build a descriptor when scope metadata already stores the C type name."""
    from .managed_values import MUTEX_RUNTIME_NAME

    if emitted_name == MUTEX_RUNTIME_NAME:
        gen.helpers.use("__btrc_mutex_arc_type")
        return IRAddressOf(expr=IRVar(name="__btrc_mutex_arc_descriptor"))
    from .arc_cycles import managed_visitor_symbol

    visitor = managed_visitor_symbol(gen, emitted_name)
    return IRAddressOf(
        expr=IRCompoundLiteral(
            c_type=CType(text="__btrc_arc_type"),
            fields=[
                (
                    "visit",
                    IRFunctionRef(name=visitor) if visitor else IRLiteral(text="NULL"),
                ),
                ("destroy", IRFunctionRef(name=f"{emitted_name}_destroy")),
                ("hook", IRLiteral(text="NULL")),
                ("guard", IRLiteral(text="NULL")),
                ("raise", IRLiteral(text="NULL")),
            ],
        )
    )


def release_if_present(gen, value, type_expr) -> IRCall:
    """Release one typed owner and buffer any graph-bearing survivor/root."""
    helper = "__btrc_arc_release" if type_release_can_enqueue(gen, type_expr) else "__btrc_arc_release_acyclic"
    gen.helpers.use(helper)
    return IRCall(
        callee=helper,
        helper_ref=helper,
        args=[value, arc_type_descriptor(gen, type_expr)],
    )


def release_edge_if_present(gen, value, type_expr, replacement=None) -> IRCall:
    """Release one persistent edge using its static fallback descriptor."""
    helper = "__btrc_arc_release_edge"
    gen.helpers.use(helper)
    return IRCall(
        callee=helper,
        helper_ref=helper,
        args=[
            value,
            arc_type_descriptor(gen, type_expr),
            replacement if replacement is not None else IRLiteral(text="NULL"),
        ],
    )


def replace_edge(gen, slot, replacement, type_expr, owner, *, adopt: bool) -> IRCall:
    """Replace one persistent class edge as a single topology transaction."""
    from .cleanup_slots import ensure_arc_slot_adapter
    from .lvalues import value_c_type
    from .types import type_to_c

    helper = "__btrc_arc_replace_edge"
    access = ensure_arc_slot_adapter(
        gen,
        CType(text=value_c_type(type_expr, gen.analyzed.class_table, type_to_c)),
    )
    gen.helpers.use(helper)
    return IRCall(
        callee=helper,
        helper_ref=helper,
        args=[
            IRCast(
                target_type=CType(text="volatile void*"),
                expr=IRAddressOf(expr=slot),
            ),
            IRFunctionRef(name=access),
            replacement,
            owner,
            arc_type_descriptor(gen, type_expr),
            IRLiteral(text="1" if adopt else "0"),
        ],
    )


def release_emitted(gen, value, emitted_name: str) -> IRCall:
    """Release one scope-tracked owner by its concrete emitted type name."""
    helper = "__btrc_arc_release" if emitted_release_can_enqueue(gen, emitted_name) else "__btrc_arc_release_acyclic"
    gen.helpers.use(helper)
    return IRCall(
        callee=helper,
        helper_ref=helper,
        args=[value, emitted_type_descriptor(gen, emitted_name)],
    )


def flush_cycles(gen) -> IRCall:
    """Flush buffered ownership-loss candidates at an observable boundary."""
    gen.helpers.use("__btrc_flush_cycles")
    return IRCall(
        callee="__btrc_flush_cycles",
        helper_ref="__btrc_flush_cycles",
        args=[],
    )


def poll_cycles(gen) -> IRCall:
    """Collect only after the deduplicated suspect queue reaches its bound."""
    gen.helpers.use("__btrc_poll_cycles")
    # The optimizer installs the program-exit force boundary after function
    # reachability is known, so keep its sibling definition available until
    # dead-helper elimination can see whether that boundary was installed.
    gen.helpers.use("__btrc_flush_cycles")
    return IRCall(
        callee="__btrc_poll_cycles",
        helper_ref="__btrc_poll_cycles",
        args=[],
    )


def type_release_can_enqueue(gen, type_expr) -> bool:
    """Whether releasing this concrete type can add a cycle suspect."""
    from .cycle_metadata import type_may_cycle

    return type_may_cycle(gen, type_expr)


def emitted_release_can_enqueue(gen, emitted_name: str) -> bool:
    """Whether a scope-tracked emitted type can add a cycle suspect."""
    from .managed_values import MUTEX_RUNTIME_NAME

    if emitted_name == MUTEX_RUNTIME_NAME:
        return True
    from .cycle_metadata import emitted_type_may_cycle

    return emitted_type_may_cycle(gen, emitted_name)


def release_batch_boundary(
    gen,
    *,
    types=(),
    emitted_names=(),
    force: bool,
) -> IRCall | None:
    """Emit one honest collector boundary for a release-bearing batch."""
    can_enqueue = any(type_release_can_enqueue(gen, item) for item in types) or any(
        emitted_release_can_enqueue(gen, item) for item in emitted_names
    )
    if can_enqueue:
        return flush_cycles(gen) if force else poll_cycles(gen)
    return None


def poll_release_batch(gen, *, types=(), emitted_names=()) -> IRCall | None:
    """Bound deferred garbage after an ordinary mutation/expression batch."""
    return release_batch_boundary(
        gen,
        types=types,
        emitted_names=emitted_names,
        force=False,
    )


def flush_release_batch(gen, *, types=(), emitted_names=()) -> IRCall | None:
    """Drain suspects after an externally observable ownership boundary."""
    return release_batch_boundary(
        gen,
        types=types,
        emitted_names=emitted_names,
        force=True,
    )


def invalidate_cycle_proof(gen, value) -> IRCall:
    """Invalidate cached topology/liveness after an owned-slot mutation."""
    gen.helpers.use("__btrc_arc_invalidate")
    return IRCall(
        callee="__btrc_arc_invalidate",
        helper_ref="__btrc_arc_invalidate",
        args=[value],
    )


__all__ = [
    "adopt_edge_if_present",
    "arc_type_descriptor",
    "destroy_name",
    "emitted_release_can_enqueue",
    "emitted_type_descriptor",
    "flush_cycles",
    "flush_release_batch",
    "invalidate_cycle_proof",
    "poll_cycles",
    "poll_release_batch",
    "release_batch_boundary",
    "release_edge_if_present",
    "release_emitted",
    "release_if_present",
    "replace_edge",
    "retain_edge_if_present",
    "retain_if_present",
    "type_release_can_enqueue",
    "unlink_edge_if_present",
]
