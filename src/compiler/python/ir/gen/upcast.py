"""Class-pointer upcasting (Derived* → Base*) for IR generation.

A btrc subclass and its base compile to *separate* C structs, so a
``Derived*`` is not assignment-compatible with a ``Base*`` in C. Older
compilers only warned about the implicit conversion; gcc 15 promotes
``-Wincompatible-pointer-types`` to a hard error. Every site where a
class-typed value flows into a base-class context therefore needs an explicit
``(Base*)`` cast.

This module centralizes that logic. ``is_subclass`` answers the inheritance
question; ``upcast_class_pointer`` wraps a value in an ``IRCast`` when (and only
when) the target is a concrete (non-generic) class and the source's static type
is a strict subclass of it. Generic class instances are pointers to the SAME
mangled struct regardless of subclassing, so they are left untouched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..nodes import IRCast, IRExpr
from .types import type_to_c

if TYPE_CHECKING:
    from ...ast_nodes import TypeExpr
    from .generator import IRGenerator


def is_subclass(gen: IRGenerator, sub: str | None, base: str | None) -> bool:
    """True if `base` is a (transitive) parent class of `sub`."""
    if not sub or not base:
        return False
    ct = gen.analyzed.class_table
    seen: set[str] = set()
    cur = sub
    while cur and cur not in seen:
        if cur == base:
            return True
        seen.add(cur)
        info = ct.get(cur)
        cur = info.parent if info else None
    return False


def upcast_class_pointer(gen: IRGenerator, target_type: TypeExpr | None,
                         source_type: TypeExpr | None,
                         value: IRExpr) -> IRExpr:
    """Wrap `value` in an explicit ``(Base*)`` cast for a Derived→Base upcast.

    Returns `value` unchanged unless ALL of the following hold:
      - `target_type` is a concrete class in the class table with NO generic args
        (a sibling/derived struct pointer is otherwise incompatible C);
      - `source_type` names a DIFFERENT class that is a strict subclass of
        `target_type.base`.

    Generic class targets are skipped: all instances of a generic share one
    mangled struct, so no upcast is needed (and the cast text would be wrong).
    """
    if target_type is None or source_type is None:
        return value
    ct = gen.analyzed.class_table
    if target_type.base not in ct or target_type.generic_args:
        return value
    if source_type.base == target_type.base:
        return value
    if not is_subclass(gen, source_type.base, target_type.base):
        return value
    return IRCast(target_type=type_to_c(target_type), expr=value)
