"""Exact identifier resolution from the analyzer's occurrence table.

The analyzer records, for every simple identifier it resolves, an
``Occurrence`` carrying the symbol's definition site (file/line/col). This
module turns that ``id(node) -> Occurrence`` map into a per-snapshot index
keyed by the identifier's native ``(line, col)`` position, so LSP features can
look a cursor up and get analyzer-truth resolution instead of token-walking
heuristics.

The index covers the simple-``Identifier`` paths the analyzer records (locals,
params, loop/catch vars, function names, top-level class/enum names). Member
accesses (``obj.field``) are NOT keyed here — their field token has no AST
position — so callers keep their existing member heuristics for those.

All positions are native to the active document. Occurrences whose def site
lives in another file (an imported symbol) are kept: go-to-def can still jump
there, but references-grouping stays within the active document.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import Occurrence
from src.compiler.python.ast_nodes import Identifier, TypeExpr
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import active_decls, find_token_at_position, nav_tokens
from src.devex.lsp.var_scopes import collect_lexical_vars, find_visible_var_def

# (file | None, line, col) — the canonical key identifying a definition.
DefSite = tuple


@dataclass
class OccurrenceIndex:
    """Per-snapshot map from identifier position to its resolved occurrence."""

    # (line, col) [1-based] -> Occurrence at that identifier
    by_position: dict[tuple[int, int], Occurrence]
    # def site (file, line, col) -> identifier positions [(line, col), ...]
    by_def_site: dict[DefSite, list[tuple[int, int]]]
    # (line, col) [1-based] -> analyzer-inferred TypeExpr for that identifier
    type_by_position: dict[tuple[int, int], object]
    # Definition site -> file-qualified identifier uses across active + imports.
    resolved_by_def_site: dict[DefSite, list[tuple[str | None, int, int]]]
    # Syntactic type references, which are TypeExpr nodes rather than Identifier.
    type_positions: dict[str, list[tuple[str | None, int, int]]]


def _occ_def_site(occ: Occurrence) -> DefSite:
    return (occ.def_file, occ.def_line, occ.def_col)


def _collect_nodes(
    node,
    file: str | None,
    occ_map: dict[int, Occurrence],
    identifiers: list,
    type_positions: dict,
) -> None:
    """Collect resolved identifiers and syntactic type sites from one unit."""
    if node is None:
        return
    if isinstance(node, Identifier):
        occ = occ_map.get(id(node))
        if occ is not None:
            identifiers.append((file, node, occ))
        return
    if isinstance(node, TypeExpr):
        if node.base and node.line and node.col:
            type_positions.setdefault(node.base, []).append((file, node.line, node.col))
        for argument in node.generic_args:
            _collect_nodes(argument, file, occ_map, identifiers, type_positions)
        _collect_nodes(node.array_size, file, occ_map, identifiers, type_positions)
        return
    if not dataclasses.is_dataclass(node):
        return
    for f in dataclasses.fields(node):
        child = getattr(node, f.name, None)
        if isinstance(child, (list, tuple)):
            for item in child:
                if isinstance(item, (list, tuple)):
                    for sub in item:
                        _collect_nodes(sub, file, occ_map, identifiers, type_positions)
                else:
                    _collect_nodes(item, file, occ_map, identifiers, type_positions)
        else:
            _collect_nodes(child, file, occ_map, identifiers, type_positions)


def build_index(result: AnalysisResult) -> OccurrenceIndex:
    """Build (or return the cached) occurrence index for a snapshot."""
    cached = result._caches.get("occ_index")
    if cached is not None:
        return cached

    occ_map: dict[int, Occurrence] = {}
    node_types: dict = {}
    if result.analyzed is not None:
        occ_map = result.analyzed.occurrences or {}
        node_types = result.analyzed.node_types or {}

    by_position: dict[tuple[int, int], Occurrence] = {}
    by_def_site: dict[DefSite, list[tuple[int, int]]] = {}
    type_by_position: dict[tuple[int, int], object] = {}
    resolved_by_def_site: dict[DefSite, list[tuple[str | None, int, int]]] = {}
    type_positions: dict[str, list[tuple[str | None, int, int]]] = {}

    pairs: list = []
    active = active_decls(result)
    lexical_vars = collect_lexical_vars(active, result.tokens)
    for decl in active:
        _collect_nodes(decl, result.path or None, occ_map, pairs, type_positions)
    for unit in result.units:
        if unit.path == result.path:
            continue
        for decl in unit.decls:
            _collect_nodes(decl, unit.path, occ_map, pairs, type_positions)
    for file, node, occ in pairs:
        if not node.line:
            continue
        pos = (node.line, node.col)
        site = _occ_def_site(occ)
        lexical_type = None
        if file in (None, result.path):
            var_def = find_visible_var_def(
                lexical_vars,
                node.name,
                node.line,
                node.col,
            )
            if var_def is not None:
                lexical_site = (
                    result.path or None,
                    var_def.line,
                    var_def.col,
                )
                if lexical_site != site:
                    occ = Occurrence(
                        kind=var_def.kind,
                        name=node.name,
                        def_file=lexical_site[0],
                        def_line=lexical_site[1],
                        def_col=lexical_site[2],
                    )
                    site = lexical_site
                    lexical_type = getattr(var_def.node, "type", None)
        resolved_by_def_site.setdefault(site, []).append((file, *pos))
        if file in (None, result.path):
            by_position[pos] = occ
            by_def_site.setdefault(site, []).append(pos)
        inferred = lexical_type or node_types.get(id(node))
        if inferred is not None and file in (None, result.path):
            type_by_position[pos] = inferred

    index = OccurrenceIndex(
        by_position=by_position,
        by_def_site=by_def_site,
        type_by_position=type_by_position,
        resolved_by_def_site=resolved_by_def_site,
        type_positions=type_positions,
    )
    result._caches["occ_index"] = index
    return index


def occurrence_at(result: AnalysisResult, position: lsp.Position) -> Occurrence | None:
    """The analyzer-resolved occurrence for the identifier at *position*, or None."""
    if result.analyzed is None or not result.tokens:
        return None
    token = find_token_at_position(nav_tokens(result), position, result.source)
    return occurrence_for_token(result, token)


def occurrence_for_token(
    result: AnalysisResult,
    token,
) -> Occurrence | None:
    """Return an occurrence for an already-resolved active-file token."""
    if token is None or result.analyzed is None:
        return None
    return build_index(result).by_position.get((token.line, token.col))


def type_at(result: AnalysisResult, position: lsp.Position):
    """The analyzer-inferred TypeExpr for the identifier at *position*, or None.

    Only returns a type for identifiers the analyzer resolved (so it reflects a
    real ``var`` inference rather than a syntactic guess). None otherwise.
    """
    if result.analyzed is None or not result.tokens:
        return None
    index = build_index(result)
    if not index.type_by_position:
        return None
    token = find_token_at_position(nav_tokens(result), position, result.source)
    if token is None:
        return None
    return index.type_by_position.get((token.line, token.col))


def references_to(result: AnalysisResult, def_site: DefSite) -> list[tuple[int, int]]:
    """Active-document identifier positions resolving to *def_site*.

    Returns 1-based ``(line, col)`` pairs; empty when the def site has no
    recorded uses (the caller then falls back to its heuristic).
    """
    index = build_index(result)
    return list(index.by_def_site.get(def_site, []))


def resolved_references_to(
    result: AnalysisResult,
    def_site: DefSite,
) -> list[tuple[str | None, int, int]]:
    """File-qualified analyzer-resolved identifiers for one definition site."""
    index = build_index(result)
    refs = index.resolved_by_def_site.get(def_site)
    if refs is not None:
        return list(refs)
    # Older/synthetic ASTs can omit active-file provenance.
    if def_site[0] == result.path:
        return list(index.resolved_by_def_site.get((None, *def_site[1:]), []))
    return []
