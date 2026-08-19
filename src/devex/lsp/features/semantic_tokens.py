"""Semantic-token classification and protocol encoding."""

from __future__ import annotations

from types import MappingProxyType

from lsprotocol import types as lsp

from src.compiler.python.syntax.ast.generated import ClassDecl, EnumDecl, RichEnumDecl, StructDecl, TypedefDecl
from src.compiler.python.syntax.tokens import Token, TokenKind
from src.devex.lsp.analysis.document import DocumentAnalysis, DocumentText
from src.devex.lsp.analysis.resolution import SemanticResolver
from src.devex.lsp.features.navigation import NavigationProvider

TOKEN_TYPES = (
    "namespace",
    "type",
    "class",
    "enum",
    "interface",
    "struct",
    "typeParameter",
    "parameter",
    "variable",
    "property",
    "enumMember",
    "function",
    "method",
    "keyword",
    "comment",
    "string",
    "number",
    "operator",
)
TOKEN_MODIFIERS = ("declaration", "definition", "readonly", "static", "defaultLibrary")
_TYPE_INDEX = MappingProxyType({name: i for i, name in enumerate(TOKEN_TYPES)})
_MOD_INDEX = MappingProxyType({name: i for i, name in enumerate(TOKEN_MODIFIERS)})
LEGEND = lsp.SemanticTokensLegend(token_types=TOKEN_TYPES, token_modifiers=TOKEN_MODIFIERS)


class SemanticTokenCollector:
    """Walks tokens + AST to assign semantic token types."""

    def __init__(
        self,
        result: DocumentAnalysis,
        resolver: SemanticResolver,
        navigation: NavigationProvider,
    ):
        self.result = result
        self.tokens = resolver.nav_tokens(result)
        self.ast = result.ast
        self.analyzed = result.analyzed
        self.class_table = result.analyzed.class_table if result.analyzed else {}
        self.function_table = result.analyzed.function_table if result.analyzed else {}
        self.class_names: set[str] = set(self.class_table.keys())
        self.function_names: set[str] = set(self.function_table.keys())
        self.enum_names: set[str] = set()
        self.enum_member_names: set[str] = set()
        self.struct_names: set[str] = set()
        self.typedef_names: set[str] = set()
        self.generic_params: set[str] = set()
        self.variable_names: set[str] = set()
        if self.ast:
            dmap = navigation.definition_map(result)
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
        self.raw_tokens: list[tuple[int, int, int, int, int]] = []

    def collect(self) -> list[int]:
        """Walk all tokens and classify them. Returns LSP-encoded token data."""
        for i, tok in enumerate(self.tokens):
            if tok.type == TokenKind.EOF:
                continue
            self._classify_token(tok, i)
        return self._encode()

    def _classify_token(self, tok: Token, idx: int):
        """Assign semantic type to a token based on context."""
        name = tok.value
        if tok.type == TokenKind.IDENT:
            prev = self.tokens[idx - 1] if idx > 0 else None
            next_tok = self.tokens[idx + 1] if idx + 1 < len(self.tokens) else None
            if prev and prev.value in (".", "->", "?."):
                if next_tok and next_tok.value == "(":
                    self._add(tok, "method")
                else:
                    self._add(tok, "property")
                return
            if name in self.class_names:
                if prev and prev.type == TokenKind.CLASS:
                    self._add(tok, "class", "declaration")
                else:
                    self._add(tok, "type")
                return
            if name in self.enum_names:
                if prev and prev.type == TokenKind.ENUM:
                    self._add(tok, "enum", "declaration")
                else:
                    self._add(tok, "type")
                return
            if name in self.struct_names:
                if prev and prev.type == TokenKind.STRUCT:
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
        if tok.type in (
            TokenKind.STRING,
            TokenKind.BOOL,
            TokenKind.INT,
            TokenKind.FLOAT,
            TokenKind.DOUBLE,
            TokenKind.LONG,
            TokenKind.SHORT,
            TokenKind.CHAR,
            TokenKind.VOID,
            TokenKind.UNSIGNED,
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
        source_line = DocumentText(self.result.snapshot_source or self.result.source).line(line - 1)
        lsp_col = DocumentText.codepoint_to_utf16(source_line, col - 1)
        token_length = DocumentText.utf16_length(tok.value)
        mod_bits = self._modifier_bits(*modifiers) if modifiers else 0
        self.raw_tokens.append((line, lsp_col, token_length, type_idx, mod_bits))

    @staticmethod
    def _modifier_bits(*modifiers: str) -> int:
        bits = 0
        for modifier in modifiers:
            if modifier in _MOD_INDEX:
                bits |= 1 << _MOD_INDEX[modifier]
        return bits

    def _document_position(self, tok: Token) -> tuple[int, int] | None:
        return (tok.line, tok.col)

    def _encode(self) -> list[int]:
        """Encode raw tokens into LSP delta-encoded format.

        LSP requires tokens sorted by position, then encoded as deltas:
        [deltaLine, deltaStartChar, length, tokenType, tokenModifiers]
        """
        self.raw_tokens.sort(key=lambda t: (t[0], t[1]))
        data: list[int] = []
        prev_line = 0
        prev_col = 0
        for line, col, length, type_idx, mod_bits in self.raw_tokens:
            lsp_line = line - 1
            lsp_col = col
            delta_line = lsp_line - prev_line
            if delta_line == 0:
                delta_col = lsp_col - prev_col
            else:
                delta_col = lsp_col
            data.extend([delta_line, delta_col, length, type_idx, mod_bits])
            prev_line = lsp_line
            prev_col = lsp_col
        return data


class SemanticTokenProvider:
    """Semantic-token classification and protocol encoding."""

    def __init__(self, resolver: SemanticResolver, navigation: NavigationProvider):
        self._resolver = resolver
        self._navigation = navigation

    def get_semantic_tokens(self, result: DocumentAnalysis) -> lsp.SemanticTokens | None:
        """Compute semantic tokens for the document (cached per snapshot)."""
        if not result.tokens or not result.ast or not result.positions_are_stable():
            return None
        data = result._caches.get("semantic_tokens")
        if data is None:
            data = SemanticTokenCollector(result, self._resolver, self._navigation).collect()
            result._caches["semantic_tokens"] = data
        if not data:
            return None
        return lsp.SemanticTokens(data=data)
