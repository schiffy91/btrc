"""Monomorphization of generic methods (method-level type parameters).

A generic method introduces its own type parameters on top of any class-level
generics, e.g. ``Vector<U> mapTo<U>(__fn_ptr<U, T> fn)``. The analyzer records
each call site's (class_args, method_args) combination in
``analyzed.generic_method_instances``; here we emit one monomorphized C function
per combination.

Mangling: ``{class_mangled}_{method}_{method_arg_mangles}``, e.g.
``btrc_Vector_int_mapTo_string`` for ``Vector<int>.mapTo<string>`` and
``btrc_Box_int_convert_string`` for ``Box<int>.convert<string>``. The class part
is the existing ``mangle_generic_type`` output (or the bare class name for a
non-generic owner); the method part appends each method type argument's mangle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...nodes import (
    CType,
    IRBlock,
    IRCast,
    IRExprStmt,
    IRFunctionDef,
    IRParam,
    IRVar,
)
from ..types import mangle_generic_type, mangle_type_name
from .user_emitter import _UserGenericEmitter

if TYPE_CHECKING:
    from ..generator import IRGenerator


def generic_method_instance_name(class_base, class_args, method_name,
                                 method_args) -> str:
    """C function name for a monomorphized generic-method instance."""
    if class_args:
        class_part = mangle_generic_type(class_base, list(class_args))
    else:
        class_part = class_base
    method_part = "_".join(mangle_type_name(a) for a in method_args)
    return f"{class_part}_{method_name}_{method_part}"


def emit_generic_method_instances(gen: IRGenerator):
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
            _emit_one_method_instance(gen, class_base, cls_info, method,
                                      class_args, method_args)


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


def _emit_one_method_instance(gen, class_base, cls_info, method,
                              class_args, method_args):
    from ..types import type_to_c as ttc

    if class_args:
        self_mangled = mangle_generic_type(class_base, list(class_args))
    else:
        self_mangled = class_base
    fn_name = generic_method_instance_name(class_base, class_args,
                                           method.name, method_args)

    type_map = _build_type_map(cls_info, method, class_args, method_args)
    emitter = _UserGenericEmitter(type_map, self_mangled, ttc, gen=gen,
                                  cls_info=cls_info)
    emitter.reset_var_types(method.params)

    ret_c = emitter.resolve_c(method.return_type) if method.return_type else "void"
    params_ir = [IRParam(c_type=CType(text=f"{self_mangled}*"), name="self")]
    for p in method.params:
        params_ir.append(
            IRParam(c_type=CType(text=emitter.resolve_c(p.type)), name=p.name))

    body_stmts = (emitter.emit_stmts(method.body.statements)
                  if method.body else [])
    if not body_stmts:
        body_stmts = [IRExprStmt(
            expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="self")))]

    # Forward declaration (raw_section: body may reference fn-ptr typedefs not
    # yet emitted at forward_decls time).
    fwd_params = [f"{self_mangled}* self"]
    for p in method.params:
        fwd_params.append(f"{emitter.resolve_c(p.type)} {p.name}")
    gen.module.raw_sections.append(
        f"static {ret_c} {fn_name}({', '.join(fwd_params)});")

    gen.module.function_defs.append(IRFunctionDef(
        name=fn_name,
        return_type=CType(text=ret_c),
        params=params_ir,
        body=IRBlock(stmts=body_stmts),
        is_static=True,
    ))
