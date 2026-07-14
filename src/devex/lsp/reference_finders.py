"""Per-kind reference finders for the btrc LSP (see references.py).

Each finder returns ``Ref`` tuples ``(file | None, line, col)`` with positions
native to their file. The active document scans the f-string-expanded
navigation stream; imported units scan their own token streams.
"""

from __future__ import annotations

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.definition import DefinitionMap
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.occurrences import (
    build_index,
    occurrence_for_token,
    references_to,
    resolved_references_to,
)
from src.devex.lsp.utils import active_decls, nav_tokens, resolve_chain_type

Ref = tuple  # (file | None, line, col)


def _token_streams(result: AnalysisResult) -> list[tuple[str | None, list[Token], list]]:
    """(file, tokens, decls) per scannable unit; the active document first.

    The active document scans the navigation stream (f-string expressions
    expanded with true positions). ``decls`` provide the scope context for
    chain resolution in that file.
    """
    streams: list[tuple[str | None, list[Token], list]] = [
        (result.path or None, nav_tokens(result), active_decls(result))
    ]
    for unit in result.units:
        if result.path and unit.path == result.path:
            continue
        if unit.tokens:
            streams.append((unit.path, unit.tokens, unit.decls))
    return streams


def _matching(tokens: list[Token], name: str) -> list[tuple[int, Token]]:
    """(index, token) for identifier tokens spelling *name*."""
    return [(i, tok) for i, tok in enumerate(tokens) if tok.type == TokenType.IDENT and tok.value == name]


def _is_member_access(tokens: list[Token], idx: int) -> bool:
    return idx >= 1 and tokens[idx - 1].value in (".", "->", "?.")


def _same_site(ref: Ref, def_loc: tuple[str | None, int, int] | None) -> bool:
    if def_loc is None:
        return False
    rfile, rline, rcol = ref
    dfile, dline, dcol = def_loc
    return (rline, rcol) == (dline, dcol) and (rfile or None) == (dfile or None)


def find_name_references(
    name: str,
    result: AnalysisResult,
    def_loc: tuple[str | None, int, int] | None,
    include_declaration: bool,
) -> list[Ref]:
    """References to a top-level name (class/enum/struct/typedef) across units."""
    refs = resolved_references_to(result, def_loc) if def_loc else []
    refs.extend(build_index(result).type_positions.get(name, []))
    refs.extend(_inheritance_references(name, result))
    constructor = DefinitionMap.from_result(result).method_defs.get((name, name))
    if constructor is not None:
        refs.append(constructor)
    return _with_declaration(refs, def_loc, include_declaration)


def find_function_references(
    name: str,
    result: AnalysisResult,
    dmap: DefinitionMap,
    include_declaration: bool,
) -> list[Ref]:
    """References to a function name across all units."""
    def_loc = dmap.function_defs.get(name)
    refs = resolved_references_to(result, def_loc) if def_loc else []
    return _with_declaration(refs, def_loc, include_declaration)


def _with_declaration(
    refs: list[Ref],
    definition: Ref | None,
    include_declaration: bool,
) -> list[Ref]:
    unique = list(dict.fromkeys(refs))
    if definition is None:
        return unique
    unique = [ref for ref in unique if not _same_site(ref, definition)]
    return [definition, *unique] if include_declaration else unique


def _inheritance_references(name: str, result: AnalysisResult) -> list[Ref]:
    refs: list[Ref] = []
    for file, tokens, _decls in _token_streams(result):
        for index, token in _matching(tokens, name):
            if _in_inheritance_clause(tokens, index):
                refs.append((file, token.line, token.col))
    return refs


def _in_inheritance_clause(tokens: list[Token], index: int) -> bool:
    for token in reversed(tokens[max(0, index - 32) : index]):
        if token.value in ("extends", "implements"):
            return True
        if token.value in ("{", "}", ";"):
            return False
    return False


def find_member_references(
    class_name: str,
    member_name: str,
    kind: str,  # 'method' or 'field'
    result: AnalysisResult,
    class_table: dict[str, ClassInfo],
    dmap: DefinitionMap,
    include_declaration: bool,
) -> list[Ref]:
    """References to a class member (method or field) across all units."""
    refs: list[Ref] = []

    if kind == "method":
        def_loc = dmap.method_defs.get((class_name, member_name))
    else:
        def_loc = dmap.field_defs.get((class_name, member_name))

    if include_declaration and def_loc:
        refs.append(def_loc)

    # Collect all classes that have this member (including subclasses that inherit it)
    valid_classes = {class_name}
    for cname, cinfo in class_table.items():
        parent = cinfo.parent
        while parent:
            if parent == class_name:
                valid_classes.add(cname)
                break
            parent = class_table[parent].parent if parent in class_table else None

    for file, tokens, decls in _token_streams(result):
        for idx, tok in _matching(tokens, member_name):
            if idx < 2 or not _is_member_access(tokens, idx):
                continue
            ref = (file, tok.line, tok.col)
            if _same_site(ref, def_loc):
                continue  # declaration handled above
            target_class = resolve_chain_type(result, tokens, idx - 2, class_table, decls=decls)
            if target_class in valid_classes:
                refs.append(ref)

    return refs


def find_variable_references(
    name: str,
    result: AnalysisResult,
    dmap: DefinitionMap,
    token: Token,
    tokens: list[Token],
) -> list[Ref]:
    """Scope-aware references to a variable within the active document.

    Primary path: the analyzer's occurrence table. When the cursor resolves to
    a recorded occurrence with a definition site, every identifier whose
    occurrence shares that def site is an exact, scope-correct reference. The
    definition's own name token (which is not an identifier node) is added so
    the declaration is part of the result.

    Fallback (no occurrence — e.g. the analyzer never resolved this node):
    the cursor token anchors a ``VarDef`` and a candidate counts only when it
    resolves to that same definition. Unresolvable cursor yields just itself.
    """
    here = result.path or None

    occ = occurrence_for_token(result, token)
    if occ is not None and (occ.def_line or occ.def_file):
        def_site = (occ.def_file, occ.def_line, occ.def_col)
        positions = references_to(result, def_site)
        refs: list[Ref] = [(here, line, col) for line, col in positions]
        # Include the definition's own name token when it lives in this file.
        if occ.def_file in (None, result.path):
            decl_ref = (here, occ.def_line, occ.def_col)
            if decl_ref not in refs:
                refs.append(decl_ref)
        return refs

    anchor = dmap.find_var_def(name, token.line, token.col)
    if anchor is None:
        return [(here, token.line, token.col)]
    refs = []
    for idx, tok in _matching(tokens, name):
        if _is_member_access(tokens, idx):
            continue
        if dmap.find_var_def(name, tok.line, tok.col) is anchor:
            refs.append((here, tok.line, tok.col))
    return refs
