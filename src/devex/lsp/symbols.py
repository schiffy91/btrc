"""Document symbol provider for btrc.

Walks the AST to produce a DocumentSymbol hierarchy for the Outline view.
"""

from __future__ import annotations

from lsprotocol import types as lsp

from src.compiler.python.ast_nodes import (
    ClassDecl,
    EnumDecl,
    EnumValue,
    FieldDecl,
    FunctionDecl,
    MethodDecl,
    StructDecl,
    TypedefDecl,
)
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import find_closing_brace_line, type_repr


def _pos(line: int, col: int) -> lsp.Position:
    """Convert 1-based btrc position to 0-based LSP position."""
    return lsp.Position(line=max(0, line - 1), character=max(0, col - 1))


def _range_from_node(node, source_lines: list[str]) -> lsp.Range:
    """Compute a range for an AST node."""
    start = _pos(node.line, node.col)

    if isinstance(node, (ClassDecl, FunctionDecl, MethodDecl)):
        end_line = find_closing_brace_line(source_lines, node.line - 1)
        if end_line is not None:
            end_col = len(source_lines[end_line]) if end_line < len(source_lines) else 0
            return lsp.Range(
                start=start, end=lsp.Position(line=end_line, character=end_col)
            )

    line_idx = max(0, node.line - 1)
    end_col = len(source_lines[line_idx]) if line_idx < len(source_lines) else 0
    return lsp.Range(start=start, end=lsp.Position(line=line_idx, character=end_col))


def _selection_range(node) -> lsp.Range:
    """Selection range: just the name, approximated as the node's start position."""
    start = _pos(node.line, node.col)
    # Approximate end as start + length of name
    name = getattr(node, "name", "")
    end = lsp.Position(line=start.line, character=start.character + len(name))
    return lsp.Range(start=start, end=end)


def _method_detail(method: MethodDecl) -> str:
    """Build a detail string like 'int method(string name, int age)'."""
    params = ", ".join(f"{type_repr(p.type)} {p.name}" for p in method.params)
    ret = type_repr(method.return_type)
    return f"{ret} {method.name}({params})"


def get_document_symbols(result: AnalysisResult) -> list[lsp.DocumentSymbol]:
    """Extract document symbols from the parsed AST."""
    if not result.ast:
        return []

    source_lines = result.source.split("\n")
    symbols: list[lsp.DocumentSymbol] = []

    for decl in result.ast.declarations:
        if isinstance(decl, ClassDecl):
            children: list[lsp.DocumentSymbol] = []

            for member in decl.members:
                if isinstance(member, FieldDecl):
                    children.append(
                        lsp.DocumentSymbol(
                            name=member.name,
                            kind=lsp.SymbolKind.Field,
                            range=_range_from_node(member, source_lines),
                            selection_range=_selection_range(member),
                            detail=type_repr(member.type),
                        )
                    )
                elif isinstance(member, MethodDecl):
                    # Constructor vs regular method
                    is_constructor = member.name == decl.name
                    kind = (
                        lsp.SymbolKind.Constructor
                        if is_constructor
                        else lsp.SymbolKind.Method
                    )
                    children.append(
                        lsp.DocumentSymbol(
                            name=member.name,
                            kind=kind,
                            range=_range_from_node(member, source_lines),
                            selection_range=_selection_range(member),
                            detail=_method_detail(member),
                        )
                    )

            # Generic params in detail
            detail = ""
            if decl.generic_params:
                detail = f"<{', '.join(decl.generic_params)}>"
            if decl.parent:
                detail += f" extends {decl.parent}"

            symbols.append(
                lsp.DocumentSymbol(
                    name=decl.name,
                    kind=lsp.SymbolKind.Class,
                    range=_range_from_node(decl, source_lines),
                    selection_range=_selection_range(decl),
                    detail=detail.strip(),
                    children=children,
                )
            )

        elif isinstance(decl, FunctionDecl):
            params = ", ".join(f"{type_repr(p.type)} {p.name}" for p in decl.params)
            ret = type_repr(decl.return_type)
            symbols.append(
                lsp.DocumentSymbol(
                    name=decl.name,
                    kind=lsp.SymbolKind.Function,
                    range=_range_from_node(decl, source_lines),
                    selection_range=_selection_range(decl),
                    detail=f"{ret}({params})",
                )
            )

        elif isinstance(decl, EnumDecl):
            children = []
            for ev in decl.values:
                if isinstance(ev, EnumValue):
                    children.append(
                        lsp.DocumentSymbol(
                            name=ev.name,
                            kind=lsp.SymbolKind.EnumMember,
                            range=_range_from_node(decl, source_lines),
                            selection_range=_selection_range(decl),
                            detail=str(ev.value) if ev.value is not None else "",
                        )
                    )
            symbols.append(
                lsp.DocumentSymbol(
                    name=decl.name,
                    kind=lsp.SymbolKind.Enum,
                    range=_range_from_node(decl, source_lines),
                    selection_range=_selection_range(decl),
                    children=children,
                )
            )

        elif isinstance(decl, StructDecl):
            symbols.append(
                lsp.DocumentSymbol(
                    name=decl.name,
                    kind=lsp.SymbolKind.Struct,
                    range=_range_from_node(decl, source_lines),
                    selection_range=_selection_range(decl),
                )
            )

        elif isinstance(decl, TypedefDecl):
            symbols.append(
                lsp.DocumentSymbol(
                    name=decl.alias,
                    kind=lsp.SymbolKind.TypeParameter,
                    range=_range_from_node(decl, source_lines),
                    selection_range=_selection_range(decl),
                    detail=type_repr(decl.original),
                )
            )

    return symbols
