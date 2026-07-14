"""Shared-state runtime helpers for the precompiled-stdlib archive.

A few runtime helper groups carry *process-global* mutable state that must be a
single instance shared by the archive and every program that links it (the
try/catch stacks, the cleanup stack, the destroyed-pointer guard, and the cycle
suspect queue, and the managed-string registry). Every pointer, index/count,
capacity, lock, and callback-table member of each group must have the same
linkage. The archive defines them once with external linkage and the public
header publishes matching declarations.

To prevent the declarations from drifting out of sync with the real helper text
(the bug class this module exists to kill — e.g. ``__btrc_try_top`` gaining a
``volatile`` qualifier, or ``__btrc_cleanup_entry`` gaining a ``visit`` member),
both the header (extern) declarations and the single-instance ``.c`` definitions
are *derived* from each helper's actual ``c_source`` rather than hardcoded.
"""

from __future__ import annotations

# Helper-level ownership groups whose state must be a single shared instance.
# Keeping these as named groups makes a pointer/count/capacity split visible in
# review instead of relying on an unrelated flat allow-list.
SHARED_STATE_HELPER_GROUPS = {
    "try_stack": frozenset(
        {
            "__btrc_try_level",
            "__btrc_trycatch_globals",
        }
    ),
    "cleanup_stack": frozenset(
        {
            "__btrc_cleanup_types",
            "__btrc_cleanup_capacity",
        }
    ),
    "destroyed_log": frozenset(
        {
            "__btrc_destroyed_tracking",
            "__btrc_destroyed_capacity",
        }
    ),
    "cycle_suspects": frozenset(
        {
            "__btrc_suspect_state",
            "__btrc_suspect_capacity",
        }
    ),
    "string_registry": frozenset(
        {
            "__btrc_string_registry",
            "__btrc_string_registry_resize",
            "__btrc_string_live_count",
        }
    ),
}
SHARED_STATE_HELPER_NAMES = frozenset().union(*SHARED_STATE_HELPER_GROUPS.values())


def externize_toplevel(text: str) -> str:
    """Strip a leading ``static``/``static inline`` from each *top-level* (column
    0) declaration so the symbol gets external linkage. Indented lines (function
    bodies) are left untouched.
    """
    out = []
    for line in text.split("\n"):
        if line.startswith("static inline "):
            out.append(line[len("static inline ") :])
        elif line.startswith("static "):
            out.append(line[len("static ") :])
        else:
            out.append(line)
    return "\n".join(out)


def _split_toplevel_units(c_source: str) -> list[str]:
    """Split C helper source into its top-level units (one per declaration or
    function definition), dropping blank lines and standalone comments. Tracks
    brace depth so a unit spanning multiple lines (a function body) stays whole;
    a unit at depth 0 ends at a ``;`` or at the ``}`` that closes its body.
    """
    units: list[str] = []
    cur: list[str] = []
    depth = 0
    for line in c_source.split("\n"):
        stripped = line.strip()
        if not cur and (
            not stripped or stripped.startswith("/*") or stripped.startswith("*") or stripped.startswith("//")
        ):
            # Leading comment / blank line before any unit content — skip it.
            continue
        cur.append(line)
        depth += line.count("{") - line.count("}")
        if depth == 0 and (stripped.endswith(";") or stripped.endswith("}")):
            units.append("\n".join(cur))
            cur = []
    if cur:
        units.append("\n".join(cur))
    return units


def _function_definition_prototype(unit: str) -> str | None:
    """Derive a prototype from one raw helper function definition."""

    brace = unit.find("{")
    if brace < 0:
        return None
    signature = unit[:brace].rstrip()
    if "(" not in signature or signature.endswith("="):
        return None
    return signature + ";"


def derive_shared_decls(c_source: str) -> str:
    """Derive the header (extern) declarations for a shared-state helper from its
    real ``c_source``. typedefs pass through verbatim (the type must be visible
    to every TU). A top-level variable definition ``static T x = init;`` becomes
    ``extern T x;``. A top-level function definition becomes its prototype.
    """
    out: list[str] = []
    for unit in _split_toplevel_units(c_source):
        if unit.lstrip().startswith("typedef"):
            out.append(unit)
            continue
        proto = _function_definition_prototype(unit)
        if proto is not None:
            # Function definition -> prototype (already extern by default).
            out.append(externize_toplevel(proto))
            continue
        # Variable definition: strip leading `static`, drop the initializer, and
        # publish as `extern`.
        decl = externize_toplevel(unit).rstrip().rstrip(";")
        eq = decl.find("=")
        if eq != -1:
            decl = decl[:eq].rstrip()
        out.append(f"extern {decl};")
    return "\n".join(out)


def derive_shared_impl(c_source: str) -> str:
    """Derive the archive ``.c`` single-instance definitions for a shared-state
    helper from its real ``c_source``: every top-level definition with its
    leading ``static`` stripped (so it has external linkage), but typedefs
    dropped — they live in the header and re-emitting them in the .c is redundant.
    Function bodies and initialized data are kept intact.
    """
    out: list[str] = []
    for unit in _split_toplevel_units(c_source):
        if unit.lstrip().startswith("typedef"):
            continue
        out.append(externize_toplevel(unit))
    return "\n".join(out)
