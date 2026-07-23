"""Dependency bundle for portable typed-operator lowering."""

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field

from ...ast_nodes import TypeExpr
from .errors import CodegenError
from .types import CTypeRenderer


@dataclass(frozen=True)
class OperatorLoweringContext:
    use_helper: Callable[[str], None] | None
    fresh_temp: Callable[[str], str]
    type_renderer: CTypeRenderer
    class_table: Mapping[str, object] = field(default_factory=dict)
    interface_table: Mapping[str, object] = field(default_factory=dict)
    enum_names: Set[str] = field(default_factory=frozenset)
    typedef_table: Mapping[str, TypeExpr] = field(default_factory=dict)


def operator_context(
    gen,
    type_renderer: CTypeRenderer,
    *,
    fresh_temp=None,
) -> OperatorLoweringContext:
    analyzed = getattr(gen, "analyzed", None)
    temp_factory = fresh_temp or getattr(gen, "fresh_temp", None)
    if temp_factory is None:
        raise CodegenError("typed operator lowering requires a temp allocator")
    helper_registry = getattr(gen, "helpers", None)
    return OperatorLoweringContext(
        use_helper=helper_registry.use if helper_registry is not None else None,
        fresh_temp=temp_factory,
        class_table=getattr(analyzed, "class_table", {}),
        interface_table=getattr(analyzed, "interface_table", {}),
        enum_names=frozenset(getattr(analyzed, "enum_table", {})),
        typedef_table=getattr(analyzed, "typedef_table", {}),
        type_renderer=type_renderer,
    )


def canonical_operator_type(
    context: OperatorLoweringContext,
    type_expr: TypeExpr | None,
    seen: frozenset[str] = frozenset(),
) -> TypeExpr | None:
    """Resolve declared aliases while preserving every use-site modifier."""
    from .type_resolution import canonical_type

    return canonical_type(type_expr, dict(context.typedef_table), seen)


__all__ = [
    "OperatorLoweringContext",
    "canonical_operator_type",
    "operator_context",
]
