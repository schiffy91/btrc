"""Cycle-visitor classification and emitted-symbol registry."""

from __future__ import annotations

from dataclasses import dataclass

from ...ast_nodes import TypeExpr
from ...cycle_symbols import cycle_visitor_symbol
from .cycle_type_resolution import (
    canonical_cycle_type,
    cycle_type_key,
    substitute_cycle_type,
)
from .types import mangle_generic_type

BUILTIN_COLLECTION_LAYOUTS = {
    "Vector": (1, frozenset({"data", "len"})),
    "Array": (1, frozenset({"data", "len"})),
    "List": (1, frozenset({"head", "tail", "len"})),
    "Map": (2, frozenset({"keys", "values", "occupied", "cap"})),
    "Set": (1, frozenset({"keys", "occupied", "cap"})),
}


@dataclass(frozen=True)
class DirectVisitAction:
    """A managed slot whose target must join the collector candidate graph."""

    emitted_name: str


def generic_instance_needs_visitor(
    gen,
    base: str,
    arguments: list[TypeExpr],
    seen: set[tuple] | None = None,
) -> bool:
    """Whether a concrete generic representation owns managed slots."""
    info = gen.analyzed.class_table.get(base)
    if info is None or not info.generic_params:
        return False
    key = (base, tuple(cycle_type_key(argument) for argument in arguments))
    seen = set() if seen is None else seen
    if key in seen:
        return False
    seen.add(key)
    try:
        if base in BUILTIN_COLLECTION_LAYOUTS:
            arity, _fields = BUILTIN_COLLECTION_LAYOUTS[base]
            if len(arguments) != arity:
                return False
            # List owns heap ListNode objects even when T itself is scalar.
            return base == "List" or any(visit_action(gen, argument, seen) is not None for argument in arguments)
        substitutions = dict(zip(info.generic_params, arguments))
        return any(
            field.type is not None
            and _type_has_visit_action(
                gen,
                substitute_cycle_type(gen, field.type, substitutions),
                seen,
            )
            for _name, field in info.instance_storage
        )
    finally:
        seen.remove(key)


def visitor_for_type(gen, type_expr: TypeExpr) -> str | None:
    """Return the concrete visitor symbol used for exception cleanup."""
    type_expr = canonical_cycle_type(gen, type_expr) or type_expr
    from .managed_values import is_mutex_type

    if is_mutex_type(gen, type_expr):
        gen.helpers.use("__btrc_mutex_arc_type")
        return "__btrc_mutex_arc_visit"
    if not type_needs_visitor(gen, type_expr, set()):
        return None
    if type_expr.generic_args:
        emitted = mangle_generic_type(type_expr.base, type_expr.generic_args)
        return cycle_visitor_symbol(emitted)
    return cycle_visitor_symbol(type_expr.base)


def emitted_type_has_visitor(gen, emitted_name: str) -> bool:
    """Check metadata without confusing a source method named ``visit``."""
    return emitted_name in getattr(gen, "_cycle_visitor_types", set())


def emitted_type_may_cycle(gen, emitted_name: str) -> bool:
    """Whether an emitted representation can itself join a retain cycle.

    Scope metadata stores C names rather than ``TypeExpr`` values.  Generic
    instances register their concrete classification before their bodies are
    lowered.  Unknown emitted types fail closed and keep the collector path.
    """
    classifications = getattr(gen, "_cycle_type_may_cycle", {})
    if emitted_name in classifications:
        return classifications[emitted_name]
    info = gen.analyzed.class_table.get(emitted_name)
    if info is not None and not info.generic_params:
        return type_may_cycle(gen, TypeExpr(base=emitted_name))
    return True


def register_cycle_visitor(gen, emitted_name: str) -> None:
    visitors = getattr(gen, "_cycle_visitor_types", None)
    if visitors is None:
        visitors = set()
        gen._cycle_visitor_types = visitors
    visitors.add(emitted_name)


def register_cycle_classification(gen, emitted_name: str, may_cycle: bool) -> None:
    """Remember the concrete cycle eligibility of one emitted class."""
    classifications = getattr(gen, "_cycle_type_may_cycle", None)
    if classifications is None:
        classifications = {}
        gen._cycle_type_may_cycle = classifications
    classifications[emitted_name] = may_cycle


def visit_action(gen, type_expr: TypeExpr, seen: set[tuple]) -> DirectVisitAction | None:
    """Return one typed heap edge, or ``None`` for unmanaged storage.

    Generic containers are graph vertices in their own right.  Flattening a
    container into its element slots loses external aliases to that container,
    so the collector could otherwise reclaim elements that are still reachable
    through a separately retained collection object.
    """
    type_expr = canonical_cycle_type(gen, type_expr) or type_expr
    if type_expr.is_array:
        return None
    from .managed_values import MUTEX_RUNTIME_NAME, is_class_type, is_mutex_type

    if is_mutex_type(gen, type_expr):
        return DirectVisitAction(MUTEX_RUNTIME_NAME)
    if not is_class_type(gen, type_expr):
        return None
    info = gen.analyzed.class_table.get(type_expr.base)
    if info is None:
        return None
    emitted = type_expr.base
    if type_expr.generic_args:
        emitted = mangle_generic_type(type_expr.base, type_expr.generic_args)
    return DirectVisitAction(emitted)


