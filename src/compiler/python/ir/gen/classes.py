"""Class lowering: ClassDecl → IRStructDef + method/ctor/dtor IRFunctionDefs."""

from __future__ import annotations
from typing import TYPE_CHECKING

from ...ast_nodes import (
    BraceInitializer, ClassDecl, FieldDecl, ListLiteral, MapLiteral,
    MethodDecl, NewExpr, PropertyDecl, StructDecl, TypeExpr,
)
from ...analyzer import ClassInfo
from ..nodes import (
    CType, IRAssign, IRBlock, IRCall, IRCast, IRExprStmt, IRFieldAccess,
    IRFunctionDef, IRLiteral, IRParam, IRRawExpr, IRReturn, IRStructDef,
    IRStructField, IRVar, IRVarDecl,
)
from .types import type_to_c, is_pointer_type, is_collection_type, mangle_generic_type

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_struct_decl(gen: IRGenerator, decl: StructDecl):
    """Emit a plain struct (not class) definition."""
    fields = []
    for f in decl.fields:
        fields.append(IRStructField(c_type=CType(text=type_to_c(f.type)), name=f.name))
    gen.module.struct_defs.append(IRStructDef(name=decl.name, fields=fields))


def emit_class_decl(gen: IRGenerator, decl: ClassDecl):
    """Emit a class: struct + constructor + destructor + methods."""
    cls_info = gen.analyzed.class_table.get(decl.name)
    if not cls_info:
        return

    gen.current_class = cls_info
    gen.current_class_name = decl.name

    # Struct definition
    _emit_class_struct(gen, decl, cls_info)

    # Constructor: ClassName_init and ClassName_new
    _emit_constructor(gen, decl, cls_info)

    # Destructor
    _emit_destructor(gen, decl, cls_info)

    # Methods
    own_methods = set()
    for member in decl.members:
        if isinstance(member, MethodDecl) and member.name != decl.name and member.name != "__del__":
            _emit_method(gen, decl, member)
            own_methods.add(member.name)
        elif isinstance(member, PropertyDecl):
            _emit_property(gen, decl, member)

    # Inherit parent methods that aren't overridden
    if cls_info.parent and cls_info.parent in gen.analyzed.class_table:
        _emit_inherited_methods(gen, decl, cls_info, own_methods)

    gen.current_class = None
    gen.current_class_name = ""


def _lower_field_init(gen: IRGenerator, field: FieldDecl):
    """Lower a field initializer, handling collection types properly."""
    from .expressions import lower_expr
    init = field.initializer
    # Empty {} for collection-typed fields → collection_new()
    if isinstance(init, BraceInitializer) and not init.elements:
        if field.type and is_collection_type(field.type):
            mangled = mangle_generic_type(field.type.base, field.type.generic_args)
            return IRCall(callee=f"{mangled}_new", args=[])
    # Empty [] for List-typed fields → List_new() with correct element type
    if isinstance(init, ListLiteral) and not init.elements:
        if field.type and field.type.base == "List" and field.type.generic_args:
            mangled = mangle_generic_type("List", field.type.generic_args)
            return IRCall(callee=f"{mangled}_new", args=[])
    # Empty {} for Map-typed fields → Map_new()
    if isinstance(init, MapLiteral) and not init.entries:
        if field.type and field.type.base == "Map" and field.type.generic_args:
            mangled = mangle_generic_type("Map", field.type.generic_args)
            return IRCall(callee=f"{mangled}_new", args=[])
    return lower_expr(gen, init)


def _emit_class_struct(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo):
    """Emit the struct definition for a class."""
    fields: list[IRStructField] = []

    # Parent fields (if inheriting)
    if cls_info.parent and cls_info.parent in gen.analyzed.class_table:
        parent = gen.analyzed.class_table[cls_info.parent]
        for name, fd in parent.fields.items():
            fields.append(IRStructField(c_type=CType(text=type_to_c(fd.type)), name=name))

    # Own fields
    for member in decl.members:
        if isinstance(member, FieldDecl):
            fields.append(IRStructField(
                c_type=CType(text=type_to_c(member.type)), name=member.name))
        # Properties → backing field in struct
        elif isinstance(member, PropertyDecl):
            fields.append(IRStructField(
                c_type=CType(text=type_to_c(member.type)), name=f"_prop_{member.name}"))

    gen.module.struct_defs.append(IRStructDef(name=decl.name, fields=fields))


