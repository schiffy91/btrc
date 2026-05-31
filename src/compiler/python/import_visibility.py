"""Per-file import visibility checks for resolved btrc programs."""

from __future__ import annotations

import os
from collections import deque
from dataclasses import fields, is_dataclass
from typing import Any

from . import ast_nodes as ast

_NAMED_DECLS = (
    ast.ClassDecl,
    ast.InterfaceDecl,
    ast.FunctionDecl,
    ast.StructDecl,
    ast.EnumDecl,
    ast.RichEnumDecl,
    ast.TypedefDecl,
)


def _decl_name(decl: Any) -> str:
    if isinstance(decl, ast.TypedefDecl):
        return decl.alias
    return getattr(decl, "name", "")


def _line_file(provenance: list[str], line: int) -> str | None:
    if 1 <= line <= len(provenance):
        return provenance[line - 1]
    return None


def _reachable_files(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen = {start}
    queue = deque(graph.get(start, set()))
    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        queue.extend(graph.get(path, set()) - seen)
    return seen


def _add_ref(refs: list[tuple[str, int, int]], name: str,
             line: int, col: int, generic_params: set[str]) -> None:
    if name and name not in generic_params:
        refs.append((name, line or 1, col or 1))


def _collect_refs(node: Any, refs: list[tuple[str, int, int]],
                  generic_params: set[str]) -> None:
    if node is None:
        return
    if isinstance(node, ast.TypeExpr):
        _add_ref(refs, node.base, node.line, node.col, generic_params)
        for arg in node.generic_args:
            _collect_refs(arg, refs, generic_params)
        _collect_refs(node.array_size, refs, generic_params)
        return
    if isinstance(node, ast.Identifier):
        _add_ref(refs, node.name, node.line, node.col, generic_params)
        return
    if isinstance(node, ast.ClassDecl):
        params = generic_params | set(node.generic_params)
        _add_ref(refs, node.parent or "", node.line, node.col, params)
        for iface in node.interfaces:
            _add_ref(refs, iface, node.line, node.col, params)
        for member in node.members:
            _collect_refs(member, refs, params)
        return
    if isinstance(node, ast.InterfaceDecl):
        params = generic_params | set(node.generic_params)
        _add_ref(refs, node.parent or "", node.line, node.col, params)
        for method in node.methods:
            _collect_refs(method, refs, params)
        return
    if isinstance(node, list):
        for item in node:
            _collect_refs(item, refs, generic_params)
        return
    if not is_dataclass(node):
        return
    for field in fields(node):
        _collect_refs(getattr(node, field.name), refs, generic_params)


def _symbol_files(program: ast.Program, provenance: list[str]) -> dict[str, str]:
    symbols: dict[str, str] = {}
    for decl in program.declarations:
        if not isinstance(decl, _NAMED_DECLS):
            continue
        name = _decl_name(decl)
        source_file = _line_file(provenance, getattr(decl, "line", 0))
        if name and source_file:
            symbols.setdefault(name, os.path.abspath(source_file))
    return symbols


def check_visibility(program: ast.Program, provenance: list[str],
                     graph: dict[str, set[str]]) -> list[tuple[str, int, int]]:
    """Return import-visibility errors as ``(message, line, col)`` tuples."""
    symbol_file = _symbol_files(program, provenance)
    reachable_cache: dict[str, set[str]] = {}
    errors: list[tuple[str, int, int]] = []

    for decl in program.declarations:
        if not isinstance(decl, _NAMED_DECLS):
            continue
        source_file = _line_file(provenance, getattr(decl, "line", 0))
        if source_file is None:
            continue
        source_file = os.path.abspath(source_file)
        reachable = reachable_cache.setdefault(
            source_file, _reachable_files(source_file, graph)
        )
        refs: list[tuple[str, int, int]] = []
        _collect_refs(decl, refs, set(getattr(decl, "generic_params", [])))

        seen_refs: set[tuple[str, int, int]] = set()
        for name, line, col in refs:
            ref_key = (name, line, col)
            if ref_key in seen_refs:
                continue
            seen_refs.add(ref_key)
            target_file = symbol_file.get(name)
            if (target_file is None or target_file == source_file
                    or target_file in reachable):
                continue
            errors.append((
                f"'{name}' is defined in {os.path.basename(target_file)} "
                f"but {os.path.basename(source_file)} does not import it",
                line,
                col,
            ))
    return errors
