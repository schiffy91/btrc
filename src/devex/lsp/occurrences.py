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
from src.compiler.python.ast_nodes import Identifier
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import active_decls, find_token_at_position, nav_tokens

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


def _occ_def_site(occ: Occurrence) -> DefSite:
    return (occ.def_file, occ.def_line, occ.def_col)


def _collect_identifiers(node, occ_map: dict[int, Occurrence], out: list) -> None:
    """Append (Identifier, Occurrence) for every recorded identifier in *node*."""
    if node is None:
        return
    if isinstance(node, Identifier):
        occ = occ_map.get(id(node))
        if occ is not None:
            out.append((node, occ))
        return
    if not dataclasses.is_dataclass(node):
        return
    for f in dataclasses.fields(node):
        child = getattr(node, f.name, None)
        if isinstance(child, (list, tuple)):
            for item in child:
                if isinstance(item, (list, tuple)):
                    for sub in item:
                        _collect_identifiers(sub, occ_map, out)
                else:
                    _collect_identifiers(item, occ_map, out)
        else:
            _collect_identifiers(child, occ_map, out)


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

    if occ_map:
        pairs: list = []
        for decl in active_decls(result):
            _collect_identifiers(decl, occ_map, pairs)
        for node, occ in pairs:
            if not node.line:
                continue
            pos = (node.line, node.col)
            by_position[pos] = occ
            by_def_site.setdefault(_occ_def_site(occ), []).append(pos)
            inferred = node_types.get(id(node))
            if inferred is not None:
                type_by_position[pos] = inferred

    index = OccurrenceIndex(
        by_position=by_position,
        by_def_site=by_def_site,
        type_by_position=type_by_position,
    )
    result._caches["occ_index"] = index
    return index


def occurrence_at(result: AnalysisResult, position: lsp.Position) -> Occurrence | None:
    """The analyzer-resolved occurrence for the identifier at *position*, or None."""
    if result.analyzed is None or not result.tokens:
        return None
    index = build_index(result)
    if not index.by_position:
        return None
    token = find_token_at_position(nav_tokens(result), position)
    if token is None:
        return None
    return index.by_position.get((token.line, token.col))


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
    token = find_token_at_position(nav_tokens(result), position)
    if token is None:
        return None
    return index.type_by_position.get((token.line, token.col))


def references_to(
    result: AnalysisResult, def_site: DefSite
) -> list[tuple[int, int]]:
    """Active-document identifier positions resolving to *def_site*.

    Returns 1-based ``(line, col)`` pairs; empty when the def site has no
    recorded uses (the caller then falls back to its heuristic).
    """
    index = build_index(result)
    return list(index.by_def_site.get(def_site, []))
