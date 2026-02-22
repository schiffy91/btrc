"""Document symbol provider for btrc.

Walks the AST to produce a DocumentSymbol hierarchy for the Outline view.
"""

from __future__ import annotations
from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.ast_nodes import (
    ClassDecl, FunctionDecl, StructDecl, EnumDecl, TypedefDecl,
    FieldDecl, MethodDecl,
)

from devex.lsp.diagnostics import AnalysisResult


def _pos(line: int, col: int) -> lsp.Position:
    """Convert 1-based btrc position to 0-based LSP position."""
    return lsp.Position(line=max(0, line - 1), character=max(0, col - 1))


def _range_from_node(node, source_lines: list[str]) -> lsp.Range:
    """Compute a range for an AST node.

    Uses the node's line/col for start, and tries to find the end
    by scanning for the closing brace of the declaration.
    """
    start = _pos(node.line, node.col)

    # For declarations with bodies, scan for the matching closing brace
    if isinstance(node, (ClassDecl, FunctionDecl, MethodDecl)):
        end_line = _find_closing_brace(source_lines, node.line - 1)
        if end_line is not None:
            end_col = len(source_lines[end_line]) if end_line < len(source_lines) else 0
            return lsp.Range(start=start, end=lsp.Position(line=end_line, character=end_col))

    # Fallback: single line
    line_idx = max(0, node.line - 1)
    end_col = len(source_lines[line_idx]) if line_idx < len(source_lines) else 0
    return lsp.Range(start=start, end=lsp.Position(line=line_idx, character=end_col))


def _find_closing_brace(source_lines: list[str], start_line: int) -> Optional[int]:
    """Find the line of the closing brace matching the first opening brace at or after start_line."""
    depth = 0
    found_open = False
    for i in range(start_line, len(source_lines)):
        for ch in source_lines[i]:
            if ch == '{':
                depth += 1
                found_open = True
            elif ch == '}':
                depth -= 1
                if found_open and depth == 0:
                    return i
    return None


def _selection_range(node) -> lsp.Range:
    """Selection range: just the name, approximated as the node's start position."""
    start = _pos(node.line, node.col)
    # Approximate end as start + length of name
    name = getattr(node, 'name', '')
    end = lsp.Position(line=start.line, character=start.character + len(name))
    return lsp.Range(start=start, end=end)


def _type_repr(type_expr) -> str:
    """Format a TypeExpr as a string."""
    if type_expr is None:
        return "void"
    return repr(type_expr)


def _method_detail(method: MethodDecl) -> str:
    """Build a detail string like 'int method(string name, int age)'."""
    params = ", ".join(f"{_type_repr(p.type)} {p.name}" for p in method.params)
    ret = _type_repr(method.return_type)
    return f"{ret} {method.name}({params})"


def get_document_symbols(result: AnalysisResult) -> list[lsp.DocumentSymbol]:
    """Extract document symbols from the parsed AST."""
    if not result.ast:
        return []

    source_lines = result.source.split('\n')
    symbols: list[lsp.DocumentSymbol] = []

    for decl in result.ast.declarations:
        if isinstance(decl, ClassDecl):
            children: list[lsp.DocumentSymbol] = []

            for member in decl.members:
                if isinstance(member, FieldDecl):
                    children.append(lsp.DocumentSymbol(
                        name=member.name,
                        kind=lsp.SymbolKind.Field,
                        range=_range_from_node(member, source_lines),
                        selection_range=_selection_range(member),
                        detail=_type_repr(member.type),
                    ))
                elif isinstance(member, MethodDecl):
                    # Constructor vs regular method
                    is_constructor = member.name == decl.name
                    kind = lsp.SymbolKind.Constructor if is_constructor else lsp.SymbolKind.Method
                    children.append(lsp.DocumentSymbol(
                        name=member.name,
                        kind=kind,
                        range=_range_from_node(member, source_lines),
                        selection_range=_selection_range(member),
                        detail=_method_detail(member),
                    ))

            # Generic params in detail
            detail = ""
            if decl.generic_params:
                detail = f"<{', '.join(decl.generic_params)}>"
            if decl.parent:
                detail += f" extends {decl.parent}"

            symbols.append(lsp.DocumentSymbol(
                name=decl.name,
                kind=lsp.SymbolKind.Class,
                range=_range_from_node(decl, source_lines),
                selection_range=_selection_range(decl),
                detail=detail.strip(),
                children=children,
            ))

        elif isinstance(decl, FunctionDecl):
            params = ", ".join(f"{_type_repr(p.type)} {p.name}" for p in decl.params)
            ret = _type_repr(decl.return_type)
            symbols.append(lsp.DocumentSymbol(
                name=decl.name,
                kind=lsp.SymbolKind.Function,
                range=_range_from_node(decl, source_lines),
                selection_range=_selection_range(decl),
                detail=f"{ret}({params})",
            ))

        elif isinstance(decl, EnumDecl):
            children = []
            for name, val in decl.values:
                children.append(lsp.DocumentSymbol(
                    name=name,
                    kind=lsp.SymbolKind.EnumMember,
                    range=_range_from_node(decl, source_lines),
                    selection_range=_selection_range(decl),
                    detail=str(val) if val is not None else "",
                ))
            symbols.append(lsp.DocumentSymbol(
                name=decl.name,
                kind=lsp.SymbolKind.Enum,
                range=_range_from_node(decl, source_lines),
                selection_range=_selection_range(decl),
                children=children,
            ))

        elif isinstance(decl, StructDecl):
            symbols.append(lsp.DocumentSymbol(
                name=decl.name,
                kind=lsp.SymbolKind.Struct,
                range=_range_from_node(decl, source_lines),
                selection_range=_selection_range(decl),
            ))

        elif isinstance(decl, TypedefDecl):
            symbols.append(lsp.DocumentSymbol(
                name=decl.alias,
                kind=lsp.SymbolKind.TypeParameter,
                range=_range_from_node(decl, source_lines),
                selection_range=_selection_range(decl),
                detail=_type_repr(decl.original),
            ))

    return symbols
