"""Lower class-access fields to one translation-unit object each."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...ast_nodes import BraceInitializer, FieldDecl, ListLiteral
from ...qualifier_provenance import effective_outer_volatile
from ..nodes import CType, IRGlobalDecl, IRLiteral
from .types import type_to_c

if TYPE_CHECKING:
    from ...ast_nodes import ClassDecl
    from .lowerer import IRLowerer


def emit_static_fields(gen: IRLowerer, declaration: ClassDecl) -> None:
    from .aggregate_initializers import lower_static_initializer
    from .expressions import lower_expr

    for field in declaration.members:
        if not isinstance(field, FieldDecl) or field.access != "class":
            continue
        field_type, array_size = _static_field_type(gen, field)
        initializer = field.initializer
        if initializer is not None:
            from .callable_boundaries import reject_persistent_callable_escape

            reject_persistent_callable_escape(
                gen,
                field.type,
                initializer,
                "class field storage",
            )
        if isinstance(initializer, (BraceInitializer, ListLiteral)):
            init = lower_static_initializer(gen, initializer)
        else:
            init = lower_expr(gen, initializer) if initializer is not None else None
        gen.module.global_decls.append(
            IRGlobalDecl(
                c_type=CType(text=type_to_c(field_type)),
                name=f"{declaration.name}_{field.name}",
                init=init,
                array_size=array_size,
                is_static=True,
                is_volatile=bool(field.type.is_volatile),
                effective_is_volatile=effective_outer_volatile(
                    field.type,
                    gen.analyzed.typedef_table,
                ),
            )
        )


def _static_field_type(gen, field):
    if not field.type.is_array:
        return field.type, None
    from ...type_composition import strip_outer_storage

    field_type = strip_outer_storage(field.type, array=True)
    if field.type.array_size is not None:
        from .expressions import lower_expr

        return field_type, lower_expr(gen, field.type.array_size)
    if isinstance(field.initializer, (BraceInitializer, ListLiteral)):
        return field_type, IRLiteral(text=str(len(field.initializer.elements)))
    # Without backing storage an unsized array is a rebindable pointer slot.
    return field.type, None


__all__ = ["emit_static_fields"]
