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


__all__ = ["instance_storage_name", "property_needs_backing"]
