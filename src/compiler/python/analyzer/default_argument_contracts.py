"""Semantic boundaries specific to source default arguments."""

from ..source_macro_queries import source_macro_expands_to_any

_CONTEXT_SENSITIVE_PREDEFINED = frozenset({"__func__", "__LINE__", "__FILE__"})


def validate_default_macro_context(analyzer, identifier) -> None:
    """Reject macros whose expansion context cannot survive helper lifting."""

    if not analyzer._analyzing_parameter_default:
        return
    definitions = analyzer.declarations.source_macro_definitions
    if not source_macro_expands_to_any(
        identifier.name,
        definitions,
        _CONTEXT_SENSITIVE_PREDEFINED,
    ):
        return
    analyzer._error(
        f"Source macro '{identifier.name}' cannot be used in a default "
        "argument because it expands to a context-sensitive predefined identifier",
        identifier.line,
        identifier.col,
    )


def validate_constructor_default_member(analyzer, identifier, *, direct_callee=False) -> bool:
    """Reject implicit instance dependencies before a constructor allocates self."""

    if not analyzer._analyzing_constructor_default or analyzer.current_class is None:
        return False
    name = identifier.name
    owner = analyzer.current_class
    if direct_callee:
        member = owner.methods.get(name)
        if member is None:
            member = owner.properties.get(name) or owner.fields.get(name)
    else:
        member = owner.properties.get(name) or owner.fields.get(name) or owner.methods.get(name)
    if member is None or member.access == "class" or getattr(member, "is_constructor", False):
        return False
    analyzer._error(
        f"Constructor defaults cannot reference instance member '{name}' before allocation",
        identifier.line,
        identifier.col,
    )
    return True


__all__ = [
    "validate_constructor_default_member",
    "validate_default_macro_context",
]
