"""Monomorphization of generic methods (method-level type parameters).

A generic method introduces its own type parameters on top of any class-level
generics, e.g. ``Vector<U> mapTo<U>(__fn_ptr<U, T> fn)``. The analyzer records
each call site's (class_args, method_args) combination in
``analyzed.generic_method_instances``; here we emit one monomorphized C function
per combination.

Mangling: ``{class_mangled}_{method}_{method_arg_mangles}``, e.g.
``btrc_Vector_int_mapTo_string`` for ``Vector<int>.mapTo<string>`` and
``btrc_Box_int_convert_string`` for ``Box<int>.convert<string>``. The class part
is the concrete class specialization symbol (or the bare class name for a
non-generic owner); the method part appends each method type argument's mangle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...cycle_boundaries import (
    PUBLIC_COLLECTION_BASES,
    FunctionCycleBoundary,
)
from ...nodes import (
    CType,
    IRBlock,
    IRCast,
    IRExprStmt,
    IRFunctionDecl,
    IRFunctionDef,
    IRParam,
    IRVar,
)
from ...topology_boundaries import CollectionTopologyBoundary
from ..parameters import lower_source_param
from .user_emitter import _UserGenericEmitter

if TYPE_CHECKING:
    from ..lowerer import IRLowerer


def emit_generic_method_instances(
    gen: IRLowerer,
    type_renderer,
    default_arguments,
):
    """Emit every monomorphized generic-method function recorded by the analyzer.

    Each function is emitted with a combined type map binding both the class
    type parameters (T, ...) and the method type parameters (U, ...) to the
    concrete types for that call site. Bodies are lowered by the same
    _UserGenericEmitter used for ordinary generic methods, so cross-type method
    dispatch (e.g. building a Vector<U> inside the body) resolves naturally.
    """
    instances = getattr(gen.analyzed, "generic_method_instances", None)
    if not instances:
        return

    for (class_base, method_name), combos in instances.items():
        cls_info = gen.analyzed.class_table.get(class_base)
        if not cls_info:
            continue
        method = cls_info.methods.get(method_name)
        if not method or not getattr(method, "generic_params", None):
            continue
        for class_args, method_args in combos:
            _emit_one_method_instance(
                gen,
                class_base,
                cls_info,
                method,
                class_args,
                method_args,
                type_renderer,
                default_arguments,
            )


def _build_type_map(cls_info, method, class_args, method_args) -> dict:
    """Combined {class_param: concrete, method_param: concrete} mapping."""
    type_map = {}
    for i, gp in enumerate(cls_info.generic_params):
        if i < len(class_args):
            type_map[gp] = class_args[i]
    for i, gp in enumerate(method.generic_params):
        if i < len(method_args):
            type_map[gp] = method_args[i]
    return type_map


def _emit_one_method_instance(
    gen,
    class_base,
    cls_info,
    method,
    class_args,
    method_args,
    type_renderer,
    default_arguments,
):
    if class_args:
        gen.type_identity.ensure_supported_generic_arguments(class_args)
        self_mangled = gen.type_identity.generic_symbol(class_base, class_args)
    else:
        self_mangled = class_base
    fn_name = gen.type_identity.method_instance_symbol(
        class_base,
        class_args,
        method.name,
        method_args,
    )

    type_map = _build_type_map(cls_info, method, class_args, method_args)
    emitter = _UserGenericEmitter(
        type_map,
        self_mangled,
        type_renderer,
        gen=gen,
        cls_info=cls_info,
        default_arguments=default_arguments,
    )
    public_collection_method = class_base in PUBLIC_COLLECTION_BASES and method.access == "public"
    emitter.reset_var_types(
        method.params,
        method.return_type,
        batch_explicit_releases=public_collection_method,
    )

    ret_c = emitter.resolve_c(method.return_type) if method.return_type else "void"
    params_ir = [IRParam(c_type=CType(text=f"{self_mangled}*"), name="self")]
    for p in method.params:
        params_ir.append(
            lower_source_param(
                p,
                emitter.resolve_c,
                emitter._gen.analyzed,
                resolved_type=emitter._resolve(p.type),
            )
        )

    body_stmts = emitter.emit_stmts(method.body.statements) if method.body else []
    if not body_stmts:
        body_stmts = [IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="self")))]

    gen.module.function_decls.append(
        IRFunctionDecl(
            name=fn_name,
            return_type=CType(text=ret_c),
            params=list(params_ir),
            is_static=True,
        )
    )

    function = IRFunctionDef(
        name=fn_name,
        return_type=CType(text=ret_c),
        params=params_ir,
        body=IRBlock(stmts=body_stmts),
        is_static=True,
    )
    if class_base in PUBLIC_COLLECTION_BASES and gen.cycles.generic_instance_needs_visitor(
        class_base, list(class_args)
    ):
        CollectionTopologyBoundary(gen, function).install()
    if public_collection_method and FunctionCycleBoundary(function).install():
        gen.helpers.use("__btrc_flush_cycles")
    gen.module.function_defs.append(function)
