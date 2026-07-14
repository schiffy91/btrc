"""Class lowering: ClassDecl → IRStructDef + constructor IRFunctionDefs."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from ...analyzer.core import ClassInfo
from ...ast_nodes import (
    ClassDecl,
    MethodDecl,
    PropertyDecl,
    StructDecl,
    TypeExpr,
)
from ..nodes import (
    CType,
    IRStructDef,
    IRStructField,
)
from .arc_metadata import arc_header_field, emit_arc_descriptor
from .class_constructors import emit_constructor as _emit_constructor
from .class_declarations import emit_class_callable_declarations
from .class_members import (
    emit_destructor as _emit_destructor,
)
from .class_members import (
    emit_inherited_methods as _emit_inherited_methods,
)
from .class_members import (
    emit_method as _emit_method,
)
from .class_properties import (
    emit_inherited_properties as _emit_inherited_properties,
)
from .class_properties import (
    emit_property as _emit_property,
)
from .class_static_fields import emit_static_fields as _emit_static_fields
from .class_visitors import emit_class_visitor
from .types import type_to_c

if TYPE_CHECKING:
    from .generator import IRGenerator


def emit_struct_decl(gen: IRGenerator, decl: StructDecl):
    """Emit a plain struct (not class) definition."""
    if decl.is_forward:
        return
    from .expressions import lower_expr

    fields = []
    for f in decl.fields:
        if f.type and f.type.is_array and f.type.array_size:
            # Array declarators remain structured through IR emission.
            base_type = replace(f.type, is_array=False, array_size=None)
            fields.append(
                IRStructField(
                    c_type=CType(text=type_to_c(base_type)),
                    name=f.name,
                    array_size=lower_expr(gen, f.type.array_size),
                )
            )
        else:
            fields.append(IRStructField(c_type=CType(text=type_to_c(f.type)), name=f.name))
    gen.module.struct_defs.append(
        IRStructDef(
            name=decl.name,
            fields=fields,
            pack_alignment=gen._pack_alignments.get(id(decl)),
        )
    )


def emit_class_decl(gen: IRGenerator, decl: ClassDecl):
    """Emit a class: struct + constructor + destructor + methods."""
    cls_info = gen.analyzed.class_table.get(decl.name)
    if not cls_info:
        return

    gen.current_class = cls_info
    gen.current_class_name = decl.name

    # Struct definition
    _emit_class_struct(gen, decl, cls_info)
    _emit_static_fields(gen, decl)

    # Forward-declare all methods (avoids ordering issues like
    # destructor calling close() before close is defined)
    emit_class_callable_declarations(gen, decl, cls_info)

    # Constructor: ClassName_init and ClassName_new
    _emit_constructor(gen, decl, cls_info)

    # Destructor
    _emit_destructor(gen, decl, cls_info)

    # ARC: every representation with managed outgoing slots gets a visitor.
    from .cycle_metadata import type_needs_visitor

    visitor_name = None
    if type_needs_visitor(gen, TypeExpr(base=decl.name), set()):
        emit_class_visitor(gen, decl.name, cls_info.instance_storage)
        from .cycle_metadata import cycle_visitor_symbol

        visitor_name = cycle_visitor_symbol(decl.name)
    emit_arc_descriptor(gen, decl.name, visitor_name)

    # Methods
    own_methods = set()
    own_properties = set()
    for member in decl.members:
        if isinstance(member, MethodDecl) and not member.is_constructor and member.name != "__del__":
            own_methods.add(member.name)
            if not member.is_abstract and member.body is not None:
                _emit_method(gen, decl, member)
        elif isinstance(member, PropertyDecl):
            _emit_property(gen, decl, member)
            own_properties.add(member.name)

    _emit_inherited_properties(gen, decl, cls_info, own_properties)

    # Inherit parent methods that aren't overridden
    if cls_info.parent and cls_info.parent in gen.analyzed.class_table:
        _emit_inherited_methods(gen, decl, cls_info, own_methods)

    gen.current_class = None
    gen.current_class_name = ""


def _emit_class_struct(gen: IRGenerator, decl: ClassDecl, cls_info: ClassInfo):
    """Emit the struct definition for a class."""
    fields: list[IRStructField] = []

    # The real header subobject must remain first: runtime ARC type erasure
    # relies on pointer interconvertibility with this exact common prefix.
    fields.append(arc_header_field(gen))

    for storage_name, member in cls_info.instance_storage:
        fields.append(
            IRStructField(
                c_type=CType(text=type_to_c(member.type)),
                name=storage_name,
            )
        )

    gen.module.struct_defs.append(
        IRStructDef(
            name=decl.name,
            fields=fields,
            pack_alignment=gen._pack_alignments.get(id(decl)),
        )
    )
