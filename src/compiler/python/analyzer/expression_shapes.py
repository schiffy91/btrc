"""Small structural predicates shared by expression analysis."""

from ..ast_nodes import BraceInitializer, ListLiteral, MapLiteral


def is_empty_contextual_literal(expression) -> bool:
    return (
        (isinstance(expression, BraceInitializer) and not expression.elements)
        or (isinstance(expression, ListLiteral) and not expression.elements)
        or (isinstance(expression, MapLiteral) and not expression.entries)
    )


__all__ = ["is_empty_contextual_literal"]
