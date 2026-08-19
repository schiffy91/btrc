"""Shared helpers for btrc LSP tests.

Tests drive retained feature-provider objects over real source through the
same compiler front-end the server uses, then assert concrete positions.
"""

from lsprotocol import types as lsp

from src.devex.lsp.analysis.document import DocumentAnalysis, DocumentAnalyzer, DocumentText
from src.devex.lsp.analysis.resolution import SemanticResolver
from src.devex.lsp.catalog.builtins import BuiltinCatalog
from src.devex.lsp.features.code_actions import CodeActionProvider
from src.devex.lsp.features.completion import CompletionProvider
from src.devex.lsp.features.hover import HoverProvider
from src.devex.lsp.features.navigation import NavigationProvider
from src.devex.lsp.features.semantic_tokens import TOKEN_TYPES, SemanticTokenProvider
from src.devex.lsp.features.signature_help import SignatureHelpProvider
from src.devex.lsp.features.symbols import SymbolProvider
from src.devex.lsp.workspace.workspace import Workspace

WORKSPACE = Workspace()
ANALYZER = DocumentAnalyzer(WORKSPACE)
CATALOG = BuiltinCatalog()
RESOLVER = SemanticResolver(CATALOG)
NAVIGATION = NavigationProvider(RESOLVER, WORKSPACE)
COMPLETION = CompletionProvider(CATALOG, RESOLVER)
SIGNATURE_HELP = SignatureHelpProvider(CATALOG, RESOLVER)
HOVER = HoverProvider(CATALOG, RESOLVER, NAVIGATION)
SEMANTIC_TOKENS = SemanticTokenProvider(RESOLVER, NAVIGATION)
SYMBOLS = SymbolProvider(RESOLVER)
CODE_ACTIONS = CodeActionProvider(CATALOG, RESOLVER, NAVIGATION, WORKSPACE)

# A small well-formed program covering the symbol kinds features must handle.
SAMPLE = """\
enum Color { RED, GREEN, BLUE };

int add(int a, int b) { return a + b; }

class Point {
    public int x;
    public Point(int x) { self.x = x; }
    public int getX() { return self.x; }
    public int doubled() { return add(self.x, self.x); }
}

int main() {
    Point p = Point(5);
    int v = p.getX();
    Color c = RED;
    return v;
}
"""


def analyze(source: str, uri: str = "file:///t.btrc"):
    """Run the compiler pipeline and return one document snapshot."""
    return ANALYZER.analyze(uri, source)


def compute_diagnostics(uri: str, source: str) -> DocumentAnalysis:
    return ANALYZER.analyze(uri, source)


def get_completions(result, position):
    return COMPLETION.get_completions(result, position)


def get_signature_help(result, position):
    return SIGNATURE_HELP.get_signature_help(result, position)


def get_hover_info(result, position):
    return HOVER.get_hover_info(result, position)


def get_definition(result, position):
    return NAVIGATION.get_definition(result, position)


def get_references(result, position, include_declaration=True):
    return NAVIGATION.get_references(result, position, include_declaration)


def get_rename_edits(result, position, new_name):
    return NAVIGATION.get_rename_edits(result, position, new_name)


def prepare_rename(result, position):
    return NAVIGATION.prepare_rename(result, position)


def get_document_highlights(result, position):
    return NAVIGATION.get_document_highlights(result, position)


def get_semantic_tokens(result):
    return SEMANTIC_TOKENS.get_semantic_tokens(result)


def get_document_symbols(result):
    return SYMBOLS.get_document_symbols(result)


def get_workspace_symbols(workspace, query):
    return SYMBOLS.get_workspace_symbols(workspace, query)


def get_code_actions(result, params):
    return CODE_ACTIONS.get_code_actions(result, params)


def build_index(result):
    return NAVIGATION.build_index(result)


def occurrence_at(result, position):
    return NAVIGATION.occurrence_at(result, position)


def references_to(result, definition):
    return NAVIGATION.references_to(result, definition)


def definition_map(result):
    return NAVIGATION.definition_map(result)


def uri_to_path(uri: str) -> str:
    return DocumentAnalyzer.path_from_uri(uri)


def utf16_length(text: str) -> int:
    return DocumentText.utf16_length(text)


def hover_text(hover) -> str:
    """Flatten a Hover's contents (MarkupContent or string) to text."""
    if hover is None:
        return ""
    c = hover.contents
    if hasattr(c, "value"):
        return c.value
    if isinstance(c, list):
        return " ".join(getattr(x, "value", str(x)) for x in c)
    return str(c)


def decoded_semantic_tokens(source: str, data: list[int], with_position: bool = False):
    line = 0
    col = 0
    lines = source.split("\n")
    decoded = []
    for i in range(0, len(data), 5):
        delta_line, delta_col, length, token_type, modifiers = data[i : i + 5]
        line += delta_line
        col = col + delta_col if delta_line == 0 else delta_col
        assert line < len(lines)
        token = lines[line][col : col + length]
        kind = TOKEN_TYPES[token_type]
        if with_position:
            decoded.append((line, col, token, kind, modifiers))
        else:
            decoded.append((token, kind, modifiers))
    return decoded


def pos_of(source: str, needle: str, occurrence: int = 1, offset: int = 0) -> lsp.Position:
    """LSP Position of the start of the `occurrence`-th `needle`, plus `offset`
    characters (use offset to land the cursor inside an identifier)."""
    idx = -1
    for _ in range(occurrence):
        nxt = source.find(needle, idx + 1)
        assert nxt >= 0, f"{needle!r} (occurrence {occurrence}) not found in source"
        idx = nxt
    pre = source[:idx]
    line = pre.count("\n")
    char = idx - (pre.rfind("\n") + 1)
    return lsp.Position(line=line, character=char + offset)