def _emit_constructor(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo):
    """Emit ClassName_init(self, ...) and ClassName_new(...)."""
    name = decl.name
    ctor = cls_info.constructor

    # Determine constructor params
    ctor_params = []
    if ctor:
        for p in ctor.params:
            ctor_params.append(IRParam(c_type=CType(text=type_to_c(p.type)), name=p.name))

    # _init function: takes self pointer + ctor params
    init_params = [IRParam(c_type=CType(text=f"{name}*"), name="self")] + ctor_params
    init_body_stmts = []

    # Initialize fields with defaults
    for member in decl.members:
        if isinstance(member, FieldDecl) and member.initializer:
            value = _lower_field_init(gen, member)
            init_body_stmts.append(IRAssign(
                target=IRFieldAccess(obj=IRVar(name="self"), field=member.name, arrow=True),
                value=value,
            ))

    # Constructor body (user code)
    if ctor and ctor.body:
        from .statements import lower_block
        user_block = lower_block(gen, ctor.body)
        init_body_stmts.extend(user_block.stmts)

    gen.module.function_defs.append(IRFunctionDef(
        name=f"{name}_init",
        return_type=CType(text="void"),
        params=init_params,
        body=IRBlock(stmts=init_body_stmts),
    ))

    # _new function: malloc + memset + init + return
    new_body_stmts = [
        IRVarDecl(
            c_type=CType(text=f"{name}*"), name="self",
            init=IRCast(
                target_type=f"{name}*",
                expr=IRCall(callee="malloc", args=[IRRawExpr(text=f"sizeof({name})")]),
            ),
        ),
        IRExprStmt(expr=IRCall(
            callee="memset",
            args=[IRVar(name="self"), IRLiteral(text="0"),
                  IRRawExpr(text=f"sizeof({name})")],
        )),
        IRExprStmt(expr=IRCall(
            callee=f"{name}_init",
            args=[IRVar(name="self")] + [IRVar(name=p.name) for p in ctor_params],
        )),
        IRReturn(value=IRVar(name="self")),
    ]

    gen.module.function_defs.append(IRFunctionDef(
        name=f"{name}_new",
        return_type=CType(text=f"{name}*"),
        params=ctor_params[:],  # Same params as ctor (no self)
        body=IRBlock(stmts=new_body_stmts),
    ))


def _emit_destructor(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo):
    """Emit ClassName_destroy(self) which frees internal resources."""
    name = decl.name
    dtor = cls_info.methods.get("__del__")

    body_stmts = []
    if dtor and dtor.body:
        from .statements import lower_block
        body_stmts = lower_block(gen, dtor.body).stmts

    # Recursively destroy owned pointer-type fields
    for fname, fd in cls_info.fields.items():
        from ..nodes import IRIf, IRBinOp
        # Collection fields (List, Map, Set) → mangled_free()
        if fd.type and is_collection_type(fd.type):
            mangled = mangle_generic_type(fd.type.base, fd.type.generic_args)
            fa = IRFieldAccess(obj=IRVar(name="self"), field=fname, arrow=True)
            body_stmts.append(IRIf(
                condition=IRBinOp(left=fa, op="!=", right=IRLiteral(text="NULL")),
                then_block=IRBlock(stmts=[IRExprStmt(
                    expr=IRCall(callee=f"{mangled}_free",
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


def _emit_method(gen: IRGenerator, decl: ClassDecl, method: MethodDecl):
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


def _emit_property(gen: IRGenerator, decl: ClassDecl, prop: PropertyDecl):
    """Emit getter/setter functions for a property."""
    name = decl.name
    prop_type = type_to_c(prop.type) if prop.type else "int"
    backing = f"_prop_{prop.name}"

    if prop.has_getter:
        if prop.getter_body:
            from .statements import lower_block
            body = lower_block(gen, prop.getter_body)
        else:
            # Auto-getter: return self->_prop_x;
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
            # Auto-setter: self->_prop_x = value;
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


def _emit_inherited_methods(gen: IRGenerator, decl: ClassDecl,
                            cls_info: ClassInfo, own_methods: set[str]):
    """Emit wrapper functions for inherited methods not overridden."""
    parent_name = cls_info.parent
    while parent_name and parent_name in gen.analyzed.class_table:
        parent_info = gen.analyzed.class_table[parent_name]
        for mname, method in parent_info.methods.items():
            if mname in own_methods or mname == "__del__" or mname == parent_name:
                continue
            # Emit wrapper: Child_method(self, ...) → Parent_method(self, ...)
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
    from .types import mangle_generic_type
    type_name = node.type.base
    if node.type.generic_args:
        type_name = mangle_generic_type(node.type.base, node.type.generic_args)
    args = [lower_expr(gen, a) for a in node.args]
    return IRCall(callee=f"{type_name}_new", args=args)


# Import needed for _new body
from ..nodes import IRRawExpr
