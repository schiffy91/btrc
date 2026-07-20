"""Archive-owned contracts for stateless runtime helper families."""

from __future__ import annotations

from .stdlib_shared_state import (
    _function_definition_prototype,
    _split_toplevel_units,
    externize_toplevel,
)

ARCHIVE_HELPER_API_GROUPS = {
    "thread_handle": frozenset(
        {
            "__btrc_thread_spawn",
            "__btrc_thread_join",
            "__btrc_thread_free",
        }
    ),
}
ARCHIVE_HELPER_API_NAMES = frozenset().union(*ARCHIVE_HELPER_API_GROUPS.values())


def _defines_function(unit: str, name: str) -> bool:
    prototype = _function_definition_prototype(unit)
    return prototype is not None and f"{name}(" in "".join(prototype.split())


def derive_archive_api_decls(c_source: str, public_name: str) -> str:
    """Publish typedefs and one selected helper function prototype."""

    out = []
    for unit in _split_toplevel_units(c_source):
        if unit.lstrip().startswith("typedef"):
            out.append(unit)
        elif _defines_function(unit, public_name):
            prototype = _function_definition_prototype(unit)
            assert prototype is not None
            out.append(externize_toplevel(prototype))
    return "\n".join(out)


def derive_archive_api_impl(c_source: str, public_name: str) -> str:
    """Externalize one public helper while retaining its private internals."""

    out = []
    for unit in _split_toplevel_units(c_source):
        if unit.lstrip().startswith("typedef"):
            continue
        if _defines_function(unit, public_name):
            unit = externize_toplevel(unit)
        out.append(unit)
    return "\n".join(out)
