"""Find-all-references and rename provider for btrc.

Supports finding references for:
- Class names (type annotations, constructor calls, extends, field types)
- Method names (call sites, definition)
- Field names (access sites, definition)
- Function names (call sites, definition)
- Variables (declarations and usages within scope)
"""

from __future__ import annotations

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.definition import DefinitionMap
from src.devex.lsp.diagnostics import AnalysisResult
from src.devex.lsp.utils import (
    document_position_to_resolved,
    find_token_at_position,
    find_token_index,
    resolve_chain_type,
    result_location,
)

# ---------------------------------------------------------------------------
# Reference collection
# ---------------------------------------------------------------------------


def _collect_all_tokens_matching(
    tokens: list[Token],
    name: str,
) -> list[Token]:
    """Find all identifier tokens with the given name."""
    return [tok for tok in tokens if tok.type == TokenType.IDENT and tok.value == name]


def _result_ref_location(
    result: AnalysisResult,
    line: int,
    col: int,
    name_len: int,
) -> lsp.Location:
    return result_location(result, line, col, name_len)


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
    for (cls, mem), (dline, _dcol) in dmap.method_defs.items():
        if mem == name and dline == token.line:
            return ("method", cls, name)
    for (cls, mem), (dline, _dcol) in dmap.field_defs.items():
        if mem == name and dline == token.line:
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


def _find_class_references(
    name: str,
    tokens: list[Token],
    dmap: DefinitionMap,
    include_declaration: bool,
) -> list[tuple[int, int]]:
    """Find all references to a class name."""
    refs = []
    matching = _collect_all_tokens_matching(tokens, name)
    def_loc = dmap.class_defs.get(name)

    for tok in matching:
        loc = (tok.line, tok.col)
        if not include_declaration and def_loc and loc == def_loc:
            continue
        refs.append(loc)
    return refs


def _find_function_references(
    name: str,
    tokens: list[Token],
    dmap: DefinitionMap,
    include_declaration: bool,
) -> list[tuple[int, int]]:
    """Find all references to a function name."""
    refs = []
    matching = _collect_all_tokens_matching(tokens, name)
    def_loc = dmap.function_defs.get(name)

    # The declaration is recorded at the return-type column, not the name
    # token's, so match by line and skip the first name token on that line.
    decl_skipped = False
    for tok in matching:
        loc = (tok.line, tok.col)
        if not include_declaration and def_loc and not decl_skipped and tok.line == def_loc[0]:
            decl_skipped = True
            continue
        refs.append(loc)
    return refs


def _find_member_references(
    class_name: str,
    member_name: str,
    kind: str,  # 'method' or 'field'
    tokens: list[Token],
    result: AnalysisResult,
    class_table: dict[str, ClassInfo],
    dmap: DefinitionMap,
    include_declaration: bool,
) -> list[tuple[int, int]]:
    """Find all references to a class member (method or field)."""
    refs = []

    # Get definition location
    if kind == "method":
        def_loc = dmap.method_defs.get((class_name, member_name))
    else:
        def_loc = dmap.field_defs.get((class_name, member_name))

    # Include definition if requested
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

    # Find all tokens that match member_name preceded by . or -> or ?.
    matching = _collect_all_tokens_matching(tokens, member_name)
    for tok in matching:
        tok_idx = find_token_index(tokens, tok)
        if tok_idx is None or tok_idx < 2:
            continue

        loc = (tok.line, tok.col)
        if not include_declaration and def_loc and loc == def_loc:
            continue

        prev = tokens[tok_idx - 1]
        if prev.value not in (".", "->", "?."):
            continue

        target_class = resolve_chain_type(result, tokens, tok_idx - 2, class_table)

        if target_class in valid_classes:
            refs.append(loc)

    return refs


def _find_variable_references(
    name: str,
    tokens: list[Token],
) -> list[tuple[int, int]]:
    """Find all references to a variable name.

    Simple token-based approach: collect all identifier tokens with the name.
    Filter out those that follow . or -> (those are member accesses, not variable refs).
    """
    refs = []
    matching = _collect_all_tokens_matching(tokens, name)

    for tok in matching:
        tok_idx = find_token_index(tokens, tok)
        if tok_idx is not None and tok_idx >= 1:
            prev = tokens[tok_idx - 1]
            if prev.value in (".", "->", "?."):
                continue  # member access, not a variable reference
        refs.append((tok.line, tok.col))

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

    token = find_token_at_position(
        result.tokens,
        document_position_to_resolved(result, position),
    )
    if token is None or token.type != TokenType.IDENT:
        return []

    class_table = result.analyzed.class_table if result.analyzed else {}
    dmap = DefinitionMap.from_ast(result.ast, result.tokens)
    name = token.value

    kind, class_name, member_name = _classify_symbol(token, result.tokens, result, class_table, dmap)

    if kind == "class":
        locs = _find_class_references(name, result.tokens, dmap, include_declaration)
    elif kind == "function":
        locs = _find_function_references(name, result.tokens, dmap, include_declaration)
    elif kind in ("method", "field"):
        locs = _find_member_references(
            class_name,
            member_name,
            kind,
            result.tokens,
            result,
            class_table,
            dmap,
            include_declaration,
        )
    else:
        locs = _find_variable_references(name, result.tokens)

    return [_result_ref_location(result, line, col, len(name)) for line, col in locs]


def get_rename_edits(
    result: AnalysisResult,
    position: lsp.Position,
    new_name: str,
) -> lsp.WorkspaceEdit | None:
    """Return workspace edits to rename the symbol at position."""
    if not result.tokens or not result.ast:
        return None

    token = find_token_at_position(
        result.tokens,
        document_position_to_resolved(result, position),
    )
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

    token = find_token_at_position(
        result.tokens,
        document_position_to_resolved(result, position),
    )
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
