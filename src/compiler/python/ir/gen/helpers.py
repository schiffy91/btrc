"""Collect runtime helpers through a validated dependency graph."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..helpers.core import HelperDef
from ..helpers.registry import HELPERS
from ..nodes import IRHelperDecl

if TYPE_CHECKING:
    from .generator import IRGenerator


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


def helper_decls_for_roots(roots: set[str]) -> list[IRHelperDecl]:
    """Materialize a dependency-complete, stable helper declaration list."""

    index, stable_order = _helper_index()
    ordered = _dependency_order(roots, index, stable_order)
    declarations = []
    for name in ordered:
        category, definition = index[name]
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


def collect_helpers(gen: IRGenerator) -> None:
    """Materialize used helpers after validating their dependency graph."""

    if not gen._used_helpers:
        return

    declarations = helper_decls_for_roots(set(gen._used_helpers))
    for declaration in declarations:
        for header in declaration.required_headers:
            gen.require_runtime_include(header)
    gen.module.helper_decls.extend(declarations)


__all__ = ["collect_helpers", "helper_decls_for_roots"]
