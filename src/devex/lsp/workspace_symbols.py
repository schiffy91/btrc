"""workspace/symbol provider for btrc.

Fuzzy/substring search over every named declaration the workspace has parsed:
the active document and every imported user file (both live in
``Workspace._file_cache``) plus every stdlib unit. Each unit's decls already
carry true name spans and ``source_file`` provenance, so a hit maps straight to
a ``Location`` at the symbol's name token.

The query matches case-insensitively as a substring first, then as a
subsequence (``vec`` matches ``Vector``), so an empty query lists everything.
"""

from __future__ import annotations

import os

from lsprotocol import types as lsp

from src.compiler.python.ast_nodes import (
    ClassDecl,
    EnumDecl,
    FunctionDecl,
    InterfaceDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
)
from src.devex.lsp.text_coordinates import protocol_range
from src.devex.lsp.units import FileUnit
from src.devex.lsp.workspace import Workspace

# AST decl type -> (LSP SymbolKind, name-attribute)
_KIND_BY_DECL: list[tuple[type, lsp.SymbolKind, str]] = [
    (ClassDecl, lsp.SymbolKind.Class, "name"),
    (InterfaceDecl, lsp.SymbolKind.Interface, "name"),
    (StructDecl, lsp.SymbolKind.Struct, "name"),
    (EnumDecl, lsp.SymbolKind.Enum, "name"),
    (RichEnumDecl, lsp.SymbolKind.Enum, "name"),
    (FunctionDecl, lsp.SymbolKind.Function, "name"),
    (TypedefDecl, lsp.SymbolKind.TypeParameter, "alias"),
]


def _match_rank(query: str, name: str) -> int | None:
    """Match quality rank (lower = better), or None when *name* does not match.

    0 = exact, 1 = prefix, 2 = substring, 3 = subsequence (``vec``->``Vector``).
    An empty query matches everything at rank 0 (the client wants the full list).
    """
    if not query:
        return 0
    q = query.lower()
    n = name.lower()
    if n == q:
        return 0
    if n.startswith(q):
        return 1
    if q in n:
        return 2
    it = iter(n)
    return 3 if all(ch in it for ch in q) else None


def _classify(decl) -> tuple[str, lsp.SymbolKind] | None:
    """(name, kind) for a named top-level decl, or None when *decl* is unnamed."""
    for decl_type, kind, attr in _KIND_BY_DECL:
        if isinstance(decl, decl_type):
            name = getattr(decl, attr, None)
            return (name, kind) if name else None
    return None


def _name_position(node) -> tuple[int, int]:
    """1-based (line, col) of *node*'s name token (parser-populated span)."""
    nl = getattr(node, "name_line", 0)
    if nl:
        return (nl, getattr(node, "name_col", 0))
    return (getattr(node, "line", 0), getattr(node, "col", 0))


def _symbol_for(
    decl,
    unit: FileUnit,
    name: str,
    kind: lsp.SymbolKind,
):
    line, col = _name_position(decl)
    if line == 0:
        return None
    source = unit.source
    if not source:
        try:
            with open(unit.path, encoding="utf-8") as source_file:
                source = source_file.read()
        except OSError:
            source = ""
    uri = _path_to_uri(unit.path)
    return lsp.WorkspaceSymbol(
        name=name,
        kind=kind,
        location=lsp.Location(uri=uri, range=protocol_range(source, line, col, len(name))),
    )


def _path_to_uri(path: str) -> str:
    from pathlib import Path

    # absolute(), not resolve(): keep document identity stable (/tmp vs
    # /private/tmp) — the same convention result_location uses.
    return Path(path).absolute().as_uri()


def _units(workspace: Workspace) -> list[FileUnit]:
    """Every parsed unit: cached user files first, then stdlib."""
    units = workspace.cached_units()
    units.extend(workspace.stdlib_units())
    return units


def _preferred_declarations(declarations: list) -> list:
    """Use a struct definition when a file also contains forward declarations."""
    structs = {}
    for declaration in declarations:
        if not isinstance(declaration, StructDecl):
            continue
        previous = structs.get(declaration.name)
        if previous is None or (previous.is_forward and not declaration.is_forward):
            structs[declaration.name] = declaration
    return [
        declaration
        for declaration in declarations
        if not isinstance(declaration, StructDecl) or structs.get(declaration.name) is declaration
    ]


def get_workspace_symbols(workspace: Workspace, query: str, limit: int = 500) -> list[lsp.WorkspaceSymbol]:
    """All named decls across the workspace whose name matches *query*.

    De-duplicated by (path, name, line) so a file present in both the active
    cache and the import cache is not listed twice. Capped at *limit* results.
    """
    ranked: list[tuple[int, lsp.WorkspaceSymbol]] = []
    seen: set[tuple[str, str, int]] = set()
    for unit in _units(workspace):
        path = unit.path
        for decl in _preferred_declarations(unit.decls):
            classified = _classify(decl)
            if classified is None:
                continue
            name, kind = classified
            rank = _match_rank(query, name)
            if rank is None:
                continue
            line, _col = _name_position(decl)
            key = (os.path.abspath(path), name, line)
            if key in seen:
                continue
            seen.add(key)
            sym = _symbol_for(decl, unit, name, kind)
            if sym is not None:
                ranked.append((rank, sym))
    # Stable sort by match quality (substring/prefix before subsequence);
    # original discovery order breaks ties within a rank.
    ranked.sort(key=lambda item: item[0])
    return [sym for _rank, sym in ranked[:limit]]
