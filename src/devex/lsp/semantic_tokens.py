"""Semantic tokens provider for btrc.

Provides rich token classification beyond what TextMate grammars can do:
- Class names highlighted as types everywhere (annotations, extends, new)
- Method calls vs field accesses
- Function calls vs variable references
- Parameter names in declarations
- Enum/struct names as types
"""

from __future__ import annotations

from lsprotocol import types as lsp

from src.compiler.python.ast_nodes import (
    ClassDecl,
    EnumDecl,
    RichEnumDecl,
    StructDecl,
    TypedefDecl,
)
from src.compiler.python.tokens import Token, TokenType
from src.devex.lsp.definition import DefinitionMap
from src.devex.lsp.diagnostics import AnalysisResult, uri_to_path
from src.devex.lsp.utils import navigation_tokens

# LSP Semantic Token Types (order matters — index is the type ID)
TOKEN_TYPES = [
    "namespace",  # 0
    "type",  # 1 - class/struct/enum/typedef names
    "class",  # 2 - class declarations
    "enum",  # 3 - enum declarations
    "interface",  # 4
    "struct",  # 5 - struct declarations
    "typeParameter",  # 6 - generic type parameters
    "parameter",  # 7 - function/method parameters
    "variable",  # 8 - local variables
    "property",  # 9 - class fields
    "enumMember",  # 10 - enum values
    "function",  # 11 - function names
    "method",  # 12 - method names
    "keyword",  # 13
    "comment",  # 14
    "string",  # 15
    "number",  # 16
    "operator",  # 17
]

# LSP Semantic Token Modifiers (bit flags)
TOKEN_MODIFIERS = [
    "declaration",  # 0
    "definition",  # 1
    "readonly",  # 2
    "static",  # 3
    "defaultLibrary",  # 4
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
            bits |= 1 << _MOD_INDEX[m]
    return bits


# ---------------------------------------------------------------------------
# Semantic token collection
# ---------------------------------------------------------------------------


class SemanticTokenCollector:
    """Walks tokens + AST to assign semantic token types."""

    def __init__(self, result: AnalysisResult):
        self.result = result
        self.tokens = navigation_tokens(result.tokens or [])
        self.ast = result.ast
        self.analyzed = result.analyzed
        self.source_positions = result.source_positions
        self.document_path = uri_to_path(result.uri)
        self.class_table = result.analyzed.class_table if result.analyzed else {}
        self.function_table = result.analyzed.function_table if result.analyzed else {}

        # Collect known names
        self.class_names: set[str] = set(self.class_table.keys())
        self.function_names: set[str] = set(self.function_table.keys())
        self.enum_names: set[str] = set()
        self.enum_member_names: set[str] = set()
        self.struct_names: set[str] = set()
        self.typedef_names: set[str] = set()
        self.generic_params: set[str] = set()
        self.variable_names: set[str] = set()

        if self.ast:
            dmap = DefinitionMap.from_ast(self.ast, result.tokens)
            self.variable_names = {var.name for var in dmap.var_defs}
            for decl in self.ast.declarations:
                if isinstance(decl, EnumDecl):
                    self.enum_names.add(decl.name)
                    for value in decl.values:
                        self.enum_member_names.add(value.name)
                elif isinstance(decl, RichEnumDecl):
                    self.enum_names.add(decl.name)
                    for variant in decl.variants:
                        self.enum_member_names.add(variant.name)
                elif isinstance(decl, StructDecl):
                    self.struct_names.add(decl.name)
                elif isinstance(decl, TypedefDecl):
                    self.typedef_names.add(decl.alias)
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
            prev = self.tokens[idx - 1] if idx > 0 else None
            next_tok = self.tokens[idx + 1] if idx + 1 < len(self.tokens) else None

            if prev and prev.value in (".", "->", "?."):
                if next_tok and next_tok.value == "(":
                    self._add(tok, "method")
                else:
                    self._add(tok, "property")
                return

            if name in self.class_names:
                if prev and prev.type == TokenType.CLASS:
                    self._add(tok, "class", "declaration")
                else:
                    self._add(tok, "type")
                return

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

            if name in self.generic_params:
                self._add(tok, "typeParameter")
                return

            if name in self.typedef_names:
                self._add(tok, "type")
                return

            if name in self.enum_member_names:
                self._add(tok, "enumMember")
                return

            if next_tok and next_tok.value == "(":
                if name in self.function_names:
                    self._add(tok, "function")
                    return
                self._add(tok, "function", "defaultLibrary")
                return

            if name in self.variable_names:
                self._add(tok, "variable")
                return

        # Built-in types that are keywords
        if tok.type in (
            TokenType.STRING,
            TokenType.BOOL,
            TokenType.INT,
            TokenType.FLOAT,
            TokenType.DOUBLE,
            TokenType.LONG,
            TokenType.SHORT,
            TokenType.CHAR,
            TokenType.VOID,
            TokenType.UNSIGNED,
        ):
            self._add(tok, "type", "defaultLibrary")

    def _add(self, tok: Token, type_name: str, *modifiers: str):
        """Add a semantic token."""
        type_idx = _TYPE_INDEX.get(type_name)
        if type_idx is None:
            return
        location = self._document_position(tok)
        if location is None:
            return
        line, col = location
        mod_bits = _mod_bits(*modifiers) if modifiers else 0
        self.raw_tokens.append(
            (
                line,  # 1-based
                col,  # 1-based
                len(tok.value),
                type_idx,
                mod_bits,
            )
        )

    def _document_position(self, tok: Token) -> tuple[int, int] | None:
        if not self.source_positions:
            return (tok.line, tok.col)
        if tok.line < 1 or tok.line > len(self.source_positions):
            return None
        source_file, source_line = self.source_positions[tok.line - 1]
        if source_file != self.document_path:
            return None
        return (source_line, tok.col)

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


def get_semantic_tokens(result: AnalysisResult) -> lsp.SemanticTokens | None:
    """Compute semantic tokens for the entire document."""
    if not result.tokens or not result.ast:
        return None

    collector = SemanticTokenCollector(result)
    data = collector.collect()

    if not data:
        return None

    return lsp.SemanticTokens(data=data)
