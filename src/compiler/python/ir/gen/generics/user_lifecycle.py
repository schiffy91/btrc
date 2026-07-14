"""Lifecycle emission for monomorphized user-defined classes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ....ast_nodes import TypeExpr
from ...nodes import (
    CType,
    IRBlock,
    IRCall,
    IRCast,
    IRExprStmt,
    IRFunctionDecl,
    IRFunctionDef,
    IRLiteral,
    IRParam,
    IRReturn,
    IRSizeof,
    IRVar,
    IRVarDecl,
)
from ..arc_metadata import arc_header_initialization, emit_arc_descriptor
from ..collection_visitors import emit_generic_visitor
from ..constructor_cleanup import constructor_cleanup_guard
from ..cycle_metadata import (
    cycle_visitor_symbol,
    generic_instance_may_cycle,
    generic_instance_needs_visitor,
    register_cycle_classification,
    register_cycle_visitor,
)
from ..destructor_hooks import call_destructor_hook
from ..parameters import lower_source_param
from .core import _resolve_type
from .user_destructors import (
    build_generic_destructor_hook,
    build_generic_field_release_stmts,
)

if TYPE_CHECKING:
    from ..generator import IRGenerator
    from .user_emitter import _UserGenericEmitter


def emit_generic_lifecycle(
    gen: IRGenerator,
    base_name: str,
    mangled: str,
    args: list[TypeExpr],
    type_map: dict[str, TypeExpr],
    cls_info,
    emitter: _UserGenericEmitter,
) -> tuple[list[IRFunctionDecl], list[IRFunctionDef]]:
    """Emit init/new/destroy and the optional cycle visitor."""
    has_visitor = generic_instance_needs_visitor(gen, base_name, args)
    register_cycle_classification(gen, mangled, generic_instance_may_cycle(gen, base_name, args))
    if has_visitor:
        register_cycle_visitor(gen, mangled)

    ctor = cls_info.constructor
    ctor_params = [lower_source_param(param, emitter.resolve_c) for param in ctor.params] if ctor else []
    declarations = _lifecycle_declarations(mangled, ctor_params)
    destructor_hook = build_generic_destructor_hook(
        cls_info,
        type_map,
        mangled,
        gen,
    )
    definitions = [
        _emit_init(gen, mangled, ctor, ctor_params, emitter),
        _emit_new(gen, mangled, ctor, ctor_params, has_visitor),
    ]
    if destructor_hook is not None:
        definitions.append(destructor_hook)
    definitions.append(
        _emit_destroy(
            gen,
            mangled,
            cls_info,
            type_map,
            has_destructor_hook=destructor_hook is not None,
        )
    )
    gen.module.function_defs.extend(definitions)

    if has_visitor:
        emit_generic_visitor(
            gen,
            base_name,
            mangled,
            args,
            cls_info.instance_storage,
            lambda field_type: _resolve_type(field_type, type_map),
        )
    emit_arc_descriptor(
        gen,
        mangled,
        cycle_visitor_symbol(mangled) if has_visitor else None,
    )
    return declarations, definitions


def _lifecycle_declarations(mangled: str, ctor_params: list[IRParam]) -> list[IRFunctionDecl]:
    return [
        IRFunctionDecl(
            name=f"{mangled}_init",
            return_type=CType(text="void"),
            params=[IRParam(c_type=CType(text=f"{mangled}*"), name="self")] + list(ctor_params),
            is_static=True,
        ),
        IRFunctionDecl(
            name=f"{mangled}_new",
            return_type=CType(text=f"{mangled}*"),
            params=list(ctor_params),
            is_static=True,
        ),
        IRFunctionDecl(
            name=f"{mangled}_destroy",
            return_type=CType(text="void"),
            params=[IRParam(c_type=CType(text="void*"), name="object")],
            is_static=True,
        ),
    ]


def _emit_init(gen, mangled, ctor, ctor_params, emitter) -> IRFunctionDef:
    body_stmts = []
    if ctor and ctor.body:
        emitter.reset_var_types(ctor.params)
        body_stmts = emitter.emit_stmts(ctor.body.statements)
    if not body_stmts:
        body_stmts = [IRExprStmt(expr=IRCast(target_type=CType(text="void"), expr=IRVar(name="self")))]

    return IRFunctionDef(
        name=f"{mangled}_init",
        return_type=CType(text="void"),
        params=[IRParam(c_type=CType(text=f"{mangled}*"), name="self")] + ctor_params,
        body=IRBlock(
            stmts=[
                *arc_header_initialization(mangled),
                *body_stmts,
            ]
        ),
        is_static=True,
    )


def _emit_new(gen, mangled, ctor, ctor_params, has_visitor) -> IRFunctionDef:
    ctor_args = [IRVar(name=param.name) for param in ctor.params] if ctor else []
    self_declaration = IRVarDecl(
        c_type=CType(text=f"{mangled}*"),
        name="self",
        init=IRCast(
            target_type=CType(text=f"{mangled}*"),
            expr=IRCall(
                callee="malloc",
                args=[IRSizeof(operand=CType(text=mangled))],
            ),
        ),
    )
    cleanup_before, cleanup_after = constructor_cleanup_guard(
        gen,
        self_declaration,
        f"{mangled}_destroy",
        cycle_visitor_symbol(mangled) if has_visitor else None,
    )
    return IRFunctionDef(
        name=f"{mangled}_new",
        return_type=CType(text=f"{mangled}*"),
        params=list(ctor_params),
        body=IRBlock(
            stmts=[
                self_declaration,
                IRExprStmt(
                    expr=IRCall(
                        callee="memset",
                        args=[
                            IRVar(name="self"),
                            IRLiteral(text="0"),
                            IRSizeof(operand=CType(text=mangled)),
                        ],
                    )
                ),
                *cleanup_before,
                IRExprStmt(
                    expr=IRCall(
                        callee=f"{mangled}_init",
                        args=[IRVar(name="self"), *ctor_args],
                    )
                ),
                *cleanup_after,
                IRReturn(value=IRVar(name="self")),
            ]
        ),
        is_static=True,
    )


def _emit_destroy(
    gen,
    mangled,
    cls_info,
    type_map,
    *,
    has_destructor_hook: bool,
) -> IRFunctionDef:
    body_stmts = [call_destructor_hook(mangled)] if has_destructor_hook else []
    if "free" in cls_info.methods:
        body_stmts.append(IRExprStmt(expr=IRCall(callee=f"{mangled}_free", args=[IRVar(name="self")])))
    else:
        body_stmts.extend(build_generic_field_release_stmts(cls_info, type_map, gen))
    body_stmts.insert(
        0,
        IRVarDecl(
            c_type=CType(text=f"{mangled}*"),
            name="self",
            init=IRCast(target_type=CType(text=f"{mangled}*"), expr=IRVar(name="object")),
        ),
    )
    body_stmts.append(IRExprStmt(expr=IRCall(callee="free", args=[IRVar(name="self")])))
    return IRFunctionDef(
        name=f"{mangled}_destroy",
        return_type=CType(text="void"),
        params=[IRParam(c_type=CType(text="void*"), name="object")],
        body=IRBlock(stmts=body_stmts),
        is_static=True,
    )


__all__ = ["emit_generic_lifecycle"]
