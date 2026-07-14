"""Stable facade for shared btrc LSP utilities.

Implementation lives in cohesive position, scope, variable, and type-resolution
modules.  Existing feature and extension imports intentionally continue to use
this module as their compatibility boundary.
"""

from src.devex.lsp.position_utils import (
    active_decls,
    document_position_to_resolved,
    find_token_at_position,
    find_token_index,
    get_text_before_cursor,
    nav_tokens,
    navigation_tokens,
    result_location,
    type_repr,
)
from src.devex.lsp.scope_utils import (
    body_range,
    find_closing_brace_line,
    find_enclosing_class,
    find_enclosing_class_from_source,
    find_matching_brace_line,
)
from src.devex.lsp.type_resolution import (
    ChainResolution,
    resolve_chain,
    resolve_chain_type,
    resolve_member_type,
)
from src.devex.lsp.variable_resolution import BUILTIN_TYPES, resolve_variable_type

__all__ = [
    "BUILTIN_TYPES",
    "ChainResolution",
    "active_decls",
    "body_range",
    "document_position_to_resolved",
    "find_closing_brace_line",
    "find_enclosing_class",
    "find_enclosing_class_from_source",
    "find_matching_brace_line",
    "find_token_at_position",
    "find_token_index",
    "get_text_before_cursor",
    "nav_tokens",
    "navigation_tokens",
    "resolve_chain",
    "resolve_chain_type",
    "resolve_member_type",
    "resolve_variable_type",
    "result_location",
    "type_repr",
]
