"""Class lowering: ClassDecl → IRStructDef + constructor IRFunctionDefs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...analyzer.core import ClassInfo
from ...ast_nodes import (
    ClassDecl,
    MethodDecl,
    PropertyDecl,
    StructDecl,
    TypeExpr,
)
from ...qualifier_provenance import effective_outer_volatile
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
from .class_storage_fields import lower_instance_storage_field
from .class_visitors import emit_class_visitor
from .types import CTypeRenderer

if TYPE_CHECKING:
    from .lowerer import IRLowerer


def emit_struct_decl(
    gen: IRLowerer,
    decl: StructDecl,
    type_renderer: CTypeRenderer,
):
    """Emit a plain struct (not class) definition."""
    if decl.is_forward:
        return
    from .expressions import lower_expr

    fields = []
    for f in decl.fields:
        if f.type and f.type.is_array and f.type.array_size:
            # Array declarators remain structured through IR emission.
            from ...type_composition import strip_outer_storage

            base_type = strip_outer_storage(f.type, array=True)
            fields.append(
                IRStructField(
                    c_type=CType(text=type_renderer.render(base_type)),
                    name=f.name,
                    array_size=lower_expr(
                        gen,
                        f.type.array_size,
                        type_renderer,
                    ),
                    is_volatile=bool(f.type.is_volatile),
                    effective_is_volatile=effective_outer_volatile(
                        f.type,
                        gen.analyzed.typedef_table,
                    ),
                )
            )
        else:
            fields.append(
                IRStructField(
                    c_type=CType(text=type_renderer.render(f.type)),
                    name=f.name,
                    is_volatile=bool(f.type and f.type.is_volatile),
                    effective_is_volatile=effective_outer_volatile(
                        f.type,
                        gen.analyzed.typedef_table,
                    ),
                )
            )
    gen.module.struct_defs.append(
        IRStructDef(
            name=decl.name,
            fields=fields,
            pack_alignment=gen._pack_alignments.get(id(decl)),
        )
    )


def emit_class_decl(
    gen: IRLowerer,
    decl: ClassDecl,
    type_renderer: CTypeRenderer,
):
    """Emit a class: struct + constructor + destructor + methods."""
    cls_info = gen.analyzed.class_table.get(decl.name)
    if not cls_info:
        return

    gen.current_class = cls_info
    gen.current_class_name = decl.name

    # Struct definition
    _emit_class_struct(gen, decl, cls_info, type_renderer)
    _emit_static_fields(gen, decl, type_renderer)

    # Forward-declare all methods (avoids ordering issues like
    # destructor calling close() before close is defined)
    emit_class_callable_declarations(
        gen,
        decl,
        cls_info,
        type_renderer,
    )

    # Constructor: ClassName_init and ClassName_new
    _emit_constructor(gen, decl, cls_info, type_renderer)

    # Destructor
    destructor_hook = _emit_destructor(
        gen,
        decl,
        cls_info,
        type_renderer,
    )

    # ARC: every representation with managed outgoing slots gets a visitor.
    from .cycle_metadata import type_needs_visitor

    visitor_name = None
    if type_needs_visitor(gen, TypeExpr(base=decl.name), set()):
        emit_class_visitor(
            gen,
            decl.name,
            cls_info.instance_storage,
            type_renderer,
        )
        from .cycle_metadata import cycle_visitor_symbol

        visitor_name = cycle_visitor_symbol(decl.name)
    emit_arc_descriptor(gen, decl.name, visitor_name, destructor_hook)

    # Methods
    own_methods = set()
    own_properties = set()
    for member in decl.members:
        if isinstance(member, MethodDecl) and not member.is_constructor and member.name != "__del__":
            own_methods.add(member.name)
            if not member.generic_params and not member.is_abstract and member.body is not None:
                _emit_method(gen, decl, member, type_renderer)
        elif isinstance(member, PropertyDecl):
            _emit_property(gen, decl, member, type_renderer)
            own_properties.add(member.name)

    _emit_inherited_properties(
        gen,
        decl,
        cls_info,
        own_properties,
        type_renderer,
    )

    # Inherit parent methods that aren't overridden
    if cls_info.parent and cls_info.parent in gen.analyzed.class_table:
        _emit_inherited_methods(
            gen,
            decl,
            cls_info,
            own_methods,
            type_renderer,
        )

    gen.current_class = None
    gen.current_class_name = ""


def _emit_class_struct(
    gen: IRLowerer,
    decl: ClassDecl,
    cls_info: ClassInfo,
    type_renderer: CTypeRenderer,
):
    """Emit the struct definition for a class."""
    fields: list[IRStructField] = []

    # The real header subobject must remain first: runtime ARC type erasure
    # relies on pointer interconvertibility with this exact common prefix.
    fields.append(arc_header_field(gen))

    for storage_name, member in cls_info.instance_storage:
        fields.append(
            lower_instance_storage_field(
                gen,
                storage_name,
                member.type,
                type_renderer,
            )
        )

    gen.module.struct_defs.append(
        IRStructDef(
            name=decl.name,
            fields=fields,
            pack_alignment=gen._pack_alignments.get(id(decl)),
        )
    )
