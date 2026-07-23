"""User-defined generic class monomorphization: struct + methods."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import IRStructDef, IRStructForward
from ..arc_metadata import arc_header_field
from ..class_storage_fields import lower_instance_storage_field
from .core import _resolve_type
from .user_emitter import _UserGenericEmitter
from .user_methods import _emit_user_generic_methods

if TYPE_CHECKING:
    from ..lowerer import IRLowerer


def _register_transitive_generic_deps(gen: IRLowerer, cls_info, type_map: dict[str, TypeExpr]):
    """Scan resolved field types for generic class references and register them.

    When List<string> has a field of type ListNode<T>, resolving T->string
    gives ListNode<string>. This must be registered as a new generic instance
    so the while-changed loop in core.py emits it.
    """
    for _name, fd in cls_info.instance_storage:
        resolved = _resolve_type(fd.type, type_map, gen.analyzed.typedef_table, gen.type_identity)
        _register_if_generic(gen, resolved)
    # Also scan method return types and parameter types
    for method in cls_info.methods.values():
        if method.return_type:
            resolved = _resolve_type(method.return_type, type_map, gen.analyzed.typedef_table, gen.type_identity)
            _register_if_generic(gen, resolved, method.generic_params)
        for p in method.params:
            if p.type:
                resolved = _resolve_type(p.type, type_map, gen.analyzed.typedef_table, gen.type_identity)
                _register_if_generic(gen, resolved, method.generic_params)


def _register_if_generic(gen: IRLowerer, t: TypeExpr, unresolved=()):
    """Register a resolved type as a generic instance if it's a generic class."""
    if not t or not t.generic_args or gen.type_identity.references_names(t, unresolved):
        return
    cls = gen.analyzed.class_table.get(t.base)
    if cls and cls.generic_params:
        instances = gen.analyzed.generic_instances.setdefault(t.base, [])
        args_tuple = tuple(t.generic_args)
        target = gen.type_identity.generic_instance_key(t.base, args_tuple)
        if not any(gen.type_identity.generic_instance_key(t.base, existing) == target for existing in instances):
            instances.append(args_tuple)


def _emit_user_generic_instance(
    gen: IRLowerer,
    base_name: str,
    args: list[TypeExpr],
    type_renderer,
    default_arguments,
    seen: set | None = None,
):
    """Emit a user-defined generic class instance (struct + methods).

    The `seen` set tracks already-emitted mangled names. When field types
    reference other generic classes (transitive deps), those are emitted
    first so their forward declarations and method definitions appear
    before the current type's method bodies.
    """
    cls_info = gen.analyzed.class_table.get(base_name)
    if not cls_info:
        return
    gen.type_identity.ensure_supported_generic_arguments(args)
    mangled = gen.type_identity.generic_symbol(base_name, args)

    # Build type parameter mapping
    type_map = {}
    for i, gp in enumerate(cls_info.generic_params):
        if i < len(args):
            type_map[gp] = args[i]

    # Register transitive generic dependencies (e.g. ListNode<string> from List<string>)
    _register_transitive_generic_deps(gen, cls_info, type_map)

    # Recursively emit transitive field-type dependencies FIRST
    if seen is not None:
        for _name, fd in cls_info.instance_storage:
            resolved = _resolve_type(fd.type, type_map, gen.analyzed.typedef_table, gen.type_identity)
            if resolved.generic_args and resolved.base in gen.analyzed.class_table:
                dep_cls = gen.analyzed.class_table[resolved.base]
                if dep_cls.generic_params:
                    gen.type_identity.ensure_supported_generic_arguments(resolved.generic_args)
                    dep_mangled = gen.type_identity.generic_symbol(resolved.base, resolved.generic_args)
                    if dep_mangled not in seen:
                        seen.add(dep_mangled)
                        _emit_user_generic_instance(
                            gen,
                            resolved.base,
                            list(resolved.generic_args),
                            type_renderer,
                            default_arguments,
                            seen,
                        )

    # Transitive dependencies may be discovered after the initial declaration
    # pass, so register their typed struct forward on demand.
    forward = IRStructForward(name=mangled)
    if forward not in gen.module.struct_forwards:
        gen.module.struct_forwards.append(forward)

    # A concrete generic instance carries the same first-member ARC header as
    # an ordinary class; its descriptor is emitted by the lifecycle pass.
    fields = [arc_header_field(gen)]
    bound_emitter = _UserGenericEmitter(
        type_map,
        mangled,
        type_renderer,
        gen=gen,
        cls_info=cls_info,
        default_arguments=default_arguments,
    )
    for name, fd in cls_info.instance_storage:
        resolved = _resolve_type(
            fd.type,
            type_map,
            gen.analyzed.typedef_table,
            gen.type_identity,
        )
        fields.append(
            lower_instance_storage_field(
                gen,
                name,
                resolved,
                type_renderer,
                bound_lowerer=bound_emitter._expr,
            )
        )
    gen.module.struct_defs.append(IRStructDef(name=mangled, fields=fields))

    # Emit constructor, destructor, and methods
    _emit_user_generic_methods(
        gen,
        base_name,
        mangled,
        args,
        type_map,
        cls_info,
        type_renderer,
        default_arguments,
    )
