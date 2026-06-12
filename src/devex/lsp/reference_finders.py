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
    return [
        (i, tok)
        for i, tok in enumerate(tokens)
        if tok.type == TokenType.IDENT and tok.value == name
    ]


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
    refs: list[Ref] = []
    for file, tokens, _decls in _token_streams(result):
        for _i, tok in _matching(tokens, name):
            ref = (file, tok.line, tok.col)
            if not include_declaration and _same_site(ref, def_loc):
                continue
            refs.append(ref)
    return refs


def find_function_references(
    name: str,
    result: AnalysisResult,
    dmap: DefinitionMap,
    include_declaration: bool,
) -> list[Ref]:
    """References to a function name across all units."""
    refs: list[Ref] = []
    def_loc = dmap.function_defs.get(name)
    for file, tokens, _decls in _token_streams(result):
        # The declaration is recorded at the name token; older parsers recorded
        # the return-type column, so also match by line in the defining file.
        decl_skipped = False
        for _i, tok in _matching(tokens, name):
            ref = (file, tok.line, tok.col)
            if (
                not include_declaration
                and def_loc
                and not decl_skipped
                and (file or None) == (def_loc[0] or None)
                and tok.line == def_loc[1]
            ):
                decl_skipped = True
                continue
            refs.append(ref)
    return refs


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
            target_class = resolve_chain_type(
                result, tokens, idx - 2, class_table, decls=decls
            )
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

    The cursor token anchors a definition; a candidate token is a reference
    iff it resolves to that same definition. Unresolvable cursor (no visible
    definition) yields just the cursor token.
    """
    here = result.path or None
    anchor = dmap.find_var_def(name, token.line, token.col)
    if anchor is None:
        return [(here, token.line, token.col)]
    refs: list[Ref] = []
    for idx, tok in _matching(tokens, name):
        if _is_member_access(tokens, idx):
            continue
        if dmap.find_var_def(name, tok.line, tok.col) is anchor:
            refs.append((here, tok.line, tok.col))
    return refs
