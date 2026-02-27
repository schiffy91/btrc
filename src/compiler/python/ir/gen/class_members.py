"""Class member lowering: destructor, methods, properties, inheritance."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import ClassDecl, MethodDecl, PropertyDecl, NewExpr
from ...analyzer import ClassInfo
from ..nodes import (
    CType, IRAssign, IRBinOp, IRBlock, IRCall, IRCast, IRExprStmt,
    IRFieldAccess, IRFunctionDef, IRIf, IRLiteral, IRParam, IRReturn, IRVar,
)
from .types import type_to_c, is_generic_class_type, mangle_generic_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_destructor(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo):
    """Emit ClassName_destroy(self) which frees internal resources."""
    name = decl.name
    dtor = cls_info.methods.get("__del__")

    body_stmts = []
    if dtor and dtor.body:
        from .statements import lower_block
        body_stmts = lower_block(gen, dtor.body).stmts

    # Recursively destroy owned pointer-type fields
    for fname, fd in cls_info.fields.items():
        # Generic class fields → mangled_free() or mangled_destroy()
        if fd.type and is_generic_class_type(fd.type, gen.analyzed.class_table):
            mangled = mangle_generic_type(fd.type.base, fd.type.generic_args)
            field_cls = gen.analyzed.class_table.get(fd.type.base)
            dtor_name = "free" if field_cls and "free" in field_cls.methods else "destroy"
            fa = IRFieldAccess(obj=IRVar(name="self"), field=fname, arrow=True)
            body_stmts.append(IRIf(
                condition=IRBinOp(left=fa, op="!=", right=IRLiteral(text="NULL")),
                then_block=IRBlock(stmts=[IRExprStmt(
                    expr=IRCall(callee=f"{mangled}_{dtor_name}",
                                args=[IRFieldAccess(obj=IRVar(name="self"),
                                                     field=fname, arrow=True)]))]),
            ))
        # Class instance fields → ClassName_destroy()
        elif fd.type and fd.type.base in gen.analyzed.class_table:
            fa = IRFieldAccess(obj=IRVar(name="self"), field=fname, arrow=True)
            body_stmts.append(IRIf(
                condition=IRBinOp(left=fa, op="!=", right=IRLiteral(text="NULL")),
                then_block=IRBlock(stmts=[IRExprStmt(
                    expr=IRCall(callee=f"{fd.type.base}_destroy",
                                args=[IRFieldAccess(obj=IRVar(name="self"),
                                                     field=fname, arrow=True)]))]),
            ))

    # Free self at the end
    body_stmts.append(IRExprStmt(expr=IRCall(callee="free", args=[IRVar(name="self")])))

    gen.module.function_defs.append(IRFunctionDef(
        name=f"{name}_destroy",
        return_type=CType(text="void"),
        params=[IRParam(c_type=CType(text=f"{name}*"), name="self")],
        body=IRBlock(stmts=body_stmts),
    ))


def emit_method(gen: IRGenerator, decl: ClassDecl, method: MethodDecl):
    """Emit ClassName_methodname(self, ...) as a free function."""
    name = decl.name
    is_static = method.access == "class"
    params = []
    if not is_static:
        params.append(IRParam(c_type=CType(text=f"{name}*"), name="self"))
    for p in method.params:
        params.append(IRParam(c_type=CType(text=type_to_c(p.type)), name=p.name))

    ret_type = type_to_c(method.return_type) if method.return_type else "void"

    body = IRBlock()
    if method.body:
        from .statements import lower_block
        body = lower_block(gen, method.body)

    gen.module.function_defs.append(IRFunctionDef(
        name=f"{name}_{method.name}",
        return_type=CType(text=ret_type),
        params=params,
        body=body,
    ))


def emit_property(gen: IRGenerator, decl: ClassDecl, prop: PropertyDecl):
    """Emit getter/setter functions for a property."""
    name = decl.name
    prop_type = type_to_c(prop.type) if prop.type else "int"
    backing = f"_prop_{prop.name}"

    if prop.has_getter:
        if prop.getter_body:
            from .statements import lower_block
            body = lower_block(gen, prop.getter_body)
        else:
            body = IRBlock(stmts=[IRReturn(
                value=IRFieldAccess(obj=IRVar(name="self"),
                                    field=backing, arrow=True))])
        gen.module.function_defs.append(IRFunctionDef(
            name=f"{name}_get_{prop.name}",
            return_type=CType(text=prop_type),
            params=[IRParam(c_type=CType(text=f"{name}*"), name="self")],
            body=body,
        ))

    if prop.has_setter:
        if prop.setter_body:
            from .statements import lower_block
            body = lower_block(gen, prop.setter_body)
        else:
            body = IRBlock(stmts=[IRAssign(
                target=IRFieldAccess(obj=IRVar(name="self"),
                                     field=backing, arrow=True),
                value=IRVar(name="value"))])
        gen.module.function_defs.append(IRFunctionDef(
            name=f"{name}_set_{prop.name}",
            return_type=CType(text="void"),
            params=[
                IRParam(c_type=CType(text=f"{name}*"), name="self"),
                IRParam(c_type=CType(text=prop_type), name="value"),
            ],
            body=body,
        ))


def emit_inherited_methods(gen: IRGenerator, decl: ClassDecl,
                           cls_info: ClassInfo, own_methods: set[str]):
    """Emit wrapper functions for inherited methods not overridden."""
    parent_name = cls_info.parent
    while parent_name and parent_name in gen.analyzed.class_table:
        parent_info = gen.analyzed.class_table[parent_name]
        for mname, method in parent_info.methods.items():
            if mname in own_methods or mname == "__del__" or mname == parent_name:
                continue
            own_methods.add(mname)
            params = [IRParam(c_type=CType(text=f"{decl.name}*"), name="self")]
            call_args = [IRCast(
                target_type=f"{parent_name}*", expr=IRVar(name="self"))]
            for p in method.params:
                params.append(IRParam(c_type=CType(text=type_to_c(p.type)), name=p.name))
                call_args.append(IRVar(name=p.name))
            ret_type = type_to_c(method.return_type) if method.return_type else "void"
            call = IRCall(callee=f"{parent_name}_{mname}", args=call_args)
            if ret_type == "void":
                body = IRBlock(stmts=[IRExprStmt(expr=call)])
            else:
                body = IRBlock(stmts=[IRReturn(value=call)])
            gen.module.function_defs.append(IRFunctionDef(
                name=f"{decl.name}_{mname}",
                return_type=CType(text=ret_type),
                params=params,
                body=body,
            ))
        parent_name = parent_info.parent


def lower_new_expr(gen: IRGenerator, node: NewExpr):
    """Lower new ClassName(args) → ClassName_new(args)."""
    from .expressions import lower_expr
    type_name = node.type.base
    if node.type.generic_args:
        type_name = mangle_generic_type(node.type.base, node.type.generic_args)
    args = [lower_expr(gen, a) for a in node.args]
    return IRCall(callee=f"{type_name}_new", args=args)
