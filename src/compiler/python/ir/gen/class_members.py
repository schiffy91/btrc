"""Class member lowering: destructor, methods, and inheritance."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...analyzer.core import ClassInfo
from ...ast_nodes import ClassDecl, MethodDecl
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
    IRVar,
    IRVarDecl,
)
from .managed_values import (
    is_class_type,
    is_managed_type,
    release_edge_value,
    replace_edge_value,
    unlink_edge_value,
)
from .parameters import lower_source_param
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_destructor(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo):
    """Emit ClassName_destroy(self) which frees internal resources."""
    name = decl.name
    dtor = cls_info.methods.get("__del__")

    body_stmts = []
    if dtor and dtor.body:
        from .statements import lower_block

        gen._func_var_decls = []
        previous_return_type = gen.current_return_type
        previous_return_c_type = gen.current_return_c_type
        previous_return_owned = gen.current_return_owned
        gen.current_return_c_type = "void"
        gen.current_return_type = None
        body_stmts = lower_block(gen, dtor.body, local_bindings=["self"]).stmts
        gen.current_return_type = previous_return_type
        gen.current_return_c_type = previous_return_c_type
        gen.current_return_owned = previous_return_owned

    body_stmts.insert(
        0,
        IRVarDecl(
            c_type=CType(text=f"{name}*"),
            name="self",
            init=IRCast(target_type=CType(text=f"{name}*"), expr=IRVar(name="object")),
        ),
    )

    # ARC: release owned pointer-type fields (rc-- then destroy at zero)
    # Class types have pointer_depth=1 in analyzer (always heap-allocated).
    # Skip pointer_depth > 1 (double-pointers / raw arrays).
    has_class_field_releases = False
    for fname, fd in cls_info.instance_storage:
        if fd.type and fd.type.pointer_depth > 1:
            continue
        # Generic class fields use their terminal destructor. Collection
        # ``free()`` methods only clear contents; ``destroy()`` also frees the
        # instance struct.
        if is_managed_type(gen, fd.type):
            body_stmts.append(_emit_field_release(gen, fname, fd.type))
            has_class_field_releases = has_class_field_releases or is_class_type(gen, fd.type)

    # Mark cascade destruction before freeing. The helper itself checks the
    # process-wide unwind scope under the ARC mutation lock.
    if has_class_field_releases:
        gen.use_helper("__btrc_mark_destroyed")
        body_stmts.append(
            IRExprStmt(
                expr=IRCall(
                    callee="__btrc_mark_destroyed",
                    helper_ref="__btrc_mark_destroyed",
                    args=[IRVar(name="self")],
                )
            )
        )
    # Free self at the end
    body_stmts.append(IRExprStmt(expr=IRCall(callee="free", args=[IRVar(name="self")])))

    gen.module.function_defs.append(
        IRFunctionDef(
            name=f"{name}_destroy",
            return_type=CType(text="void"),
            params=[IRParam(c_type=CType(text="void*"), name="object")],
            body=IRBlock(stmts=body_stmts),
        )
    )


def emit_method(gen: IRGenerator, decl: ClassDecl, method: MethodDecl):
    """Emit ClassName_methodname(self, ...) as a free function."""
    name = decl.name
    is_static = method.access == "class"
    params = []
    if not is_static:
        params.append(IRParam(c_type=CType(text=f"{name}*"), name="self"))
    for p in method.params:
        params.append(lower_source_param(p))

    ret_type = type_to_c(method.return_type) if method.return_type else "void"

    body = IRBlock()
    if method.body:
        from .statements import lower_block

        gen._func_var_decls = []
        previous_return_type = gen.current_return_type
        previous_return_c_type = gen.current_return_c_type
        previous_return_owned = gen.current_return_owned
        gen.current_return_c_type = ret_type
        gen.current_return_type = method.return_type
        gen.current_return_owned = True
        body = lower_block(
            gen,
            method.body,
            local_bindings=["self", *(parameter.name for parameter in method.params)],
            callable_bindings=method.params,
        )
        gen.current_return_type = previous_return_type
        gen.current_return_c_type = previous_return_c_type
        gen.current_return_owned = previous_return_owned

    gen.module.function_defs.append(
        IRFunctionDef(
            name=f"{name}_{method.name}",
            return_type=CType(text=ret_type),
            params=params,
            body=body,
        )
    )


def emit_inherited_methods(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo, own_methods: set[str]):
    """Emit wrapper functions for inherited methods not overridden."""
    parent_name = cls_info.parent
    while parent_name and parent_name in gen.analyzed.class_table:
        parent_info = gen.analyzed.class_table[parent_name]
        for mname, method in parent_info.methods.items():
            if mname in own_methods or mname == "__del__" or method.is_constructor:
                continue
            if method.is_abstract or method.body is None:
                continue
            own_methods.add(mname)
            params = []
            call_args = []
            if method.access != "class":
                params.append(IRParam(c_type=CType(text=f"{decl.name}*"), name="self"))
                call_args.append(
                    IRCast(
                        target_type=CType(text=f"{parent_name}*"),
                        expr=IRVar(name="self"),
                    )
                )
            for p in method.params:
                params.append(lower_source_param(p))
                call_args.append(IRVar(name=p.name))
            ret_type = type_to_c(method.return_type) if method.return_type else "void"
            call = IRCall(callee=f"{parent_name}_{mname}", args=call_args)
            if ret_type == "void":
                body = IRBlock(stmts=[IRExprStmt(expr=call)])
            else:
                body = IRBlock(stmts=[IRReturn(value=call)])
            gen.module.function_defs.append(
                IRFunctionDef(
                    name=f"{decl.name}_{mname}",
                    return_type=CType(text=ret_type),
                    params=params,
                    body=body,
                )
            )
        parent_name = parent_info.parent


def _emit_field_release(gen, field_name: str, field_type) -> IRBlock:
    """Release one internal field without a reentrant collector flush."""
    fa = IRFieldAccess(obj=IRVar(name="self"), field=field_name, arrow=True)
    if is_class_type(gen, field_type):
        return IRBlock(
            stmts=[
                IRExprStmt(
                    expr=replace_edge_value(
                        gen,
                        fa,
                        IRLiteral(text="NULL"),
                        field_type,
                        IRVar(name="self"),
                        adopt=False,
                    )
                )
            ]
        )
    old_name = gen.fresh_temp("__btrc_destroy_field")
    return IRBlock(
        stmts=[
            IRVarDecl(
                c_type=CType(text=type_to_c(field_type)),
                name=old_name,
                init=fa,
            ),
            IRExprStmt(
                expr=unlink_edge_value(
                    gen,
                    IRVar(name=old_name),
                    field_type,
                    IRVar(name="self"),
                )
            ),
            IRAssign(target=fa, value=IRLiteral(text="NULL")),
            IRExprStmt(expr=release_edge_value(gen, IRVar(name=old_name), field_type)),
        ]
    )
