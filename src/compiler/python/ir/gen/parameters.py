"""Shared lowering for source parameters and object qualifiers."""

from ...hosted_abi import HOSTED_MACROS, HOSTED_TYPEDEF_NAMES
from ..nodes import CType, IRParam
from .types import type_to_c


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


def lower_source_param(parameter, render=type_to_c, analyzed=None) -> IRParam:
    return IRParam(
        c_type=CType(text=render(parameter.type)),
        name=source_binding_c_name(parameter.name, analyzed),
        is_volatile=bool(parameter.type and parameter.type.is_volatile),
    )


__all__ = [
    "lower_source_param",
    "source_binding_c_name",
    "source_field_c_name",
]
