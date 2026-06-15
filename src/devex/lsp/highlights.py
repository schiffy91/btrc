"""textDocument/documentHighlight provider for btrc.

Highlights every occurrence of the symbol under the cursor *within the active
document*. It reuses the same scope-aware classification and reference finders
as find-references (references.py), then drops any reference that lives in
another file. Scope-correctness is inherited for free: variable references come
from the analyzer occurrence table grouped by definition site, so a same-named
local in a sibling function is never highlighted.

Each highlight is tagged Write when the identifier is an assignment target or
its own declaration site, Read otherwise (Text when undecidable).
"""

from __future__ import annotations

from lsprotocol import types as lsp

from src.compiler.python.tokens import TokenType
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.reference_finders import (
    find_function_references,
    find_member_references,
    find_name_references,
    find_variable_references,
)
from src.devex.lsp.references import _definition_entry, _locate_symbol
from src.devex.lsp.utils import nav_tokens

# Assignment operators whose left operand is being written.
_ASSIGN_OPS = frozenset({"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="})


def _write_positions(tokens, name: str) -> set[tuple[int, int]]:
    """1-based (line, col) of *name* tokens that are assignment targets.

    A bare identifier immediately followed by an assignment operator (and not
    itself a member access tail like ``obj.x`` — that still counts as a write of
    ``x``) is treated as a write. ``==`` is excluded by the operator set.
    """
    writes: set[tuple[int, int]] = set()
    for i, tok in enumerate(tokens):
        if tok.type != TokenType.IDENT or tok.value != name:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None and nxt.value in _ASSIGN_OPS:
            writes.add((tok.line, tok.col))
    return writes


def get_document_highlights(result: AnalysisResult, position: lsp.Position) -> list[lsp.DocumentHighlight]:
    """All in-scope occurrences of the symbol at *position*, active file only."""
    sym = _locate_symbol(result, position)
    if sym is None:
        return []
    token, tokens, class_table, dmap, kind, class_name, member_name = sym
    name = token.value

    if kind in ("class", "enum", "struct", "typedef"):
        refs = find_name_references(name, result, _definition_entry(kind, class_name, name, dmap), True)
    elif kind == "function":
        refs = find_function_references(name, result, dmap, True)
    elif kind in ("method", "field"):
        refs = find_member_references(class_name, member_name, kind, result, class_table, dmap, True)
    else:
        refs = find_variable_references(name, result, dmap, token, tokens)

    here = result.path or None
    writes = _write_positions(nav_tokens(result), name)

    highlights: list[lsp.DocumentHighlight] = []
    seen: set[tuple[int, int]] = set()
    for file, line, col in refs:
        if (file or None) != here:
            continue  # documentHighlight is scoped to the active document
        if (line, col) in seen:
            continue
        seen.add((line, col))
        hl_kind = lsp.DocumentHighlightKind.Write if (line, col) in writes else lsp.DocumentHighlightKind.Read
        start = lsp.Position(line=max(0, line - 1), character=max(0, col - 1))
        end = lsp.Position(line=start.line, character=start.character + len(name))
        highlights.append(lsp.DocumentHighlight(range=lsp.Range(start=start, end=end), kind=hl_kind))
    return highlights