def type_needs_visitor(gen, type_expr: TypeExpr, seen: set[tuple] | None = None) -> bool:
    """Whether this concrete representation has managed outgoing edges."""
    type_expr = canonical_cycle_type(gen, type_expr) or type_expr
    if type_expr.is_array:
        return False
    from .managed_values import is_class_type, is_mutex_type

    if is_mutex_type(gen, type_expr):
        return True
    if not is_class_type(gen, type_expr):
        return False
    info = gen.analyzed.class_table.get(type_expr.base)
    if info is None:
        return False
    if type_expr.generic_args:
        return generic_instance_needs_visitor(gen, type_expr.base, list(type_expr.generic_args), seen)
    return any(
        getattr(field, "type", None) is not None and _type_has_visit_action(gen, field.type, set())
        for _name, field in info.instance_storage
    )


def generic_instance_may_cycle(gen, base: str, arguments: list[TypeExpr]) -> bool:
    """Whether this concrete generic representation can reach itself."""
    return type_may_cycle(gen, TypeExpr(base=base, generic_args=list(arguments)))


def type_may_cycle(gen, type_expr: TypeExpr) -> bool:
    """Return whether any runtime value of this type may join a retain cycle."""
    from .polymorphic_cycles import runtime_type_candidates

    return any(_concrete_type_may_cycle(gen, candidate) for candidate in runtime_type_candidates(gen, type_expr))


def _concrete_type_may_cycle(gen, type_expr: TypeExpr) -> bool:
    """Return whether one concrete layout can participate in a retain cycle.

    This follows actual owned runtime slots.  In particular, a collection is
    a graph vertex rather than a transparent path through its elements.  An
    acyclic wrapper may point *into* a cyclic component without being part of
    that component itself, so it can use synchronous reference counting.
    """
    type_expr = canonical_cycle_type(gen, type_expr) or type_expr
    if not _is_managed_reference(gen, type_expr):
        return False
    info = gen.analyzed.class_table.get(type_expr.base)
    if info is not None and info.generic_params and not type_expr.generic_args:
        return True
    root = _emitted_name(type_expr)
    cache = getattr(gen, "_cycle_may_cache", None)
    if cache is None:
        cache = {}
        gen._cycle_may_cache = cache
    if root in cache:
        return cache[root]

    visited: set[str] = set()
    stack = _outgoing_managed_types(gen, type_expr)
    while stack:
        current = stack.pop()
        emitted = _emitted_name(current)
        if emitted == root:
            cache[root] = True
            return True
        if emitted in visited:
            continue
        visited.add(emitted)
        stack.extend(_outgoing_managed_types(gen, current))
    cache[root] = False
    return False


def _outgoing_managed_types(gen, type_expr: TypeExpr) -> list[TypeExpr]:
    from .polymorphic_cycles import runtime_type_candidates

    type_expr = canonical_cycle_type(gen, type_expr) or type_expr
    if not _is_managed_reference(gen, type_expr):
        return []
    from .managed_values import is_mutex_type

    if is_mutex_type(gen, type_expr):
        payload = type_expr.generic_args[0]
        if not _is_managed_reference(gen, payload):
            return []
        return list(runtime_type_candidates(gen, payload))
    info = gen.analyzed.class_table[type_expr.base]
    arguments = list(type_expr.generic_args)
    if arguments and type_expr.base in BUILTIN_COLLECTION_LAYOUTS:
        if type_expr.base == "List":
            candidates = [TypeExpr(base="ListNode", generic_args=[arguments[0]])]
        else:
            candidates = arguments
        return [
            runtime_type
            for candidate in candidates
            if _is_managed_reference(gen, candidate)
            for runtime_type in runtime_type_candidates(gen, candidate)
        ]

    substitutions = dict(zip(info.generic_params, arguments))
    if substitutions:
        candidates = [
            substitute_cycle_type(gen, field.type, substitutions)
            for _name, field in info.instance_storage
            if field.type is not None
        ]
    else:
        candidates = [field.type for _name, field in info.instance_storage if field.type is not None]
    outgoing = []
    for candidate in candidates:
        if _is_managed_reference(gen, candidate):
            outgoing.extend(runtime_type_candidates(gen, candidate))
    return outgoing


def _type_has_visit_action(gen, type_expr: TypeExpr, seen: set[tuple]) -> bool:
    return visit_action(gen, type_expr, seen) is not None


def _is_managed_reference(gen, type_expr: TypeExpr | None) -> bool:
    from .managed_values import is_arc_type

    return bool(type_expr is not None and is_arc_type(gen, type_expr))


def _emitted_name(type_expr: TypeExpr) -> str:
    if type_expr.generic_args:
        return mangle_generic_type(type_expr.base, type_expr.generic_args)
    return type_expr.base


__all__ = [
    "BUILTIN_COLLECTION_LAYOUTS",
    "DirectVisitAction",
    "cycle_visitor_symbol",
    "emitted_type_has_visitor",
    "emitted_type_may_cycle",
    "generic_instance_may_cycle",
    "generic_instance_needs_visitor",
    "register_cycle_classification",
    "register_cycle_visitor",
    "type_may_cycle",
    "type_needs_visitor",
    "visit_action",
    "visitor_for_type",
]
