"""Document and workspace symbol publication."""

from __future__ import annotations

import os

from lsprotocol import types as lsp

from src.compiler.python.syntax.ast.generated import (
    ClassDecl,
    EnumDecl,
    EnumValue,
    FieldDecl,
    FieldDef,
    FunctionDecl,
    InterfaceDecl,
    MethodDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
)
from src.devex.lsp.analysis.document import DocumentAnalysis, DocumentText
from src.devex.lsp.analysis.resolution import LexicalScopeIndex, SemanticResolver
from src.devex.lsp.workspace.units import FileUnit
from src.devex.lsp.workspace.workspace import Workspace

_KIND_BY_DECL: tuple[tuple[type, lsp.SymbolKind, str], ...] = (
    (ClassDecl, lsp.SymbolKind.Class, "name"),
    (InterfaceDecl, lsp.SymbolKind.Interface, "name"),
    (StructDecl, lsp.SymbolKind.Struct, "name"),
    (EnumDecl, lsp.SymbolKind.Enum, "name"),
    (RichEnumDecl, lsp.SymbolKind.Enum, "name"),
    (FunctionDecl, lsp.SymbolKind.Function, "name"),
    (TypedefDecl, lsp.SymbolKind.TypeParameter, "alias"),
)


class SymbolProvider:
    """Document and workspace symbol publication."""

    def __init__(self, resolver: SemanticResolver) -> None:
        self.resolver = resolver

    def _pos(self, source: str, line: int, col: int) -> lsp.Position:
        """Convert 1-based btrc position to 0-based LSP position."""
        return DocumentText(source).protocol_position(line, col)

    def _document_position(self, result: DocumentAnalysis, line: int, col: int) -> tuple[int, int] | None:
        return (line, col)

    def _range_from_node(self, result: DocumentAnalysis, node, source_lines: list[str]) -> lsp.Range | None:
        """Compute a range for an AST node."""
        mapped = self._document_position(result, node.line, node.col)
        if mapped is None:
            return None
        line, col = mapped
        start = self._pos(result.source, line, col)
        if isinstance(node, (ClassDecl, FunctionDecl, MethodDecl)):
            end_line = LexicalScopeIndex.find_closing_brace_line(source_lines, line - 1)
            if end_line is not None:
                end_col = DocumentText.utf16_length(source_lines[end_line]) if end_line < len(source_lines) else 0
                return lsp.Range(start=start, end=lsp.Position(line=end_line, character=end_col))
        line_idx = max(0, line - 1)
        end_col = DocumentText.utf16_length(source_lines[line_idx]) if line_idx < len(source_lines) else 0
        return lsp.Range(start=start, end=lsp.Position(line=line_idx, character=end_col))

    def _name_line_col(self, node) -> tuple[int, int]:
        """1-based position of *node*'s NAME token.

        Named decls/members carry ``name_line``/``name_col`` pointing at their name
        (populated by the parser); nodes whose position already *is* the name
        (EnumValue, FieldDef, RichEnumVariant) carry only ``line``/``col``. Read the
        name span when present, otherwise fall back to the node's own position.
        """
        nl = getattr(node, "name_line", 0)
        if nl:
            return (nl, getattr(node, "name_col", 0))
        return (getattr(node, "line", 0), getattr(node, "col", 0))

    def _selection_range(self, result: DocumentAnalysis, node) -> lsp.Range | None:
        """Selection range covering the symbol's NAME token.

        Reads the node's real name span so the outline selects the name, not the
        leading keyword/type.
        """
        line, col = self._name_line_col(node)
        if line == 0:
            return None
        start = self._pos(result.source, line, col)
        name = getattr(node, "name", "") or getattr(node, "alias", "")
        end = lsp.Position(line=start.line, character=start.character + len(name))
        return lsp.Range(start=start, end=end)

    def _method_detail(self, method: MethodDecl) -> str:
        """Build a detail string like 'int method(string name, int age)'."""
        params = ", ".join(f"{self.resolver.type_repr(p.type)} {p.name}" for p in method.params)
        ret = self.resolver.type_repr(method.return_type)
        return f"{ret} {method.name}({params})"

    def get_document_symbols(self, result: DocumentAnalysis) -> list[lsp.DocumentSymbol]:
        """Extract document symbols from the parsed AST."""
        if not result.ast or not result.positions_are_stable():
            return []
        source_lines = result.source.split("\n")
        symbols: list[lsp.DocumentSymbol] = []
        for decl in self.resolver.active_decls(result):
            if isinstance(decl, ClassDecl):
                decl_range = self._range_from_node(result, decl, source_lines)
                decl_selection = self._selection_range(result, decl)
                if decl_range is None or decl_selection is None:
                    continue
                children: list[lsp.DocumentSymbol] = []
                for member in decl.members:
                    if isinstance(member, FieldDecl):
                        member_range = self._range_from_node(result, member, source_lines)
                        member_selection = self._selection_range(result, member)
                        if member_range is None or member_selection is None:
                            continue
                        children.append(
                            lsp.DocumentSymbol(
                                name=member.name,
                                kind=lsp.SymbolKind.Field,
                                range=member_range,
                                selection_range=member_selection,
                                detail=self.resolver.type_repr(member.type),
                            )
                        )
                    elif isinstance(member, MethodDecl):
                        member_range = self._range_from_node(result, member, source_lines)
                        member_selection = self._selection_range(result, member)
                        if member_range is None or member_selection is None:
                            continue
                        kind = lsp.SymbolKind.Constructor if member.is_constructor else lsp.SymbolKind.Method
                        children.append(
                            lsp.DocumentSymbol(
                                name=member.name,
                                kind=kind,
                                range=member_range,
                                selection_range=member_selection,
                                detail=self._method_detail(member),
                            )
                        )
                detail = ""
                if decl.generic_params:
                    detail = f"<{', '.join(decl.generic_params)}>"
                if decl.parent:
                    detail += f" extends {decl.parent}"
                symbols.append(
                    lsp.DocumentSymbol(
                        name=decl.name,
                        kind=lsp.SymbolKind.Class,
                        range=decl_range,
                        selection_range=decl_selection,
                        detail=detail.strip(),
                        children=children,
                    )
                )
            elif isinstance(decl, FunctionDecl):
                decl_range = self._range_from_node(result, decl, source_lines)
                decl_selection = self._selection_range(result, decl)
                if decl_range is None or decl_selection is None:
                    continue
                params = ", ".join(f"{self.resolver.type_repr(p.type)} {p.name}" for p in decl.params)
                ret = self.resolver.type_repr(decl.return_type)
                symbols.append(
                    lsp.DocumentSymbol(
                        name=decl.name,
                        kind=lsp.SymbolKind.Function,
                        range=decl_range,
                        selection_range=decl_selection,
                        detail=f"{ret}({params})",
                    )
                )
            elif isinstance(decl, EnumDecl):
                decl_range = self._range_from_node(result, decl, source_lines)
                decl_selection = self._selection_range(result, decl)
                if decl_range is None or decl_selection is None:
                    continue
                children = []
                for ev in decl.values:
                    if isinstance(ev, EnumValue):
                        ev_selection = self._selection_range(result, ev)
                        ev_range = ev_selection or decl_range
                        children.append(
                            lsp.DocumentSymbol(
                                name=ev.name,
                                kind=lsp.SymbolKind.EnumMember,
                                range=ev_range,
                                selection_range=ev_selection or decl_selection,
                                detail=str(ev.value) if ev.value is not None else "",
                            )
                        )
                symbols.append(
                    lsp.DocumentSymbol(
                        name=decl.name,
                        kind=lsp.SymbolKind.Enum,
                        range=decl_range,
                        selection_range=decl_selection,
                        children=children,
                    )
                )
            elif isinstance(decl, StructDecl):
                decl_range = self._range_from_node(result, decl, source_lines)
                decl_selection = self._selection_range(result, decl)
                if decl_range is None or decl_selection is None:
                    continue
                field_children: list[lsp.DocumentSymbol] = []
                for fd in decl.fields:
                    if not isinstance(fd, FieldDef):
                        continue
                    fd_selection = self._selection_range(result, fd)
                    if fd_selection is None:
                        continue
                    field_children.append(
                        lsp.DocumentSymbol(
                            name=fd.name,
                            kind=lsp.SymbolKind.Field,
                            range=fd_selection,
                            selection_range=fd_selection,
                            detail=self.resolver.type_repr(fd.type),
                        )
                    )
                symbols.append(
                    lsp.DocumentSymbol(
                        name=decl.name,
                        kind=lsp.SymbolKind.Struct,
                        range=decl_range,
                        selection_range=decl_selection,
                        children=field_children,
                    )
                )
            elif isinstance(decl, TypedefDecl):
                decl_range = self._range_from_node(result, decl, source_lines)
                decl_selection = self._selection_range(result, decl)
                if decl_range is None or decl_selection is None:
                    continue
                symbols.append(
                    lsp.DocumentSymbol(
                        name=decl.alias,
                        kind=lsp.SymbolKind.TypeParameter,
                        range=decl_range,
                        selection_range=decl_selection,
                        detail=self.resolver.type_repr(decl.original),
                    )
                )
        return symbols

    def _match_rank(self, query: str, name: str) -> int | None:
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

    def _classify(self, decl) -> tuple[str, lsp.SymbolKind] | None:
        """(name, kind) for a named top-level decl, or None when *decl* is unnamed."""
        for decl_type, kind, attr in _KIND_BY_DECL:
            if isinstance(decl, decl_type):
                name = getattr(decl, attr, None)
                return (name, kind) if name else None
        return None

    def _name_position(self, node) -> tuple[int, int]:
        """1-based (line, col) of *node*'s name token (parser-populated span)."""
        nl = getattr(node, "name_line", 0)
        if nl:
            return (nl, getattr(node, "name_col", 0))
        return (getattr(node, "line", 0), getattr(node, "col", 0))

    def _symbol_for(self, decl, unit: FileUnit, name: str, kind: lsp.SymbolKind):
        line, col = self._name_position(decl)
        if line == 0:
            return None
        source = unit.source
        if not source:
            try:
                with open(unit.path, encoding="utf-8") as source_file:
                    source = source_file.read()
            except OSError:
                source = ""
        uri = self._path_to_uri(unit.path)
        return lsp.WorkspaceSymbol(
            name=name,
            kind=kind,
            location=lsp.Location(uri=uri, range=DocumentText(source).protocol_range(line, col, len(name))),
        )

    def _path_to_uri(self, path: str) -> str:
        from pathlib import Path

        return Path(path).absolute().as_uri()

    def _units(self, workspace: Workspace) -> list[FileUnit]:
        """Every parsed unit: cached user files first, then stdlib."""
        units = workspace.cached_units()
        units.extend(workspace.stdlib_units())
        return units

    def _preferred_declarations(self, declarations: list) -> list:
        """Use a struct definition when a file also contains forward declarations."""
        structs = {}
        for declaration in declarations:
            if not isinstance(declaration, StructDecl):
                continue
            previous = structs.get(declaration.name)
            if previous is None or (previous.is_forward and (not declaration.is_forward)):
                structs[declaration.name] = declaration
        return [
            declaration
            for declaration in declarations
            if not isinstance(declaration, StructDecl) or structs.get(declaration.name) is declaration
        ]

    def get_workspace_symbols(self, workspace: Workspace, query: str, limit: int = 500) -> list[lsp.WorkspaceSymbol]:
        """All named decls across the workspace whose name matches *query*.

        De-duplicated by (path, name, line) so a file present in both the active
        cache and the import cache is not listed twice. Capped at *limit* results.
        """
        ranked: list[tuple[int, lsp.WorkspaceSymbol]] = []
        seen: set[tuple[str, str, int]] = set()
        for unit in self._units(workspace):
            path = unit.path
            for decl in self._preferred_declarations(unit.decls):
                classified = self._classify(decl)
                if classified is None:
                    continue
                name, kind = classified
                rank = self._match_rank(query, name)
                if rank is None:
                    continue
                line, _col = self._name_position(decl)
                key = (os.path.abspath(path), name, line)
                if key in seen:
                    continue
                seen.add(key)
                sym = self._symbol_for(decl, unit, name, kind)
                if sym is not None:
                    ranked.append((rank, sym))
        ranked.sort(key=lambda item: item[0])
        return [sym for _rank, sym in ranked[:limit]]
