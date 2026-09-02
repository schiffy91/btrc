"""Performance contracts for self-hosted C output assembly."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_emitted_lines_are_joined_in_one_linear_pass() -> None:
    source = (REPO / "src/compiler/btrc/ir/emitter.btrc").read_text().expandtabs(4)
    start = source.index("    private string joinLines() {")
    end = source.index("\n    }", start)
    implementation = source[start:end]

    assert 'return Strings.join(self.lines, "\\n") + "\\n";' in implementation
    assert "out = out +" not in implementation
