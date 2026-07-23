"""Shared lowering for source parameters and object qualifiers."""

from ...hosted_abi import HOSTED_MACROS, HOSTED_TYPEDEF_NAMES
from ...qualifier_provenance import effective_outer_volatile
from ..nodes import CType, IRParam


def source_binding_c_name(name: str, analyzed=None) -> str:
    """Return a C identifier distinct from every same-spelled source type."""
    if name in HOSTED_MACROS or _binding_conflicts_with_type(name, analyzed):
        return f"__btrc_source_{name}"
    return name


def _binding_conflicts_with_type(name: str, analyzed) -> bool:
    if name in HOSTED_TYPEDEF_NAMES:
        return True
    if analyzed is None:
        return False
    tables = (
        analyzed.class_table,
        analyzed.interface_table,
        analyzed.struct_table,
        analyzed.typedef_table,
        analyzed.enum_table,
        analyzed.rich_enum_table,
    )
    if any(name in table for table in tables):
        return True
    return any(
        name in info.generic_params
        for table in (analyzed.class_table, analyzed.interface_table)
        for info in table.values()
    ) or any(
        name in method.generic_params for info in analyzed.class_table.values() for method in info.methods.values()
    )


def source_field_c_name(analyzed, receiver, name: str, *, resolve_type=None) -> str:
    """Return the C field name for a generated rich-enum payload field."""
    if name not in HOSTED_MACROS:
        return name

    from ...ast_nodes import FieldAccessExpr

    if not isinstance(receiver, FieldAccessExpr):
        return name
    data_access = receiver.obj
    if not isinstance(data_access, FieldAccessExpr) or data_access.field != "data":
        return name
    root = data_access.obj
    root_type = resolve_type(root) if resolve_type is not None else analyzed.node_types.get(id(root))
    declaration = analyzed.rich_enum_table.get(root_type.base) if root_type is not None else None
    if declaration is None:
        return name
    variant = next(
        (item for item in declaration.variants if item.name == receiver.field),
        None,
    )
    if variant is None or all(parameter.name != name for parameter in variant.params):
        return name
    return source_binding_c_name(name)


def lower_source_param(
    parameter,
    render,
    analyzed=None,
    *,
    resolved_type=None,
) -> IRParam:
    return lower_named_source_type_param(
        parameter.type,
        render(parameter.type),
        parameter.name,
        analyzed,
        resolved_type=resolved_type,
    )


def lower_named_source_type_param(
    type_expr,
    c_type,
    name,
    analyzed=None,
    *,
    resolved_type=None,
) -> IRParam:
    """Lower a synthesized parameter that represents one source-typed slot."""

    represented_type = resolved_type or type_expr
    typedefs = analyzed.typedef_table if analyzed is not None else {}
    return IRParam(
        c_type=c_type if isinstance(c_type, CType) else CType(text=c_type),
        name=source_binding_c_name(name, analyzed),
        is_volatile=bool(represented_type and represented_type.is_volatile),
        effective_is_volatile=effective_outer_volatile(
            represented_type,
            typedefs,
        ),
    )


__all__ = [
    "lower_named_source_type_param",
    "lower_source_param",
    "source_binding_c_name",
    "source_field_c_name",
]
