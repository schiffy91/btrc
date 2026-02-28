"""User-defined generic class monomorphization: struct + methods."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import CType, IRStructDef, IRStructField
from ..types import type_to_c, mangle_generic_type
from .core import _resolve_type
from .user_methods import _emit_user_generic_methods

if TYPE_CHECKING:
    from ..generator import IRGenerator


def _register_transitive_generic_deps(gen: IRGenerator, cls_info,
                                       type_map: dict[str, TypeExpr]):
    """Scan resolved field types for generic class references and register them.

    When List<string> has a field of type ListNode<T>, resolving T->string
    gives ListNode<string>. This must be registered as a new generic instance
    so the while-changed loop in core.py emits it.
    """
    for _name, fd in cls_info.fields.items():
        resolved = _resolve_type(fd.type, type_map)
        _register_if_generic(gen, resolved)
    # Also scan method return types and parameter types
    for method in cls_info.methods.values():
        if method.return_type:
            resolved = _resolve_type(method.return_type, type_map)
            _register_if_generic(gen, resolved)
        for p in method.params:
            if p.type:
                resolved = _resolve_type(p.type, type_map)
                _register_if_generic(gen, resolved)


def _register_if_generic(gen: IRGenerator, t: TypeExpr):
    """Register a resolved type as a generic instance if it's a generic class."""
    if not t or not t.generic_args:
        return
    cls = gen.analyzed.class_table.get(t.base)
    if cls and cls.generic_params:
        instances = gen.analyzed.generic_instances.setdefault(t.base, [])
        args_tuple = tuple(t.generic_args)
        if args_tuple not in instances:
            instances.append(args_tuple)


def _emit_user_generic_instance(gen: IRGenerator, base_name: str,
                                 args: list[TypeExpr],
                                 seen: set | None = None):
    """Emit a user-defined generic class instance (struct + methods).

    The `seen` set tracks already-emitted mangled names. When field types
    reference other generic classes (transitive deps), those are emitted
    first so their forward declarations and method definitions appear
    before the current type's method bodies.
    """
    cls_info = gen.analyzed.class_table.get(base_name)
    if not cls_info:
        return
    mangled = mangle_generic_type(base_name, args)

    # Build type parameter mapping
    type_map = {}
    for i, gp in enumerate(cls_info.generic_params):
        if i < len(args):
            type_map[gp] = args[i]

    # Register transitive generic dependencies (e.g. ListNode<string> from List<string>)
    _register_transitive_generic_deps(gen, cls_info, type_map)

    # Recursively emit transitive field-type dependencies FIRST
    if seen is not None:
        for _name, fd in cls_info.fields.items():
            resolved = _resolve_type(fd.type, type_map)
            if resolved.generic_args and resolved.base in gen.analyzed.class_table:
                dep_cls = gen.analyzed.class_table[resolved.base]
                if dep_cls.generic_params:
                    dep_mangled = mangle_generic_type(resolved.base,
                                                      list(resolved.generic_args))
                    if dep_mangled not in seen:
                        seen.add(dep_mangled)
                        _emit_user_generic_instance(
                            gen, resolved.base, list(resolved.generic_args), seen)

    # Emit forward typedef if not already present (for transitive deps
    # discovered after the initial forward_decls pass in generator.py)
    fwd = f"typedef struct {mangled} {mangled};"
    if fwd not in gen.module.forward_decls:
        gen.module.forward_decls.append(fwd)

    # Emit struct with resolved types (ARC: __rc as first field)
    fields = [IRStructField(c_type=CType(text="int"), name="__rc")]
    for name, fd in cls_info.fields.items():
        resolved = _resolve_type(fd.type, type_map)
        fields.append(IRStructField(c_type=CType(text=type_to_c(resolved)), name=name))
    gen.module.struct_defs.append(IRStructDef(name=mangled, fields=fields))

    # Emit constructor, destructor, and methods
    _emit_user_generic_methods(gen, base_name, mangled, args, type_map, cls_info)
