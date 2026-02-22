"""Class lowering: ClassDecl → IRStructDef + constructor IRFunctionDefs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...analyzer.core import ClassInfo
from ...ast_nodes import (
    BraceInitializer,
    ClassDecl,
    FieldDecl,
    ListLiteral,
    MapLiteral,
    MethodDecl,
    PropertyDecl,
    StructDecl,
    TypeExpr,
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
    IRRawExpr,
    IRReturn,
    IRStructDef,
    IRStructField,
    IRVar,
    IRVarDecl,
)
from .class_members import (
    emit_destructor as _emit_destructor,
)
from .class_members import (
    emit_inherited_methods as _emit_inherited_methods,
)
from .class_members import (
    emit_method as _emit_method,
)
from .class_members import (
    emit_property as _emit_property,
)
from .types import is_generic_class_type, mangle_generic_type, type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_struct_decl(gen: IRGenerator, decl: StructDecl):
    """Emit a plain struct (not class) definition."""
    from .expressions import _expr_text, lower_expr
    fields = []
    for f in decl.fields:
        if f.type and f.type.is_array and f.type.array_size:
            # Array field: encode size in name, use base type
            base_type = TypeExpr(base=f.type.base,
                                 generic_args=f.type.generic_args,
                                 pointer_depth=f.type.pointer_depth)
            size_text = _expr_text(lower_expr(gen, f.type.array_size))
            field_name = f"{f.name}[{size_text}]"
            fields.append(IRStructField(
                c_type=CType(text=type_to_c(base_type)), name=field_name))
        else:
            fields.append(IRStructField(
                c_type=CType(text=type_to_c(f.type)), name=f.name))
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

    # Forward-declare all methods (avoids ordering issues like
    # destructor calling close() before close is defined)
    _emit_method_forward_decls(gen, decl, cls_info)

    # Constructor: ClassName_init and ClassName_new
    _emit_constructor(gen, decl, cls_info)

    # Destructor
    _emit_destructor(gen, decl, cls_info)

    # ARC: visitor function for cyclable classes
    if cls_info.is_cyclable:
        _emit_visitor(gen, decl.name, cls_info)

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


def _emit_visitor(gen: IRGenerator, class_name: str, cls_info: ClassInfo):
    """Emit ClassName_visit(self, fn) for cycle detection on cyclable classes.

    The visitor passes field ADDRESSES (void**) so the callback can either
    read the value (for trial decrement) or NULL it (to break cycles).
    Only visits cyclable-type fields -- non-cyclable fields can't form cycles.
    """
    lines = []
    for fname, fd in cls_info.fields.items():
        if not fd.type:
            continue
        field_cls = gen.analyzed.class_table.get(fd.type.base)
        if field_cls and field_cls.is_cyclable:
            lines.append(
                f"    if (self->{fname}) fn((void**)&self->{fname});")
    if not lines:
        return
    body = "\n".join(lines)
    text = (
        f"static void {class_name}_visit({class_name}* self, "
        f"void (*fn)(void**)) {{\n{body}\n}}"
    )
    gen.module.raw_sections.append(text)


def _emit_method_forward_decls(gen: IRGenerator, decl: ClassDecl,
                                cls_info: ClassInfo):
    """Emit forward declarations for own + inherited methods."""
    name = decl.name
    fwd_lines = []
    for member in decl.members:
        if isinstance(member, MethodDecl) and member.name != decl.name and member.name != "__del__":
            is_static = member.access == "class"
            params = []
            if not is_static:
                params.append(f"{name}* self")
            for p in member.params:
                params.append(f"{type_to_c(p.type)} {p.name}")
            ret = type_to_c(member.return_type) if member.return_type else "void"
            fwd_lines.append(f"{ret} {name}_{member.name}({', '.join(params)});")
    # Also forward-declare inherited method wrappers so own methods can call them
    own_names = {m.name for m in decl.members if isinstance(m, MethodDecl)}
    parent_name = cls_info.parent
    seen = set(own_names)
    while parent_name and parent_name in gen.analyzed.class_table:
        parent_info = gen.analyzed.class_table[parent_name]
        for mname, method in parent_info.methods.items():
            if mname in seen or mname == "__del__" or mname == parent_name:
                continue
            seen.add(mname)
            params = [f"{name}* self"]
            for p in method.params:
                params.append(f"{type_to_c(p.type)} {p.name}")
            ret = type_to_c(method.return_type) if method.return_type else "void"
            fwd_lines.append(f"{ret} {name}_{mname}({', '.join(params)});")
        parent_name = parent_info.parent
    if fwd_lines:
        gen.module.forward_decls.extend(fwd_lines)


def _lower_field_init(gen: IRGenerator, field: FieldDecl):
    """Lower a field initializer, handling collection types properly."""
    from .expressions import lower_expr
    init = field.initializer
    ct = gen.analyzed.class_table
    # Empty {} for generic-typed fields → TYPE_new()
    if isinstance(init, BraceInitializer) and not init.elements:
        if field.type and is_generic_class_type(field.type, ct):
            mangled = mangle_generic_type(field.type.base, field.type.generic_args)
            return IRCall(callee=f"{mangled}_new", args=[])
    # Empty [] for generic-typed fields → TYPE_new()
    if isinstance(init, ListLiteral) and not init.elements:
        if field.type and is_generic_class_type(field.type, ct):
            mangled = mangle_generic_type(field.type.base, field.type.generic_args)
            return IRCall(callee=f"{mangled}_new", args=[])
    # Empty {} for generic-typed fields → TYPE_new()
    if isinstance(init, MapLiteral) and not init.entries:
        if field.type and is_generic_class_type(field.type, ct):
            mangled = mangle_generic_type(field.type.base, field.type.generic_args)
            return IRCall(callee=f"{mangled}_new", args=[])
    return lower_expr(gen, init)


def _emit_class_struct(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo):
    """Emit the struct definition for a class."""
    fields: list[IRStructField] = []

    # ARC: refcount as the first field (before everything else)
    fields.append(IRStructField(c_type=CType(text="int"), name="__rc"))

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

    # ARC: set refcount to 1
    init_body_stmts.append(IRAssign(
        target=IRFieldAccess(obj=IRVar(name="self"), field="__rc", arrow=True),
        value=IRLiteral(text="1"),
    ))

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
        gen._func_var_decls = []
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


