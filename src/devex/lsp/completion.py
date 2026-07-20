"""Code completion provider for btrc."""

import re

from lsprotocol import types as lsp

from src.compiler.python.analyzer.core import ClassInfo
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.builtins import STDLIB_STATIC_METHODS
from src.devex.lsp.completion_catalog import general_completions
from src.devex.lsp.completion_items import (
    class_member_items,
    members_for_type,
    static_completions,
)
from src.devex.lsp.diagnostics import AnalysisResult, line_changed_since_snapshot
from src.devex.lsp.text_coordinates import source_position
from src.devex.lsp.utils import (
    active_decls,
    find_enclosing_class,
    find_enclosing_class_from_source,
    get_text_before_cursor,
    nav_tokens,
    resolve_chain,
    resolve_member_type,
    resolve_variable_type,
)

_ACCESS_VALUES = frozenset({".", "?.", "->"})
_MEMBER_ACCESS_RE = re.compile(
    r"([A-Za-z_]\w*(?:\s*(?:\?\.|->|\.)\s*[A-Za-z_]\w*)*)"
    r"\s*(?:\?\.|->|\.)\s*(?:[A-Za-z_]\w*)?\s*$"
)


def get_completions(
    result: AnalysisResult,
    position: lsp.Position,
) -> list[lsp.CompletionItem]:
    """Compute completion items at a document position."""
    position = source_position(result.source, position)
    class_table = result.analyzed.class_table if result.analyzed else {}
    token_items = _dot_completions_from_tokens(result, position, class_table)
    if token_items is not None:
        return token_items

    match = _MEMBER_ACCESS_RE.search(get_text_before_cursor(result.source, position))
    if match:
        return _dot_completions(result, match.group(1), position, class_table)
    return general_completions(class_table)


def _dot_completions_from_tokens(
    result: AnalysisResult,
    position: lsp.Position,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem] | None:
    if not result.tokens or line_changed_since_snapshot(result, position.line):
        return None
    tokens = nav_tokens(result)
    access_idx = _access_token_before_cursor(tokens, position)
    if access_idx is None or access_idx < 1:
        return None

    owner_idx = access_idx - 1
    resolved = resolve_chain(result, tokens, owner_idx, class_table)
    if resolved is not None:
        if resolved.direct_type_reference:
            return static_completions(resolved.type_name, class_table)
        return members_for_type(resolved.type_name, class_table)

    owner = tokens[owner_idx]
    if _is_simple_receiver(tokens, owner_idx) and owner.value in STDLIB_STATIC_METHODS:
        return static_completions(owner.value, class_table)
    return []


def _access_token_before_cursor(tokens: list[Token], position: lsp.Position) -> int | None:
    """Find access punctuation immediately before an optional partial member."""
    line = position.line + 1
    caret_col = position.character + 1

    for index, token in enumerate(tokens):
        if token.line != line or token.type not in (TokenType.IDENT, TokenType.SELF):
            continue
        token_end = token.col + len(token.value)
        if token.col <= caret_col <= token_end and index > 0:
            if tokens[index - 1].value in _ACCESS_VALUES:
                return index - 1

    latest: tuple[int, int] | None = None
    for index, token in enumerate(tokens):
        if token.line != line or token.value not in _ACCESS_VALUES:
            continue
        token_end = token.col + len(token.value)
        if token_end <= caret_col and (latest is None or token_end > latest[1]):
            latest = (index, token_end)
    if latest is None:
        return None

    access_idx, access_end = latest
    for token in tokens[access_idx + 1 :]:
        if token.line != line:
            continue
        if token.col < caret_col and token.col >= access_end:
            return None
    return access_idx


def _is_simple_receiver(tokens: list[Token], index: int) -> bool:
    if index < 0 or index >= len(tokens) or tokens[index].value == ")":
        return False
    return index < 1 or tokens[index - 1].value not in _ACCESS_VALUES


def _dot_completions(
    result: AnalysisResult,
    receiver: str,
    position: lsp.Position,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    """Resolve a live-text receiver during the analysis debounce window."""
    parts = re.split(r"\s*(?:\?\.|->|\.)\s*", receiver.strip())
    head, hops = parts[0], parts[1:]

    current_type = _resolve_var_type(result, head, position)
    receiver_is_type = False
    if not hops and current_type is None:
        if head in class_table or head in STDLIB_STATIC_METHODS:
            return static_completions(head, class_table)

    if current_type is None and head in class_table:
        current_type = head
        receiver_is_type = True
    for hop in hops:
        if current_type is None:
            return []
        current_type = resolve_member_type(
            current_type,
            hop,
            class_table,
            static_access=receiver_is_type,
        )
        receiver_is_type = False
    return members_for_type(current_type, class_table) if current_type else []


def _resolve_var_type(
    result: AnalysisResult,
    var_name: str,
    position: lsp.Position,
) -> str | None:
    if not result.ast:
        return None
    line = position.line + 1
    if var_name == "self":
        decls = active_decls(result)
        return find_enclosing_class_from_source(
            decls,
            result.source,
            position.line,
        ) or find_enclosing_class(decls, line)
    class_table = result.analyzed.class_table if result.analyzed else {}
    return resolve_variable_type(
        var_name,
        active_decls(result),
        class_table,
        line,
        result=result,
        cursor_col=position.character + 1,
    )


# Compatibility wrappers for former module-local item builders.
def _class_member_items(class_name: str, info: ClassInfo) -> list[lsp.CompletionItem]:
    return class_member_items(class_name, {class_name: info}, static_only=False)


def _static_completions(
    class_name: str,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    return static_completions(class_name, class_table)


def _members_for_type(
    type_base: str,
    class_table: dict[str, ClassInfo],
) -> list[lsp.CompletionItem]:
    return members_for_type(type_base, class_table)
