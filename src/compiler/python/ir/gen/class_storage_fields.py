"""Structured C storage fields shared by ordinary and generic classes."""

from ...qualifier_provenance import effective_outer_volatile
from ...type_composition import strip_outer_storage
from ..nodes import CType, IRStructField
from .types import type_to_c


def lower_instance_storage_field(
    gen,
    name,
    field_type,
    *,
    bound_lowerer=None,
) -> IRStructField:
    """Preserve a fixed source array as embedded class-instance storage."""

    if field_type is not None and field_type.is_array and field_type.array_size is not None:
        if bound_lowerer is None:
            from .expressions import lower_expr

            def bound_lowerer(expression):
                return lower_expr(gen, expression)

        element_type = strip_outer_storage(field_type, array=True)
        return IRStructField(
            c_type=CType(text=type_to_c(element_type)),
            name=name,
            array_size=bound_lowerer(field_type.array_size),
            is_volatile=bool(field_type.is_volatile),
            effective_is_volatile=effective_outer_volatile(
                field_type,
                gen.analyzed.typedef_table,
            ),
        )
    return IRStructField(
        c_type=CType(text=type_to_c(field_type)),
        name=name,
        is_volatile=bool(field_type and field_type.is_volatile),
        effective_is_volatile=effective_outer_volatile(
            field_type,
            gen.analyzed.typedef_table,
        ),
    )


__all__ = ["lower_instance_storage_field"]
