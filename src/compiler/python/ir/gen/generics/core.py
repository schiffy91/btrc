"""Core generic monomorphization: dispatch + shared helpers."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import CType, IRStructDef, IRStructField
from ..types import type_to_c, mangle_generic_type, mangle_type_name, is_concrete_instance

if TYPE_CHECKING:
    from ..generator import IRGenerator


def emit_generic_instances(gen: IRGenerator):
    """Emit all monomorphized generic class types and their methods.

    ALL generic classes (stdlib and user-defined) go through user.py.
    No type-name-specific dispatch — the stdlib .btrc files define
    everything and user.py emits the monomorphized C code.
    """
    from .user import _emit_user_generic_instance

    # Emit C11 _Generic macros for type-dependent operations.
    # These are used by stdlib .btrc files (__btrc_eq, __btrc_lt, etc.)
    # and resolved at C compile time based on argument type.
    _emit_generic_macros(gen)

    seen = set()
    changed = True
    while changed:
        changed = False
        for base_name, instances in list(gen.analyzed.generic_instances.items()):
            for args in instances:
                if not is_concrete_instance(args):
                    continue
                mangled = mangle_generic_type(base_name, list(args))
                if mangled in seen:
                    continue
                seen.add(mangled)
                changed = True
                _emit_user_generic_instance(gen, base_name, list(args))


def _resolve_type(t: TypeExpr | None, type_map: dict[str, TypeExpr]) -> TypeExpr:
    """Replace generic type parameters with concrete types."""
    if t is None:
        return TypeExpr(base="void")
    if t.base in type_map and not t.generic_args:
        resolved = type_map[t.base]
        # Combine pointer depths: T* with T→int becomes int*
        if t.pointer_depth > 0:
            return TypeExpr(
                base=resolved.base,
                generic_args=resolved.generic_args,
                pointer_depth=resolved.pointer_depth + t.pointer_depth,
            )
        return resolved
    if t.generic_args:
        resolved_args = [_resolve_type(a, type_map) for a in t.generic_args]
        return TypeExpr(base=t.base, generic_args=resolved_args,
                       pointer_depth=t.pointer_depth)
    return t


# --- C11 _Generic macros for type-dependent operations ---

_GENERIC_MACROS = (
    "/* Type-dependent comparison/hashing macros for generic collections.\n"
    " * Uses __builtin_choose_expr — unselected branch is NOT evaluated.\n"
    " * Cast chain (void*)(intptr_t) avoids float-to-pointer hard errors. */\n"
    "#define __btrc_eq(a, b) __builtin_choose_expr( \\\n"
    "    __builtin_types_compatible_p(__typeof__(a), char*), \\\n"
    "    strcmp((const char*)(void*)(intptr_t)(a), "
    "(const char*)(void*)(intptr_t)(b)) == 0, \\\n"
    "    (a) == (b))\n"
    "#define __btrc_lt(a, b) __builtin_choose_expr( \\\n"
    "    __builtin_types_compatible_p(__typeof__(a), char*), \\\n"
    "    strcmp((const char*)(void*)(intptr_t)(a), "
    "(const char*)(void*)(intptr_t)(b)) < 0, \\\n"
    "    (a) < (b))\n"
    "#define __btrc_gt(a, b) __builtin_choose_expr( \\\n"
    "    __builtin_types_compatible_p(__typeof__(a), char*), \\\n"
    "    strcmp((const char*)(void*)(intptr_t)(a), "
    "(const char*)(void*)(intptr_t)(b)) > 0, \\\n"
    "    (a) > (b))\n"
    "#define __btrc_hash(k) __builtin_choose_expr( \\\n"
    "    __builtin_types_compatible_p(__typeof__(k), char*), \\\n"
    "    __btrc_hash_str((const char*)(void*)(intptr_t)(k)), \\\n"
    "    (unsigned int)(intptr_t)(k))"
)


def _emit_generic_macros(gen: IRGenerator):
    """Emit _Generic macros if any generic instances exist."""
    has_generics = any(
        is_concrete_instance(args)
        for instances in gen.analyzed.generic_instances.values()
        for args in instances
    )
    if has_generics:
        gen.use_helper("__btrc_hash_str")
        gen.module.raw_sections.append(_GENERIC_MACROS)


# --- String-aware comparison helpers (kept for non-generic use) ---
def _eq(elem_c: str, a: str, b: str) -> str:
    if elem_c == "char*":
        return f"strcmp({a}, {b}) == 0"
    return f"{a} == {b}"

def _gt(elem_c: str, a: str, b: str) -> str:
    if elem_c == "char*":
        return f"strcmp({a}, {b}) > 0"
    return f"{a} > {b}"

def _lt(elem_c: str, a: str, b: str) -> str:
    if elem_c == "char*":
        return f"strcmp({a}, {b}) < 0"
    return f"{a} < {b}"
