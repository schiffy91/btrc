"""Dependency bundle for portable typed-operator lowering."""

from collections.abc import Callable, Mapping, Set
from dataclasses import dataclass, field, replace

from ...ast_nodes import TypeExpr
from .errors import CodegenError


@dataclass(frozen=True)
class OperatorLoweringContext:
    use_helper: Callable[[str], None] | None
    fresh_temp: Callable[[str], str]
    class_table: Mapping[str, object] = field(default_factory=dict)
    interface_table: Mapping[str, object] = field(default_factory=dict)
    enum_names: Set[str] = field(default_factory=frozenset)
    typedef_table: Mapping[str, TypeExpr] = field(default_factory=dict)


def operator_context(gen, *, fresh_temp=None) -> OperatorLoweringContext:
    analyzed = getattr(gen, "analyzed", None)
    temp_factory = fresh_temp or getattr(gen, "fresh_temp", None)
    if temp_factory is None:
        raise CodegenError("typed operator lowering requires a temp allocator")
    return OperatorLoweringContext(
        use_helper=getattr(gen, "use_helper", None),
        fresh_temp=temp_factory,
        class_table=getattr(analyzed, "class_table", {}),
        interface_table=getattr(analyzed, "interface_table", {}),
        enum_names=frozenset(getattr(analyzed, "enum_table", {})),
        typedef_table=getattr(analyzed, "typedef_table", {}),
    )


def canonical_operator_type(
    context: OperatorLoweringContext,
    type_expr: TypeExpr | None,
    seen: frozenset[str] = frozenset(),
) -> TypeExpr | None:
    """Resolve declared aliases while preserving every use-site modifier."""
    if type_expr is None or type_expr.base not in context.typedef_table or type_expr.base in seen:
        return type_expr
    resolved = canonical_operator_type(
        context,
        context.typedef_table[type_expr.base],
        seen | {type_expr.base},
    )
    assert resolved is not None
    return replace(
        resolved,
        pointer_depth=resolved.pointer_depth + type_expr.pointer_depth,
        is_array=resolved.is_array or type_expr.is_array,
        array_size=(type_expr.array_size if type_expr.array_size is not None else resolved.array_size),
        is_const=resolved.is_const or type_expr.is_const,
        is_nullable=resolved.is_nullable or type_expr.is_nullable,
    )


__all__ = [
    "OperatorLoweringContext",
    "canonical_operator_type",
    "operator_context",
]
