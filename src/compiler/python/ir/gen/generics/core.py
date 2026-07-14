"""Core generic monomorphization: dispatch + shared helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ....type_identity import TypeShapeError, substitute_type_expr
from ..errors import CodegenError
from ..types import mangle_generic_type

if TYPE_CHECKING:
    from ..generator import IRGenerator


def emit_generic_instances(gen: IRGenerator):
    """Emit all monomorphized generic class types and their methods.

    ALL generic classes (stdlib and user-defined) go through user.py.
    No type-name-specific dispatch — the stdlib .btrc files define
    everything and user.py emits the monomorphized C code.

    Uses a shared `seen` set passed to user.py so that transitive
    dependencies (e.g. ListNode<string> needed by List<string>) are
    emitted before the types that reference them.
    """
    from .user import _emit_user_generic_instance

    seen = set()
    changed = True
    while changed:
        changed = False
        for base_name, instances in list(gen.analyzed.generic_instances.items()):
            for args in instances:
                mangled = mangle_generic_type(base_name, list(args))
                if mangled in seen:
                    continue
                seen.add(mangled)
                changed = True
                _emit_user_generic_instance(gen, base_name, list(args), seen)


def _resolve_type(t: TypeExpr | None, type_map: dict[str, TypeExpr]) -> TypeExpr:
    """Replace generic parameters while preserving both types' metadata."""
    try:
        return substitute_type_expr(t, type_map) or TypeExpr(base="void")
    except TypeShapeError as error:
        raise CodegenError(str(error)) from error
