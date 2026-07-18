"""Constructor and field-initializer lowering for classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import (
    BraceInitializer,
    FieldDecl,
    ListLiteral,
    MapLiteral,
)
from ..nodes import (
    CType,
    IRAssign,
    IRBlock,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFieldAccess,
    IRFunctionDef,
    IRLiteral,
    IRParam,
    IRReturn,
    IRSizeof,
    IRVar,
    IRVarDecl,
)
from .arc_metadata import arc_header_initialization
from .managed_values import (
    adopt_edge_value,
    is_arc_type,
    is_managed_type,
    replace_edge_value,
    retain_edge_value,
)
from .parameters import lower_source_param
from .types import is_generic_class_type, mangle_generic_type

if TYPE_CHECKING:
    from ...analyzer.core import ClassInfo
    from ...ast_nodes import ClassDecl
    from .generator import IRGenerator


def emit_constructor(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo) -> None:
    """Emit ``Class_init`` and allocating ``Class_new`` functions."""
    name = decl.name
    constructor = cls_info.constructor
    constructor_params = [lower_source_param(param) for param in (constructor.params if constructor else [])]
    init_params = [
        IRParam(c_type=CType(text=f"{name}*"), name="self"),
        *constructor_params,
    ]
    init_stmts = arc_header_initialization(name)

    for member in decl.members:
        if isinstance(member, FieldDecl) and member.access != "class" and member.initializer:
            from .callable_boundaries import reject_persistent_callable_escape

            reject_persistent_callable_escape(
                gen,
                member.type,
                member.initializer,
                "field storage",
            )
            target = IRFieldAccess(
                obj=IRVar(name="self"),
                field=member.name,
                arrow=True,
            )
            value = _lower_field_init(gen, member)
            from .prepared_values import prepare_normal_value

            prepared = prepare_normal_value(
                gen,
                member.initializer,
                member.type,
                lowered=value,
            )
            value = prepared.value
            from .upcast import upcast_class_pointer

            value = upcast_class_pointer(
                gen,
                member.type,
                prepared.effective_type,
                value,
            )
            if is_arc_type(gen, member.type):
                init_stmts.append(
                    IRExprStmt(
                        expr=replace_edge_value(
                            gen,
                            target,
                            value,
                            member.type,
                            IRVar(name="self"),
                            adopt=prepared.owned,
                        )
                    )
                )
            else:
                init_stmts.append(IRAssign(target=target, value=value))
            if _is_managed_field(gen, member) and not is_arc_type(gen, member.type):
                edge_op = adopt_edge_value if prepared.owned else retain_edge_value
                init_stmts.append(
                    IRExprStmt(
                        expr=edge_op(
                            gen,
                            target,
                            member.type,
                            IRVar(name="self"),
                        )
                    )
                )

    if constructor and constructor.body:
        from .statements import lower_block

        gen._func_var_decls = []
        gen.current_return_c_type = "void"
        init_stmts.extend(
            lower_block(
                gen,
                constructor.body,
                local_bindings=["self", *(parameter.name for parameter in constructor.params)],
                callable_bindings=constructor.params,
            ).stmts
        )

    gen.module.function_defs.append(
        IRFunctionDef(
            name=f"{name}_init",
            return_type=CType(text="void"),
            params=init_params,
            body=IRBlock(stmts=init_stmts),
        )
    )

    from .constructor_cleanup import constructor_cleanup_guard

    self_declaration = IRVarDecl(
        c_type=CType(text=f"{name}*"),
        name="self",
        init=IRCast(
            target_type=CType(text=f"{name}*"),
            expr=IRCall(
                callee="__btrc_safe_calloc",
                args=[
                    IRLiteral(text="1"),
                    IRSizeof(operand=CType(text=name)),
                ],
                helper_ref="__btrc_safe_calloc",
            ),
        ),
    )
    gen.use_helper("__btrc_safe_calloc")
    cleanup_before, cleanup_after = constructor_cleanup_guard(gen, self_declaration)
    new_stmts = [
        self_declaration,
        *cleanup_before,
        IRExprStmt(
            expr=IRCall(
                callee=f"{name}_init",
                args=[
                    IRVar(name="self"),
                    *(IRVar(name=param.name) for param in constructor_params),
                ],
            )
        ),
        *cleanup_after,
        IRReturn(value=IRVar(name="self")),
    ]
    gen.module.function_defs.append(
        IRFunctionDef(
            name=f"{name}_new",
            return_type=CType(text=f"{name}*"),
            params=list(constructor_params),
            body=IRBlock(stmts=new_stmts),
        )
    )


def _lower_field_init(gen: IRGenerator, field: FieldDecl):
    from .expressions import lower_expr

    initializer = field.initializer
    is_empty = (
        (isinstance(initializer, BraceInitializer) and not initializer.elements)
        or (isinstance(initializer, ListLiteral) and not initializer.elements)
        or (isinstance(initializer, MapLiteral) and not initializer.entries)
    )
    if is_empty and field.type and is_generic_class_type(field.type, gen.analyzed.class_table):
        mangled = mangle_generic_type(field.type.base, field.type.generic_args)
        return IRCall(callee=f"{mangled}_new", args=[])
    return lower_expr(gen, initializer)


def _is_managed_field(gen: IRGenerator, field: FieldDecl) -> bool:
    return is_managed_type(gen, field.type)
