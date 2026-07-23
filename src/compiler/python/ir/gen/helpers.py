"""Own runtime-helper selection and dependency materialization."""

from __future__ import annotations

from ..helpers.core import HelperDef
from ..helpers.registry import HELPERS
from ..nodes import IRHelperDecl, IRModule


def _helper_index() -> tuple[dict[str, tuple[str, HelperDef]], list[str]]:
    index: dict[str, tuple[str, HelperDef]] = {}
    stable_order: list[str] = []
    for category, helpers in HELPERS.items():
        for name, definition in helpers.items():
            if name in index:
                raise ValueError(f"duplicate runtime helper registration: {name}")
            index[name] = (category, definition)
            stable_order.append(name)
    return index, stable_order


def _dependency_order(
    roots: set[str],
    index: dict[str, tuple[str, HelperDef]],
    stable_order: list[str],
) -> list[str]:
    """Return the reachable helper graph in dependency-first stable order."""

    unknown = roots - index.keys()
    if unknown:
        raise ValueError(f"unknown runtime helper(s): {', '.join(sorted(unknown))}")

    state: dict[str, int] = {}
    ordered: list[str] = []

    def visit(name: str, path: tuple[str, ...]) -> None:
        current = state.get(name, 0)
        if current == 2:
            return
        if current == 1:
            cycle = " -> ".join((*path, name))
            raise ValueError(f"runtime helper dependency cycle: {cycle}")
        state[name] = 1
        _category, definition = index[name]
        for dependency in definition.depends_on:
            if dependency not in index:
                raise ValueError(f"runtime helper {name} has unknown dependency {dependency}")
            visit(dependency, (*path, name))
        state[name] = 2
        ordered.append(name)

    for name in stable_order:
        if name in roots:
            visit(name, ())
    return ordered


class RuntimeHelperRegistry:
    """Track one lowering run's helper roots and materialize their closure."""

    def __init__(self) -> None:
        self._roots: set[str] = set()
        self._index, self._stable_order = _helper_index()

    @property
    def roots(self) -> frozenset[str]:
        return frozenset(self._roots)

    def use(self, name: str) -> None:
        """Register a helper root, rejecting misspellings at the call site."""
        if name not in self._index:
            raise ValueError(f"unknown runtime helper: {name}")
        self._roots.add(name)

    def declarations_for(self, roots: set[str]) -> list[IRHelperDecl]:
        """Materialize a dependency-complete, stable declaration list."""
        ordered = _dependency_order(roots, self._index, self._stable_order)
        declarations = []
        for name in ordered:
            category, definition = self._index[name]
            declarations.append(
                IRHelperDecl(
                    category=category,
                    name=name,
                    c_source=definition.c_source,
                    depends_on=list(definition.depends_on),
                    required_headers=list(definition.required_headers),
                )
            )
        return declarations

    def materialize(self, module: IRModule, require_header) -> None:
        """Attach the selected dependency closure to ``module`` exactly once."""
        if not self._roots:
            return
        declarations = self.declarations_for(self._roots)
        for declaration in declarations:
            for header in declaration.required_headers:
                require_header(header)
        module.helper_decls.extend(declarations)


__all__ = ["RuntimeHelperRegistry"]
