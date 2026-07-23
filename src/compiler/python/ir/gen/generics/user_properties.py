"""Property accessors for monomorphized user-defined classes."""

from __future__ import annotations

from ....class_storage import property_needs_backing
from ...nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRCast,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDecl,
    IRFunctionDef,
    IRParam,
    IRReturn,
    IRVar,
    IRVarDecl,
)
from ..managed_values import (
    is_arc_type,
    is_managed_type,
    poll_released_values,
    release_edge_value,
    replace_edge_value,
    retain_edge_value,
    unlink_edge_value,
)
from ..parameters import (
    lower_named_source_type_param,
    source_binding_c_name,
)
from .core import _resolve_type
from .user_emitter_bindings import bind_source_parameter


def emit_generic_properties(gen, mangled, type_map, cls_info, emitter):
    """Emit typed getter/setter declarations and definitions."""

    emitted = []
    for name, prop in cls_info.properties.items():
        resolved = _resolve_type(prop.type, type_map, gen.analyzed.typedef_table)
        property_c = emitter.resolve_c(prop.type)
        backing = f"_prop_{name}"
        if prop.has_getter:
            params = [IRParam(c_type=CType(text=f"{mangled}*"), name="self")]
            gen.module.function_decls.append(
                IRFunctionDecl(
                    name=f"{mangled}_get_{name}",
                    return_type=CType(text=property_c),
                    params=list(params),
                    is_static=True,
                )
            )
            emitted.append(
                IRFunctionDef(
                    name=f"{mangled}_get_{name}",
                    return_type=CType(text=property_c),
                    params=params,
                    body=_getter_body(emitter, name, prop, backing),
                    is_static=True,
                )
            )
        if prop.has_setter:
            value_name = source_binding_c_name("value", gen.analyzed)
            params = [
                IRParam(c_type=CType(text=f"{mangled}*"), name="self"),
                lower_named_source_type_param(
                    prop.type,
                    property_c,
                    "value",
                    gen.analyzed,
                    resolved_type=emitter._resolve(prop.type),
                ),
            ]
            gen.module.function_decls.append(
                IRFunctionDecl(
                    name=f"{mangled}_set_{name}",
                    return_type=CType(text="void"),
                    params=list(params),
                    is_static=True,
                )
            )
            emitted.append(
                IRFunctionDef(
                    name=f"{mangled}_set_{name}",
                    return_type=CType(text="void"),
                    params=params,
                    body=_setter_body(
                        gen,
                        emitter,
                        prop,
                        resolved,
                        property_c,
                        backing,
                        value_name,
                    ),
                    is_static=True,
                )
            )
    gen.module.function_defs.extend(emitted)
    return emitted


def _getter_body(emitter, name, prop, backing):
    if prop.getter_body is None:
        return IRBlock(
            stmts=[
                IRReturn(
                    value=IRFieldAccess(
                        obj=IRVar(name="self"),
                        field=backing,
                        arrow=True,
                    )
                )
            ]
        )
    emitter.reset_var_types(return_type=prop.type, return_owned=False)
    return _custom_accessor_body(
        emitter,
        name,
        prop,
        [_void_use("self")],
        prop.getter_body.statements,
    )


def _setter_body(gen, emitter, prop, resolved, property_c, backing, value_name):
    target = IRFieldAccess(
        obj=IRVar(name="self"),
        field=backing,
        arrow=True,
    )
    if prop.setter_body is None:
        if not is_managed_type(gen, resolved):
            return IRBlock(stmts=[IRAssign(target=target, value=IRVar(name=value_name))])
        if is_arc_type(gen, resolved):
            stmts = [
                IRExprStmt(
                    expr=replace_edge_value(
                        gen,
                        target,
                        IRVar(name=value_name),
                        resolved,
                        IRVar(name="self"),
                        adopt=False,
                    )
                )
            ]
        else:
            old_name = emitter._fresh_temp("__btrc_property_old")
            stmts = [
                IRVarDecl(
                    c_type=CType(text=property_c),
                    name=old_name,
                    init=target,
                ),
                IRExprStmt(
                    expr=unlink_edge_value(
                        gen,
                        IRVar(name=old_name),
                        resolved,
                        IRVar(name="self"),
                    )
                ),
                IRExprStmt(
                    expr=retain_edge_value(
                        gen,
                        IRVar(name=value_name),
                        resolved,
                        IRVar(name="self"),
                    )
                ),
                IRAssign(target=target, value=IRVar(name=value_name)),
                IRExprStmt(
                    expr=release_edge_value(
                        gen,
                        IRVar(name=old_name),
                        resolved,
                        replacement=IRVar(name=value_name),
                    )
                ),
            ]
        flush = poll_released_values(gen, resolved)
        if flush is not None:
            stmts.append(IRExprStmt(expr=flush))
        return IRBlock(stmts=stmts)
    emitter.reset_var_types()
    bind_source_parameter(emitter, "value", value_name)
    emitter._var_types["value"] = resolved
    return _custom_accessor_body(
        emitter,
        prop.name,
        prop,
        [_void_use("self"), _void_use(value_name)],
        prop.setter_body.statements,
    )


def _custom_accessor_body(emitter, name, prop, prefix, statements):
    previous = emitter._current_property_backing
    emitter._current_property_backing = name if property_needs_backing(prop) else None
    if hasattr(emitter, "context"):
        emitter.context.current_property_backing = emitter._current_property_backing
    try:
        return IRBlock(stmts=prefix + emitter.emit_stmts(statements))
    finally:
        emitter._current_property_backing = previous
        if hasattr(emitter, "context"):
            emitter.context.current_property_backing = previous


def _void_use(name):
    return IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name=name)))


__all__ = ["emit_generic_properties"]
