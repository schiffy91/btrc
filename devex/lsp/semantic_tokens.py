"""Semantic tokens provider for btrc.

Provides rich token classification beyond what TextMate grammars can do:
- Class names highlighted as types everywhere (annotations, extends, new)
- Method calls vs field accesses
- Function calls vs variable references
- Parameter names in declarations
- Enum/struct names as types
"""

from __future__ import annotations
from typing import Optional

from lsprotocol import types as lsp

from src.compiler.python.tokens import Token, TokenType
from src.compiler.python.ast_nodes import (
    ClassDecl, EnumDecl, StructDecl,
)

from devex.lsp.diagnostics import AnalysisResult


# LSP Semantic Token Types (order matters — index is the type ID)
TOKEN_TYPES = [
    "namespace",      # 0
    "type",           # 1 - class/struct/enum/typedef names
    "class",          # 2 - class declarations
    "enum",           # 3 - enum declarations
    "interface",      # 4
    "struct",         # 5 - struct declarations
    "typeParameter",  # 6 - generic type parameters
    "parameter",      # 7 - function/method parameters
    "variable",       # 8 - local variables
    "property",       # 9 - class fields
    "enumMember",     # 10 - enum values
    "function",       # 11 - function names
    "method",         # 12 - method names
    "keyword",        # 13
    "comment",        # 14
    "string",         # 15
    "number",         # 16
    "operator",       # 17
]

# LSP Semantic Token Modifiers (bit flags)
TOKEN_MODIFIERS = [
    "declaration",    # 0
    "definition",     # 1
    "readonly",       # 2
    "static",         # 3
    "defaultLibrary", # 4
]

# Map token type name to index
_TYPE_INDEX = {name: i for i, name in enumerate(TOKEN_TYPES)}
_MOD_INDEX = {name: i for i, name in enumerate(TOKEN_MODIFIERS)}

LEGEND = lsp.SemanticTokensLegend(
    token_types=TOKEN_TYPES,
    token_modifiers=TOKEN_MODIFIERS,
)


def _mod_bits(*modifiers: str) -> int:
    """Compute modifier bitmask from modifier names."""
    bits = 0
    for m in modifiers:
        if m in _MOD_INDEX:
            bits |= (1 << _MOD_INDEX[m])
    return bits


# ---------------------------------------------------------------------------
# Semantic token collection
# ---------------------------------------------------------------------------

