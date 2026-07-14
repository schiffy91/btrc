"""Shared formatting rules for C declarator types."""


def qualify_volatile_object(c_type: str, is_volatile: bool) -> str:
    """Qualify the declared object, rather than a pointer's pointee."""
    if not is_volatile:
        return c_type
    return f"{c_type} volatile" if c_type.endswith("*") else f"volatile {c_type}"


__all__ = ["qualify_volatile_object"]
