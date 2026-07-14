"""Runtime class candidates used by conservative cycle classification."""

from __future__ import annotations

from collections.abc import Iterator

from ...ast_nodes import TypeExpr


def runtime_type_candidates(gen, static_type: TypeExpr) -> Iterator[TypeExpr]:
    """Yield layouts that a statically typed managed reference may contain."""
    yield static_type
    if static_type.generic_args:
        return
    class_table = gen.analyzed.class_table
    if static_type.base not in class_table:
        return
    for name in class_table:
        if name != static_type.base and _is_subclass(class_table, name, static_type.base):
            yield TypeExpr(base=name)


def _is_subclass(class_table, child: str, parent: str) -> bool:
    current = child
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        info = class_table.get(current)
        current = info.parent if info is not None else None
        if current == parent:
            return True
    return False


__all__ = ["runtime_type_candidates"]
