"""Core generic monomorphization: dispatch + shared helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ....type_identity import TypeIdentity, TypeShapeError
from ..errors import CodegenError
from ..type_resolution import substitute_concrete_type

if TYPE_CHECKING:
    from ..lowerer import IRLowerer


def emit_generic_instances(
    gen: IRLowerer,
    type_renderer,
    default_arguments,
):
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
                gen.type_identity.ensure_supported_generic_arguments(args)
                mangled = gen.type_identity.generic_symbol(base_name, args)
                if mangled in seen:
                    continue
                seen.add(mangled)
                changed = True
                _emit_user_generic_instance(
                    gen,
                    base_name,
                    list(args),
                    type_renderer,
                    default_arguments,
                    seen,
                )


def _resolve_type(
    t: TypeExpr | None,
    type_map: dict[str, TypeExpr],
    typedefs: dict[str, TypeExpr] | None,
    type_identity: TypeIdentity,
) -> TypeExpr:
    """Replace generic parameters while preserving both types' metadata."""
    try:
        resolved = substitute_concrete_type(t, type_map, typedefs or {}, type_identity)
        return resolved or TypeExpr(base="void")
    except TypeShapeError as error:
        raise CodegenError(str(error)) from error


def _resolve_type_c(
    t: TypeExpr | None,
    type_map: dict[str, TypeExpr],
    typedefs: dict[str, TypeExpr] | None,
    type_identity: TypeIdentity,
    *,
    render,
) -> str:
    """Render a substituted type without flattening its pointer layers.

    ``TypeExpr`` records nullable and pointer modifiers on one flat node.  A
    template such as ``T*`` therefore loses an important boundary when ``T``
    is itself nullable: flattening ``T*`` with ``T = int?`` produces the same
    shape as source ``int*?``, although their C representations are ``int**``
    and ``int*`` respectively.  Render the concrete value first, then append
    only the template's applied storage layers.
    """
    resolved = _resolve_type(t, type_map, typedefs, type_identity)
    if t is None or t.base not in type_map or t.generic_args:
        return render(resolved)

    concrete = type_map[t.base]
    applied_depth = resolved.pointer_depth - concrete.pointer_depth
    if applied_depth < 0:
        raise CodegenError("generic substitution produced a negative pointer depth")
    c_type = render(concrete)
    if t.is_const and not concrete.is_const:
        c_type = "const " + c_type
    c_type += "*" * applied_depth
    if t.is_array:
        c_type += "*"
    return c_type


def _generic_lvalue_c_type(emitter, target, _resolved):
    """Render a direct lvalue from its generic source template, when known."""
    if emitter._gen is None:
        return None
    template = emitter._gen.analyzed.node_types.get(id(target))
    if template is None or not emitter.type_identity.references_names(template, emitter.type_map):
        return None
    return emitter.resolve_c(template)
