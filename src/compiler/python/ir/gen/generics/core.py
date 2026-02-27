"""Core generic monomorphization: dispatch + shared helpers."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import CType, IRStructDef, IRStructField
from ..types import type_to_c, mangle_generic_type, mangle_type_name, is_concrete_instance

if TYPE_CHECKING:
    from ..generator import IRGenerator


def emit_generic_instances(gen: IRGenerator):
    """Emit all monomorphized generic collection types and their methods."""
    from .lists import _emit_list_instance
    from .maps import _emit_map_instance
    from .sets import _emit_set_instance
    from .user import _emit_user_generic_instance

    seen = set()
    for base_name, instances in gen.analyzed.generic_instances.items():
        for args in instances:
            if not is_concrete_instance(args):
                continue  # Skip unresolved type params (T, K, V)
            mangled = mangle_generic_type(base_name, list(args))
            if mangled in seen:
                continue  # Dedup
            seen.add(mangled)
            if base_name == "List":
                _emit_list_instance(gen, list(args))
            elif base_name == "Map":
                _emit_map_instance(gen, list(args))
            elif base_name == "Set":
                _emit_set_instance(gen, list(args))
            else:
                _emit_user_generic_instance(gen, base_name, list(args))


def _resolve_type(t: TypeExpr | None, type_map: dict[str, TypeExpr]) -> TypeExpr:
    """Replace generic type parameters with concrete types."""
    if t is None:
        return TypeExpr(base="void")
    if t.base in type_map and not t.generic_args:
        return type_map[t.base]
    if t.generic_args:
        resolved_args = [_resolve_type(a, type_map) for a in t.generic_args]
        return TypeExpr(base=t.base, generic_args=resolved_args,
                       pointer_depth=t.pointer_depth)
    return t


# --- String-aware comparison helpers ---
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
