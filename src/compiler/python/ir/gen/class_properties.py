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
from .parameters import (
    lower_named_source_type_param,
    source_binding_c_name,
)
from .types import CTypeRenderer

if TYPE_CHECKING:
    from ...analyzer.core import ClassInfo
    from .lowerer import IRLowerer


def emit_property(
    gen: IRLowerer,
    declaration: ClassDecl,
    prop: PropertyDecl,
    type_renderer: CTypeRenderer,
    default_arguments,
) -> None:
    """Emit getter/setter functions for one declared property."""
    name = declaration.name
    prop_type = type_renderer.render(prop.type) if prop.type else "int"
    backing = f"_prop_{prop.name}"

    if prop.has_getter:
        body = _getter_body(
            gen,
            prop,
            backing,
            prop_type,
            type_renderer,
            default_arguments,
        )
        gen.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_get_{prop.name}",
                return_type=CType(text=prop_type),
                params=[IRParam(c_type=CType(text=f"{name}*"), name="self")],
                body=body,
            )
        )
    if prop.has_setter:
        value_name = source_binding_c_name("value", gen.analyzed)
        body = _setter_body(
            gen,
            prop,
            backing,
            value_name,
            type_renderer,
            default_arguments,
        )
        gen.module.function_defs.append(
            IRFunctionDef(
                name=f"{name}_set_{prop.name}",
                return_type=CType(text="void"),
                params=[
                    IRParam(c_type=CType(text=f"{name}*"), name="self"),
                    lower_named_source_type_param(
                        prop.type,
                        prop_type,
                        "value",
                        gen.analyzed,
                    ),
                ],
                body=body,
            )
        )


def emit_inherited_properties(
    gen: IRLowerer,
    declaration: ClassDecl,
    class_info: ClassInfo,
    own_properties: set[str],
    type_renderer: CTypeRenderer,
    default_arguments,
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
        prop_type = CType(text=type_renderer.render(prop.type))
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
            value_name = source_binding_c_name("value", gen.analyzed)
            gen.module.function_defs.append(
                IRFunctionDef(
                    name=f"{declaration.name}_set_{name}",
                    return_type=CType(text="void"),
                    params=[
                        IRParam(
                            c_type=CType(text=f"{declaration.name}*"),
                            name="self",
                        ),
                        lower_named_source_type_param(
                            prop.type,
                            prop_type,
                            "value",
                            gen.analyzed,
                        ),
                    ],
                    body=IRBlock(
                        stmts=[
                            IRExprStmt(
                                expr=IRCall(
                                    callee=f"{parent_name}_set_{name}",
                                    args=[cast_self, IRVar(name=value_name)],
                                )
                            )
                        ]
                    ),
                )
            )


def _getter_body(
    gen,
    prop,
    backing,
    prop_type,
    type_renderer: CTypeRenderer,
    default_arguments,
):
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
    gen.context.function_declarations = []
    gen.current_return_c_type = prop_type
    gen.current_return_type = prop.type
    # A custom managed getter is a call-shaped projection and returns +1.
    # Borrowed branches are promoted by ordinary return lowering; freshly
    # owned branches transfer their existing reference.
    gen.current_return_owned = True
    previous_backing = gen.context.current_property_backing
    gen.context.current_property_backing = prop.name if property_needs_backing(prop) else None
    try:
        body = lower_block(
            gen,
            prop.getter_body,
            local_bindings=["self"],
            type_renderer=type_renderer,
            default_arguments=default_arguments,
        )
    finally:
        gen.context.current_property_backing = previous_backing
        gen.current_return_type = previous_return_type
        gen.current_return_c_type = previous_return_c_type
        gen.current_return_owned = previous_return_owned
    return body


def _setter_body(
    gen,
    prop,
    backing,
    value_name,
    type_renderer: CTypeRenderer,
    default_arguments,
):
    if prop.setter_body is None:
        if gen.managed_values.is_managed(prop.type):
            target = IRFieldAccess(
                obj=IRVar(name="self"),
                field=backing,
                arrow=True,
            )
            if gen.managed_values.is_arc(prop.type):
                stmts = [
                    IRExprStmt(
                        expr=gen.lifetime.replace_edge_value(
                            target,
                            IRVar(name=value_name),
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
                        c_type=CType(text=type_renderer.render(prop.type)),
                        name=old_name,
                        init=target,
                    ),
                    IRExprStmt(
                        expr=gen.lifetime.unlink_edge_value(
                            IRVar(name=old_name),
                            prop.type,
                            IRVar(name="self"),
                        )
                    ),
                    IRExprStmt(
                        expr=gen.lifetime.retain_edge_value(
                            IRVar(name=value_name),
                            prop.type,
                            IRVar(name="self"),
                        )
                    ),
                    IRAssign(target=target, value=IRVar(name=value_name)),
                    IRExprStmt(
                        expr=gen.lifetime.release_edge_value(
                            IRVar(name=old_name),
                            prop.type,
                            replacement=IRVar(name=value_name),
                        )
                    ),
                ]
            flush = gen.lifetime.poll_released_values(prop.type)
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
                    value=IRVar(name=value_name),
                )
            ]
        )
    from .statements import lower_block

    previous_return_type = gen.current_return_type
    previous_return_c_type = gen.current_return_c_type
    gen.context.function_declarations = []
    gen.current_return_c_type = "void"
    gen.current_return_type = None
    previous_backing = gen.context.current_property_backing
    gen.context.current_property_backing = prop.name if property_needs_backing(prop) else None
    try:
        body = lower_block(
            gen,
            prop.setter_body,
            local_bindings=["self", "value"],
            callable_bindings=[("value", prop.type)],
            type_renderer=type_renderer,
            default_arguments=default_arguments,
        )
    finally:
        gen.context.current_property_backing = previous_backing
        gen.current_return_type = previous_return_type
        gen.current_return_c_type = previous_return_c_type
    return body


__all__ = ["emit_inherited_properties", "emit_property"]
