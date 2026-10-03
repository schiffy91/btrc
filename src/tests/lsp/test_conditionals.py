"""C4 preprocessor conditionals in the editor (c-preprocessor-conditionals.md).

Each file is conditioned with the host target before it is lexed: a dead line
has no tokens, symbols, hovers or diagnostics, and every live line keeps its
position.
"""

from __future__ import annotations

from lsprotocol import types as lsp

from src.compiler.python.frontend.packages import PackageTarget
from src.compiler.python.frontend.sources import ConditionalEnvironment, SourceConditionals
from src.devex.lsp.workspace.cache import UnitCache
from src.devex.lsp.workspace.units import FileUnit
from src.tests.lsp.lsphelp import analyze, get_document_symbols, get_hover_info, get_semantic_tokens

DEAD_DUPLICATE = """\
#if 0
int value() { return 1; }
#endif
int value() { return 2; }
int main() { return value(); }
"""


def test_a_dead_duplicate_gives_no_diagnostic() -> None:
    result = analyze(DEAD_DUPLICATE, "file:///dead_duplicate.btrc")
    assert result.diagnostics == []


def test_hover_on_a_dead_line_is_null() -> None:
    source = "int main() {\n    int count = 2;\n#if 0\n    return count;\n#endif\n    return count;\n}\n"
    result = analyze(source, "file:///dead_hover.btrc")
    assert result.diagnostics == []
    assert get_hover_info(result, lsp.Position(line=3, character=12)) is None
    assert get_hover_info(result, lsp.Position(line=5, character=12)) is not None


def test_dead_lines_have_no_semantic_tokens() -> None:
    result = analyze(DEAD_DUPLICATE, "file:///dead_tokens.btrc")
    tokens = get_semantic_tokens(result)
    data = tokens.data if tokens is not None else []
    line = 0
    lines = set()
    for index in range(0, len(data), 5):
        line += data[index]
        lines.add(line)
    assert 1 not in lines
    assert 3 in lines


def test_symbols_and_brace_scopes_exclude_dead_declarations() -> None:
    source = """\
class Shape {
#if 0
    public int dead() {
#else
    public int live() {
#endif
        return 1;
    }
}
int main() { return 0; }
"""
    result = analyze(source, "file:///dead_symbols.btrc")
    assert result.diagnostics == []
    symbols = get_document_symbols(result)
    shape = next(symbol for symbol in symbols if symbol.name == "Shape")
    assert [child.name for child in shape.children or []] == ["live"]
    assert shape.range.end.line == 8


def test_a_conditioning_error_is_a_positioned_diagnostic() -> None:
    result = analyze("int a;\n#ifdef X\nint main() { return 0; }\n", "file:///unterminated.btrc")
    assert len(result.diagnostics) == 1
    diagnostic = result.diagnostics[0]
    assert "'#ifdef' without '#endif'" in diagnostic.message
    assert (diagnostic.range.start.line, diagnostic.range.start.character) == (1, 0)


def test_a_crlf_buffer_conditions_like_its_lf_form(tmp_path) -> None:
    lf = "#if 0\nint a;\n#else\nint b;\n#endif\n"
    crlf = lf.replace("\n", "\r\n")
    path = str(tmp_path / "Crlf.btrc")
    environment = SourceConditionals(ConditionalEnvironment(PackageTarget("linux", "x86_64")))
    lf_unit = FileUnit.parse(path, lf, conditionals=environment)
    crlf_unit = FileUnit.parse(path, crlf, conditionals=environment)
    assert crlf_unit.error is None
    assert crlf_unit.conditioned_source == lf_unit.conditioned_source == "\n\n\nint b;\n\n"
    assert [declaration.name for declaration in crlf_unit.decls] == ["b"]


def test_unit_cache_key_includes_the_target_and_environment(tmp_path) -> None:
    linux = UnitCache(tmp_path, environment=ConditionalEnvironment(PackageTarget("linux", "x86_64")))
    macos = UnitCache(tmp_path, environment=ConditionalEnvironment(PackageTarget("macos", "aarch64")))
    again = UnitCache(tmp_path, environment=ConditionalEnvironment(PackageTarget("linux", "x86_64")))
    source = "int a;\n"
    assert linux.entry_path(source) != macos.entry_path(source)
    assert linux.entry_path(source) == again.entry_path(source)


def test_an_unsupported_host_only_fails_files_with_conditionals(tmp_path) -> None:
    conditionals = SourceConditionals(ConditionalEnvironment(None))
    plain = FileUnit.parse(str(tmp_path / "Plain.btrc"), "int main() { return 0; }\n", conditionals=conditionals)
    assert plain.error is None
    tested = FileUnit.parse(str(tmp_path / "Tested.btrc"), "#if 1\n#endif\n", conditionals=conditionals)
    assert tested.error is not None
    assert "preprocessor conditionals need a target" in str(tested.error)
    assert (tested.lex_error.line, tested.lex_error.col) == (1, 1)
