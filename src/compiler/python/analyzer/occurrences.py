"""Occurrence recording: exact identifier -> definition resolution.

PURELY ADDITIVE and gated behind ``AnalyzerBase.record_occurrences`` (False by
default), so the CLI compiler pays nothing. The LSP flips the flag on to get
analyzer-truth go-to-definition / find-references / hover instead of the old
token-walking heuristics.

When recording is on, every simple ``Identifier`` the analyzer resolves is
written to ``self.occurrences`` (``id(node) -> Occurrence``) with the symbol's
definition site. Lexical scope wins (locals/params/loop/catch vars and in-scope
function names carry an exact ``decl_*`` site, populated at the ``Scope.define``
sites); otherwise top-level class/enum/function names resolve through a lazy
declaration index. Identifiers that resolve to nothing are left out so the LSP
falls back cleanly to its heuristic.
"""

from __future__ import annotations

from ..ast_nodes import (
    ClassDecl,
    EnumDecl,
    FunctionDecl,
    RichEnumDecl,
)
from .core import Occurrence


class OccurrencesMixin:

    def _record_identifier(self, expr) -> None:
        """Record where a simple ``Identifier`` resolves (LSP path only)."""
        sym = self.scope.lookup(expr.name)
        if sym is not None and (sym.decl_file is not None or sym.decl_line or sym.decl_col):
            self.occurrences[id(expr)] = Occurrence(
                kind=sym.kind, name=expr.name,
                def_file=sym.decl_file, def_line=sym.decl_line, def_col=sym.decl_col,
            )
            return
        # Top-level declarations not shadowed by a local symbol.
        decl, kind = self._lookup_top_level(expr.name)
        if decl is not None:
            nl = getattr(decl, "name_line", 0) or getattr(decl, "line", 0)
            nc = getattr(decl, "name_col", 0) or getattr(decl, "col", 0)
            self.occurrences[id(expr)] = Occurrence(
                kind=kind, name=expr.name,
                def_file=getattr(decl, "source_file", None),
                def_line=nl, def_col=nc,
            )

    def _lookup_top_level(self, name):
        """(decl, kind) for a top-level class/function/enum name, or (None, '')."""
        return self._top_level_index().get(name, (None, ""))

    def _top_level_index(self) -> dict:
        """Lazy name -> (decl, kind) index over top-level user declarations.

        Built once per analysis (only when occurrence recording is on). The
        analyzer's class/enum tables hold no decl reference, so the declarations
        list is the source of truth for definition sites.
        """
        cache = getattr(self, "_decl_index_cache", None)
        if cache is not None:
            return cache
        index: dict = {}
        program = getattr(self, "_recording_program", None)
        decls = program.declarations if program is not None else []
        for decl in decls:
            if isinstance(decl, ClassDecl):
                index.setdefault(decl.name, (decl, "class"))
            elif isinstance(decl, FunctionDecl):
                index.setdefault(decl.name, (decl, "function"))
            elif isinstance(decl, EnumDecl):
                index.setdefault(decl.name, (decl, "enum"))
                for v in decl.values:
                    index.setdefault(v.name, (v, "enum"))
            elif isinstance(decl, RichEnumDecl):
                index.setdefault(decl.name, (decl, "enum"))
                for v in decl.variants:
                    index.setdefault(v.name, (v, "enum"))
        self._decl_index_cache = index
        return index
