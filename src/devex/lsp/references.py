"""Find-all-references and rename provider for btrc.

References are found by scanning the token streams of the active document and
every imported unit (positions native per file). Variable references stay
within the active document — locals don't cross files.
"""

from __future__ import annotations

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.definition import DefinitionMap
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import (
    active_decls,
    find_token_at_position,
    find_token_index,
    resolve_chain_type,
    result_location,
)

# ---------------------------------------------------------------------------
# Token streams
# ---------------------------------------------------------------------------


def _token_streams(result: AnalysisResult) -> list[tuple[str | None, list[Token], list]]:
    """(file, tokens, decls) per scannable unit; the active document first.

    ``decls`` provide the scope context for chain resolution in that file.
    """
    streams: list[tuple[str | None, list[Token], list]] = [
        (result.path or None, result.tokens or [], active_decls(result))
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


Ref = tuple  # (file | None, line, col)


def _same_site(ref: Ref, def_loc: tuple[str | None, int, int] | None) -> bool:
    if def_loc is None:
        return False
    rfile, rline, rcol = ref
    dfile, dline, dcol = def_loc
    return (rline, rcol) == (dline, dcol) and (rfile or None) == (dfile or None)


# ---------------------------------------------------------------------------
# Symbol kind detection at cursor
# ---------------------------------------------------------------------------


def _classify_symbol(
    token: Token,
    tokens: list[Token],
    result: AnalysisResult,
    class_table: dict[str, ClassInfo],
    dmap: DefinitionMap,
) -> tuple[str, str | None, str | None]:
    """Classify the symbol under cursor.

    Returns (kind, class_name, member_name) where kind is one of:
    'class', 'function', 'method', 'field', 'variable'
    """
    name = token.value

    token_idx = find_token_index(tokens, token)
    if token_idx is not None and token_idx >= 2:
        prev = tokens[token_idx - 1]
        if prev.value in (".", "->", "?."):
            target_class = resolve_chain_type(result, tokens, token_idx - 2, class_table)
            if target_class:
                cinfo = class_table.get(target_class)
                if cinfo:
                    if name in cinfo.methods:
                        return ("method", target_class, name)
                    if name in cinfo.fields:
                        return ("field", target_class, name)
                    parent = cinfo.parent
                    while parent and parent in class_table:
                        pc = class_table[parent]
                        if name in pc.methods:
                            return ("method", parent, name)
                        if name in pc.fields:
                            return ("field", parent, name)
                        parent = pc.parent

    # Cursor on a member *declaration* (the field/method name in a class body):
    # classify it as that member so find-references/rename span all accesses,
    # not just same-named locals. Member decls live on their own line.
    here = (result.path or None, token.line)
    for (cls, mem), (dfile, dline, _dcol) in dmap.method_defs.items():
        if mem == name and (dfile or None, dline) == here:
            return ("method", cls, name)
    for (cls, mem), (dfile, dline, _dcol) in dmap.field_defs.items():
        if mem == name and (dfile or None, dline) == here:
            return ("field", cls, name)

    # Check class name
    if name in dmap.class_defs:
        return ("class", name, None)

    # Check function name
    if name in dmap.function_defs:
        return ("function", None, name)

    # Default to variable
    return ("variable", None, name)


# ---------------------------------------------------------------------------
# Reference finders per symbol kind
# ---------------------------------------------------------------------------


def _find_name_references(
    name: str,
    result: AnalysisResult,
    def_loc: tuple[str | None, int, int] | None,
    include_declaration: bool,
) -> list[Ref]:
    """References to a top-level name (class/function/enum) across all units."""
    refs: list[Ref] = []
    for file, tokens, _decls in _token_streams(result):
        for _i, tok in _matching(tokens, name):
            ref = (file, tok.line, tok.col)
            if not include_declaration and _same_site(ref, def_loc):
                continue
            refs.append(ref)
    return refs


def _find_function_references(
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


def _find_member_references(
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


def _find_variable_references(name: str, result: AnalysisResult) -> list[Ref]:
    """References to a variable name within the active document.

    Simple token-based approach: collect identifier tokens with the name,
    excluding member accesses (those follow . / -> / ?.).
    """
    refs: list[Ref] = []
    tokens = result.tokens or []
    for idx, tok in _matching(tokens, name):
        if _is_member_access(tokens, idx):
            continue
        refs.append((result.path or None, tok.line, tok.col))
    return refs


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_references(
    result: AnalysisResult,
    position: lsp.Position,
    include_declaration: bool = True,
) -> list[lsp.Location]:
    """Return all reference locations for the symbol at position."""
    if not result.tokens or not result.ast:
        return []

    token = find_token_at_position(result.tokens, position)
    if token is None or token.type != TokenType.IDENT:
        return []

    class_table = result.analyzed.class_table if result.analyzed else {}
    dmap = DefinitionMap.from_result(result)
    name = token.value

    kind, class_name, member_name = _classify_symbol(
        token, result.tokens, result, class_table, dmap
    )

    if kind == "class":
        refs = _find_name_references(
            name, result, dmap.class_defs.get(name), include_declaration
        )
    elif kind == "function":
        refs = _find_function_references(name, result, dmap, include_declaration)
    elif kind in ("method", "field"):
        refs = _find_member_references(
            class_name,
            member_name,
            kind,
            result,
            class_table,
            dmap,
            include_declaration,
        )
    else:
        refs = _find_variable_references(name, result)

    return [
        result_location(result, line, col, len(name), file=file)
        for file, line, col in refs
    ]


def get_rename_edits(
    result: AnalysisResult,
    position: lsp.Position,
    new_name: str,
) -> lsp.WorkspaceEdit | None:
    """Return workspace edits to rename the symbol at position."""
    if not result.tokens or not result.ast:
        return None

    token = find_token_at_position(result.tokens, position)
    if token is None or token.type != TokenType.IDENT:
        return None

    locations = get_references(result, position, include_declaration=True)
    if not locations:
        return None

    old_name = token.value
    changes: dict[str, list[lsp.TextEdit]] = {}
    for loc in locations:
        edit_range = lsp.Range(
            start=loc.range.start,
            end=lsp.Position(
                line=loc.range.start.line,
                character=loc.range.start.character + len(old_name),
            ),
        )
        changes.setdefault(loc.uri, []).append(lsp.TextEdit(range=edit_range, new_text=new_name))

    return lsp.WorkspaceEdit(changes=changes)


def prepare_rename(
    result: AnalysisResult,
    position: lsp.Position,
) -> lsp.Range | None:
    """Check if rename is possible at position and return the symbol range."""
    if not result.tokens:
        return None

    token = find_token_at_position(result.tokens, position)
    if token is None or token.type != TokenType.IDENT:
        return None

    # Don't allow renaming keywords or built-in types
    keywords = {
        "if",
        "else",
        "while",
        "for",
        "in",
        "return",
        "class",
        "public",
        "private",
        "void",
        "int",
        "float",
        "double",
        "string",
        "bool",
        "char",
        "true",
        "false",
        "null",
        "new",
        "delete",
        "self",
        "break",
        "continue",
        "switch",
        "case",
        "default",
        "try",
        "catch",
        "throw",
        "do",
        "List",
        "Map",
        "Set",
    }
    if token.value in keywords:
        return None

    return result_location(result, token.line, token.col, len(token.value)).range
