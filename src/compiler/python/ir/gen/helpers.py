"""Runtime helper collection: determine which helpers the IR module needs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..helpers.core import HelperDef
from ..helpers.registry import HELPERS
from ..nodes import IRHelperDecl

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
                      "trycatch", "hash", "collections", "cycles", "threads"]
    # __btrc_run_cleanups / __btrc_throw are cycle-safe unwinders: they call
    # __btrc_collect_cycles / __btrc_suspect and reference the
    # __btrc_visit_fn / __btrc_destroy_fn typedefs declared by the cycles
    # helpers, so they must be emitted AFTER the cycles category even though
    # they live in the trycatch category. Defer them and re-append at the end.
    deferred = ("__btrc_run_cleanups", "__btrc_throw")
    deferred_decls: list[IRHelperDecl] = []
    for cat in category_order:
        if cat not in HELPERS:
            continue
        for name, hdef in HELPERS[cat].items():
            if name in needed:
                decl = IRHelperDecl(
                    category=cat,
                    name=name,
                    c_source=hdef.c_source,
                    depends_on=hdef.depends_on,
                )
                if name in deferred:
                    deferred_decls.append(decl)
                else:
                    gen.module.helper_decls.append(decl)
    gen.module.helper_decls.extend(deferred_decls)
