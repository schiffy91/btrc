"""Canonical instance-storage names for class fields and auto-properties."""

from .ast_nodes import FieldDecl, PropertyDecl


def instance_storage_name(member) -> str | None:
    """Return the emitted C member name, or None for non-storage members."""
    if isinstance(member, FieldDecl):
        return member.name if member.access != "class" else None
    if isinstance(member, PropertyDecl):
        if member.access == "class" or not property_needs_backing(member):
            return None
        return f"_prop_{member.name}"
    return None


def property_needs_backing(property_decl: PropertyDecl) -> bool:
    return bool(
        (property_decl.has_getter and property_decl.getter_body is None)
        or (property_decl.has_setter and property_decl.setter_body is None)
    )


def custom_property_getter(class_table, receiver_type, field: str) -> bool:
    """Whether a field-shaped read dispatches user-defined getter code."""
    if receiver_type is None:
        return False
    class_info = class_table.get(receiver_type.base)
    property_decl = class_info.properties.get(field) if class_info else None
    return bool(property_decl is not None and property_decl.getter_body is not None)


__all__ = [
    "custom_property_getter",
    "instance_storage_name",
    "property_needs_backing",
]
