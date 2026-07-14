"""Own and inherited class-property lowering."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import ClassDecl, PropertyDecl
from ...class_storage import property_needs_backing
from ..nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDef,
    IRParam,
    IRReturn,
    IRVar,
    IRVarDecl,
)
from .managed_values import (
    is_class_type,
    is_managed_type,
    poll_released_values,
    release_edge_value,
    replace_edge_value,
    retain_edge_value,
    unlink_edge_value,
)
from .types import type_to_c

if TYPE_CHECKING:
    from ...analyzer.core import ClassInfo
    from .generator import IRGenerator


def emit_property(
    gen: IRGenerator,
    declaration: ClassDecl,
    prop: PropertyDecl,
) -> None:
    """Emit getter/setter functions for one declared property."""
    name = declaration.name
    prop_type = type_to_c(prop.type) if prop.type else "int"
    backing = f"_prop_{prop.name}"

    if prop.has_getter:
        body = _getter_body(gen, prop, backing, prop_type)
        gen.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_get_{prop.name}",
                return_type=CType(text=prop_type),
                params=[IRParam(c_type=CType(text=f"{name}*"), name="self")],
                body=body,
            )
        )
    if prop.has_setter:
        body = _setter_body(gen, prop, backing)
        gen.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_set_{prop.name}",
                return_type=CType(text="void"),
                params=[
                    IRParam(c_type=CType(text=f"{name}*"), name="self"),
                    IRParam(c_type=CType(text=prop_type), name="value"),
                ],
                body=body,
            )
        )


def emit_inherited_properties(
    gen: IRGenerator,
    declaration: ClassDecl,
    class_info: ClassInfo,
    own_properties: set[str],
) -> None:
    """Expose direct-parent property accessors with child-typed wrappers."""
    parent_name = class_info.parent
    parent = gen.analyzed.class_table.get(parent_name) if parent_name else None
    if parent is None:
        return
    cast_self = IRCast(
        target_type=CType(text=f"{parent_name}*"),
        expr=IRVar(name="self"),
    )
    for name, prop in parent.properties.items():
        if name in own_properties:
            continue
        prop_type = CType(text=type_to_c(prop.type))
        if prop.has_getter:
            gen.module.function_defs.append(
                IRFunctionDef(
                    name=f"{declaration.name}_get_{name}",
                    return_type=prop_type,
                    params=[
                        IRParam(
                            c_type=CType(text=f"{declaration.name}*"),
                            name="self",
                        )
                    ],
                    body=IRBlock(
                        stmts=[
                            IRReturn(
                                value=IRCall(
                                    callee=f"{parent_name}_get_{name}",
                                    args=[cast_self],
                                )
                            )
                        ]
                    ),
                )
            )
        if prop.has_setter:
            gen.module.function_defs.append(
                IRFunctionDef(
                    name=f"{declaration.name}_set_{name}",
                    return_type=CType(text="void"),
                    params=[
                        IRParam(
                            c_type=CType(text=f"{declaration.name}*"),
                            name="self",
                        ),
                        IRParam(c_type=prop_type, name="value"),
                    ],
                    body=IRBlock(
                        stmts=[
                            IRExprStmt(
                                expr=IRCall(
                                    callee=f"{parent_name}_set_{name}",
                                    args=[cast_self, IRVar(name="value")],
                                )
                            )
                        ]
                    ),
                )
            )


def _getter_body(gen, prop, backing, prop_type):
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
    from .statements import lower_block

    previous_return_type = gen.current_return_type
    previous_return_c_type = gen.current_return_c_type
    previous_return_owned = gen.current_return_owned
    gen._func_var_decls = []
    gen.current_return_c_type = prop_type
    gen.current_return_type = prop.type
    gen.current_return_owned = False
    previous_backing = gen.current_property_backing
    gen.current_property_backing = prop.name if property_needs_backing(prop) else None
    try:
        body = lower_block(gen, prop.getter_body, local_bindings=["self"])
    finally:
        gen.current_property_backing = previous_backing
        gen.current_return_type = previous_return_type
        gen.current_return_c_type = previous_return_c_type
        gen.current_return_owned = previous_return_owned
    return body


def _setter_body(gen, prop, backing):
    if prop.setter_body is None:
        if is_managed_type(gen, prop.type):
            target = IRFieldAccess(
                obj=IRVar(name="self"),
                field=backing,
                arrow=True,
            )
            if is_class_type(gen, prop.type):
                stmts = [
                    IRExprStmt(
                        expr=replace_edge_value(
                            gen,
                            target,
                            IRVar(name="value"),
                            prop.type,
                            IRVar(name="self"),
                            adopt=False,
                        )
                    )
                ]
            else:
                old_name = gen.fresh_temp("__btrc_property_old")
                stmts = [
                    IRVarDecl(
                        c_type=CType(text=type_to_c(prop.type)),
                        name=old_name,
                        init=target,
                    ),
                    IRExprStmt(
                        expr=unlink_edge_value(
                            gen,
                            IRVar(name=old_name),
                            prop.type,
                            IRVar(name="self"),
                        )
                    ),
                    IRExprStmt(
                        expr=retain_edge_value(
                            gen,
                            IRVar(name="value"),
                            prop.type,
                            IRVar(name="self"),
                        )
                    ),
                    IRAssign(target=target, value=IRVar(name="value")),
                    IRExprStmt(
                        expr=release_edge_value(
                            gen,
                            IRVar(name=old_name),
                            prop.type,
                            replacement=IRVar(name="value"),
                        )
                    ),
                ]
            flush = poll_released_values(gen, prop.type)
            if flush is not None:
                stmts.append(IRExprStmt(expr=flush))
            return IRBlock(stmts=stmts)
        return IRBlock(
            stmts=[
                IRAssign(
                    target=IRFieldAccess(
                        obj=IRVar(name="self"),
                        field=backing,
                        arrow=True,
                    ),
                    value=IRVar(name="value"),
                )
            ]
        )
    from .statements import lower_block

    previous_return_type = gen.current_return_type
    previous_return_c_type = gen.current_return_c_type
    gen._func_var_decls = []
    gen.current_return_c_type = "void"
    gen.current_return_type = None
    previous_backing = gen.current_property_backing
    gen.current_property_backing = prop.name if property_needs_backing(prop) else None
    try:
        body = lower_block(gen, prop.setter_body, local_bindings=["self", "value"])
    finally:
        gen.current_property_backing = previous_backing
        gen.current_return_type = previous_return_type
        gen.current_return_c_type = previous_return_c_type
    return body


__all__ = ["emit_inherited_properties", "emit_property"]