class SemanticTokenCollector:
    """Walks tokens + AST to assign semantic token types."""

    def __init__(self, result: AnalysisResult):
        self.tokens = result.tokens or []
        self.ast = result.ast
        self.analyzed = result.analyzed
        self.class_table = result.analyzed.class_table if result.analyzed else {}
        self.function_table = result.analyzed.function_table if result.analyzed else {}

        # Collect known names
        self.class_names: set[str] = set(self.class_table.keys())
        self.function_names: set[str] = set(self.function_table.keys())
        self.enum_names: set[str] = set()
        self.struct_names: set[str] = set()
        self.generic_params: set[str] = set()
        self.param_names: set[str] = set()  # current scope params

        # Collect enum/struct names from AST
        if self.ast:
            for decl in self.ast.declarations:
                if isinstance(decl, EnumDecl):
                    self.enum_names.add(decl.name)
                elif isinstance(decl, StructDecl):
                    self.struct_names.add(decl.name)
                elif isinstance(decl, ClassDecl):
                    for gp in decl.generic_params:
                        self.generic_params.add(gp)

        # Raw semantic tokens: [(line, col, length, type_index, modifier_bits)]
        self.raw_tokens: list[tuple[int, int, int, int, int]] = []

    def collect(self) -> list[int]:
        """Walk all tokens and classify them. Returns LSP-encoded token data."""
        for i, tok in enumerate(self.tokens):
            if tok.type == TokenType.EOF:
                continue
            self._classify_token(tok, i)

        return self._encode()

    def _classify_token(self, tok: Token, idx: int):
        """Assign semantic type to a token based on context."""
        name = tok.value

        if tok.type == TokenType.IDENT:
            # Check context: what comes before and after this token?
            prev = self.tokens[idx - 1] if idx > 0 else None
            next_tok = self.tokens[idx + 1] if idx + 1 < len(self.tokens) else None

            # Member access: preceded by . or -> or ?.
            if prev and prev.value in ('.', '->', '?.'):
                # Is it a method call? (followed by '(')
                if next_tok and next_tok.value == '(':
                    self._add(tok, "method")
                else:
                    self._add(tok, "property")
                return

            # Constructor call: preceded by 'new'
            if prev and prev.type == TokenType.NEW and name in self.class_names:
                self._add(tok, "type")
                return

            # Class name used as type (in declarations, extends, generics)
            if name in self.class_names:
                # Check if this is the class declaration itself
                if prev and prev.type == TokenType.CLASS:
                    self._add(tok, "class", "declaration")
                else:
                    self._add(tok, "type")
                return

            # Enum name
            if name in self.enum_names:
                if prev and prev.type == TokenType.ENUM:
                    self._add(tok, "enum", "declaration")
                else:
                    self._add(tok, "type")
                return

            # Struct name
            if name in self.struct_names:
                if prev and prev.type == TokenType.STRUCT:
                    self._add(tok, "struct", "declaration")
                else:
                    self._add(tok, "type")
                return

            # Generic type parameter (T, K, V, etc.)
            if name in self.generic_params:
                self._add(tok, "typeParameter")
                return

            # Function call: followed by '('
            if next_tok and next_tok.value == '(':
                if name in self.function_names:
                    self._add(tok, "function")
                    return
                # Could be a constructor call for a class
                if name in self.class_names:
                    self._add(tok, "type")
                    return
                # Unknown function call (built-in like print, range, etc.)
                self._add(tok, "function", "defaultLibrary")
                return

            # Function declaration: return_type IDENT (
            # Already handled by TextMate grammar mostly, skip

        # Built-in types that are keywords
        if tok.type in (TokenType.LIST, TokenType.MAP):
            self._add(tok, "type", "defaultLibrary")

    def _add(self, tok: Token, type_name: str, *modifiers: str):
        """Add a semantic token."""
        type_idx = _TYPE_INDEX.get(type_name)
        if type_idx is None:
            return
        mod_bits = _mod_bits(*modifiers) if modifiers else 0
        self.raw_tokens.append((
            tok.line,  # 1-based
            tok.col,   # 1-based
            len(tok.value),
            type_idx,
            mod_bits,
        ))

    def _encode(self) -> list[int]:
        """Encode raw tokens into LSP delta-encoded format.

        LSP requires tokens sorted by position, then encoded as deltas:
        [deltaLine, deltaStartChar, length, tokenType, tokenModifiers]
        """
        # Sort by line, then column
        self.raw_tokens.sort(key=lambda t: (t[0], t[1]))

        data: list[int] = []
        prev_line = 0
        prev_col = 0

        for line, col, length, type_idx, mod_bits in self.raw_tokens:
            # Convert from 1-based to 0-based
            lsp_line = line - 1
            lsp_col = col - 1

            delta_line = lsp_line - prev_line
            if delta_line == 0:
                delta_col = lsp_col - prev_col
            else:
                delta_col = lsp_col

            data.extend([delta_line, delta_col, length, type_idx, mod_bits])
            prev_line = lsp_line
            prev_col = lsp_col

        return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_semantic_tokens(result: AnalysisResult) -> Optional[lsp.SemanticTokens]:
    """Compute semantic tokens for the entire document."""
    if not result.tokens or not result.ast:
        return None

    collector = SemanticTokenCollector(result)
    data = collector.collect()

    if not data:
        return None

    return lsp.SemanticTokens(data=data)
