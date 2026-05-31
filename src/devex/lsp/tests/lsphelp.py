"""Shared helpers for btrc LSP tests.

Tests drive the real feature functions over real source through the same
compiler front-end the server uses, then assert concrete positions/strings.
"""

from lsprotocol import types as lsp

from src.devex.lsp.diagnostics import compute_diagnostics

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
    """Run the compiler pipeline and return the AnalysisResult."""
    return compute_diagnostics(uri, source)


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
