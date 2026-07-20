"""Find-all-references and rename provider for btrc.

References are found by scanning the token streams of the active document and
every imported unit (positions native per file; finders live in
reference_finders.py). The active stream is the f-string-expanded navigation
stream, so identifiers interpolated in f-strings are real reference sites.
Variable references stay within the active document and are scope-aware: a
candidate token counts only when it resolves to the SAME definition
(DefinitionMap.find_var_def identity) as the cursor token.

Rename refuses (returns None) when the cursor variable cannot be resolved to
a definition, and when the symbol's definition lives in the stdlib —
references may list stdlib definition sites, but rename must never edit
installed stdlib files on disk.
"""

from __future__ import annotations

import os
import re

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.frontend import _get_stdlib_dir
from src.compiler.python.tokens import KEYWORDS, Token, TokenType
from src.devex.lsp.definition import DefinitionMap
from src.devex.lsp.diagnostics import AnalysisResult, analysis_is_current
from src.devex.lsp.reference_finders import (
    find_function_references,
    find_member_references,
    find_name_references,
    find_variable_references,
)
from src.devex.lsp.utils import (
    find_token_at_position,
    find_token_index,
    nav_tokens,
    resolve_chain_type,
    result_location,
)

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
    'class', 'enum', 'struct', 'typedef', 'function', 'method', 'field',
    'variable'.
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
    here = (result.path or None, token.line, token.col)
    for (cls, mem), (dfile, dline, dcol) in dmap.method_defs.items():
        if mem == name and (dfile or None, dline, dcol) == here:
            return ("method", cls, name)
    for (cls, mem), (dfile, dline, dcol) in dmap.field_defs.items():
        if mem == name and (dfile or None, dline, dcol) == here:
            return ("field", cls, name)

    if name in dmap.class_defs:
        return ("class", name, None)
    if name in dmap.function_defs:
        return ("function", None, name)
    if name in dmap.enum_defs:
        return ("enum", None, name)
    if name in dmap.struct_defs:
        return ("struct", None, name)
    if name in dmap.typedef_defs:
        return ("typedef", None, name)

    # Default to variable
    return ("variable", None, name)


def _definition_entry(
    kind: str, class_name: str | None, name: str, dmap: DefinitionMap
) -> tuple[str | None, int, int] | None:
    """The (file, line, col) definition entry for a classified symbol."""
    if kind == "class":
        return dmap.class_defs.get(name)
    if kind == "enum":
        return dmap.enum_defs.get(name)
    if kind == "struct":
        return dmap.struct_defs.get(name)
    if kind == "typedef":
        return dmap.typedef_defs.get(name)
    if kind == "function":
        return dmap.function_defs.get(name)
    if kind == "method" and class_name:
        return dmap.method_defs.get((class_name, name))
    if kind == "field" and class_name:
        return dmap.field_defs.get((class_name, name))
    return None


def _is_stdlib_file(path: str | None) -> bool:
    """True when *path* lives under the installed stdlib directory."""
    if not path:
        return False
    stdlib_dir = os.path.abspath(_get_stdlib_dir())
    return os.path.abspath(path).startswith(stdlib_dir + os.sep)


def _locate_symbol(result: AnalysisResult, position: lsp.Position):
    """Resolve and classify the identifier at *position*, or None."""
    if not result.tokens or not result.ast:
        return None
    tokens = nav_tokens(result)
    token = find_token_at_position(tokens, position, result.source)
    if token is None or token.type != TokenType.IDENT:
        return None
    class_table = result.analyzed.class_table if result.analyzed else {}
    dmap = DefinitionMap.from_result(result)
    kind, class_name, member_name = _classify_symbol(token, tokens, result, class_table, dmap)
    return token, tokens, class_table, dmap, kind, class_name, member_name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_references(
    result: AnalysisResult,
    position: lsp.Position,
    include_declaration: bool = True,
) -> list[lsp.Location]:
    """Return all reference locations for the symbol at position."""
    if not analysis_is_current(result):
        return []
    sym = _locate_symbol(result, position)
    if sym is None:
        return []
    token, tokens, class_table, dmap, kind, class_name, member_name = sym
    name = token.value

    if kind in ("class", "enum", "struct", "typedef"):
        refs = find_name_references(name, result, _definition_entry(kind, class_name, name, dmap), include_declaration)
    elif kind == "function":
        refs = find_function_references(name, result, dmap, include_declaration)
    elif kind in ("method", "field"):
        refs = find_member_references(
            class_name,
            member_name,
            kind,
            result,
            class_table,
            dmap,
            include_declaration,
        )
    else:
        refs = find_variable_references(name, result, dmap, token, tokens)

    return [result_location(result, line, col, len(name), file=file) for file, line, col in refs]


def _rename_blocked(result: AnalysisResult, position: lsp.Position) -> bool:
    """True when rename at *position* must be refused.

    Refusals: unresolvable variables (no visible definition to anchor a
    scope-correct rename) and symbols whose definition lives in the stdlib
    (rename would edit installed stdlib files on disk).
    """
    sym = _locate_symbol(result, position)
    if sym is None:
        return True
    token, _tokens, _class_table, dmap, kind, class_name, _member_name = sym
    if kind == "variable":
        return dmap.find_var_def(token.value, token.line, token.col) is None
    entry = _definition_entry(kind, class_name, token.value, dmap)
    return _is_stdlib_file(entry[0] if entry else None)


def get_rename_edits(
    result: AnalysisResult,
    position: lsp.Position,
    new_name: str,
) -> lsp.WorkspaceEdit | None:
    """Return workspace edits to rename the symbol at position."""
    if not result.tokens or not result.ast or not analysis_is_current(result) or not _valid_rename_identifier(new_name):
        return None

    token = find_token_at_position(nav_tokens(result), position, result.source)
    if token is None or token.type != TokenType.IDENT:
        return None
    if _rename_blocked(result, position):
        return None

    locations = get_references(result, position, include_declaration=True)
    if not locations:
        return None

    changes: dict[str, list[lsp.TextEdit]] = {}
    for loc in locations:
        edit_range = loc.range
        changes.setdefault(loc.uri, []).append(lsp.TextEdit(range=edit_range, new_text=new_name))

    return lsp.WorkspaceEdit(changes=changes)


_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _valid_rename_identifier(name: str) -> bool:
    """Apply the grammar's ASCII identifier shape and keyword reservation."""
    return isinstance(name, str) and bool(_IDENTIFIER_PATTERN.fullmatch(name)) and name not in KEYWORDS


def prepare_rename(
    result: AnalysisResult,
    position: lsp.Position,
) -> lsp.Range | None:
    """Check if rename is possible at position and return the symbol range."""
    if not result.tokens or not analysis_is_current(result):
        return None

    tokens = nav_tokens(result) if result.ast else result.tokens
    token = find_token_at_position(tokens, position, result.source)
    if token is None or token.type != TokenType.IDENT:
        return None
    # With an AST available, apply the same refusals as get_rename_edits so
    # the editor never opens a rename box that the rename request will reject.
    if result.ast and _rename_blocked(result, position):
        return None

    return result_location(result, token.line, token.col, len(token.value)).range
