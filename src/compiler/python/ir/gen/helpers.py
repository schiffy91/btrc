"""Runtime helper collection: determine which helpers the IR module needs."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ..nodes import IRHelperDecl
from ..helpers.registry import HELPERS
from ..helpers.core import HelperDef

if TYPE_CHECKING:
    from .generator import IRGenerator


def collect_helpers(gen: IRGenerator):
    """Register all used helpers as IRHelperDecl entries on the module."""
    if not gen._used_helpers:
        return

    # Build reverse map: helper name → (category, HelperDef)
    name_to_info: dict[str, tuple[str, HelperDef]] = {}
    for cat, helpers in HELPERS.items():
        for name, hdef in helpers.items():
            name_to_info[name] = (cat, hdef)

    # Resolve transitive dependencies
    needed: set[str] = set(gen._used_helpers)
    worklist = list(needed)
    while worklist:
        name = worklist.pop()
        if name not in name_to_info:
            continue
        cat, hdef = name_to_info[name]
        for dep in hdef.depends_on:
            if dep not in needed:
                needed.add(dep)
                worklist.append(dep)

    # Also include category-level dependencies
    needed_cats: set[str] = set()
    for name in needed:
        if name in name_to_info:
            needed_cats.add(name_to_info[name][0])

    # Emit helpers in category order, preserving dependency order
    category_order = ["alloc", "divmod", "string_pool", "string", "math",
                      "trycatch", "hash", "collections", "cycles"]
    for cat in category_order:
        if cat not in HELPERS:
            continue
        for name, hdef in HELPERS[cat].items():
            if name in needed or cat in needed_cats and name in name_to_info:
                # Only include if the specific helper is needed, or its
                # category is needed and it's a dependency
                if name in needed:
                    gen.module.helper_decls.append(IRHelperDecl(
                        category=cat,
                        name=name,
                        c_source=hdef.c_source,
                        depends_on=hdef.depends_on,
                    ))
