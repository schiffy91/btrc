"""workspace/symbol: fuzzy search over active + imported + stdlib symbols."""

from lsprotocol import types as lsp

from src.devex.lsp.protocol.server import BtrcLanguageServer
from src.devex.lsp.workspace.workspace import Workspace
from src.tests.lsp.lsphelp import WORKSPACE, compute_diagnostics, get_workspace_symbols

srv = BtrcLanguageServer(debounce_seconds=0, compiler_workspace=WORKSPACE)

USER = """\
class Widget {
    public int x;
    public int area() { return self.x; }
}

int helper(int a) { return a; }

int main() {
    var w = Widget();
    return 0;
}
"""


def _warm(source: str, uri: str = "file:///proj/app.btrc"):
    """Parse a document so the workspace caches its unit (and the stdlib)."""
    return compute_diagnostics(uri, source)


def test_finds_user_class_by_substring():
    _warm(USER)
    syms = get_workspace_symbols(WORKSPACE, "widg")
    widgets = [s for s in syms if s.name == "Widget"]
    assert widgets, "user Widget not found"
    assert all(s.kind == lsp.SymbolKind.Class for s in widgets)
    # The active document's Widget is among the hits (other tests may also have
    # cached a Widget in the shared process-wide workspace).
    assert any(s.location.uri.endswith("app.btrc") for s in widgets)


def test_finds_stdlib_class():
    _warm(USER)
    syms = get_workspace_symbols(WORKSPACE, "Vector")
    vec = [s for s in syms if s.name == "Vector"]
    assert vec, "stdlib Vector not found by workspace/symbol"
    assert vec[0].kind == lsp.SymbolKind.Class
    assert vec[0].location.uri.endswith("vector.btrc")


def test_finds_function_by_substring():
    _warm(USER)
    syms = get_workspace_symbols(WORKSPACE, "help")
    fns = [s for s in syms if s.name == "helper"]
    assert fns and fns[0].kind == lsp.SymbolKind.Function


def test_empty_query_lists_everything():
    _warm(USER)
    syms = get_workspace_symbols(WORKSPACE, "")
    names = {s.name for s in syms}
    assert "Widget" in names
    assert "Vector" in names  # stdlib included


def test_substring_ranked_before_subsequence():
    _warm(USER)
    syms = get_workspace_symbols(WORKSPACE, "vec")
    idx_vector = next(i for i, s in enumerate(syms) if s.name == "Vector")
    # Everything before 'Vector' must itself be a substring (rank <= 2) match of
    # 'vec' — a pure subsequence match can never outrank it.
    for s in syms[:idx_vector]:
        assert "vec" in s.name.lower()


def test_handler_returns_symbols(monkeypatch):
    _warm(USER)
    out = srv.workspace_symbol(lsp.WorkspaceSymbolParams(query="Widget"))
    assert any(s.name == "Widget" for s in out)


def test_struct_definition_preferred_over_forward_declarations(tmp_path):
    source_file = tmp_path / "structs.btrc"
    source_file.write_text("struct WorkspaceTail;\nstruct WorkspaceTail { int value; };\nstruct WorkspaceTail;\n")
    workspace = Workspace()
    assert workspace.get_file_unit(str(source_file)) is not None

    matches = [
        symbol
        for symbol in get_workspace_symbols(workspace, "WorkspaceTail")
        if symbol.location.uri == source_file.as_uri()
    ]
    assert len(matches) == 1
    assert matches[0].location.range.start.line == 1
