"""Diagnostics = inline compile errors. Clean code reports nothing; lexer,
parser, and analyzer errors are reported with the right line and severity."""

from lsprotocol import types as lsp

from src.devex.lsp.tests.lsphelp import analyze


def _msgs(r):
    return [d.message for d in r.diagnostics]


def test_clean_source_has_no_diagnostics():
    r = analyze("int main() { return 0; }\n")
    assert r.diagnostics == []
    assert r.ast is not None and r.analyzed is not None


def test_diagnostics_use_compiler_stdlib_context():
    r = analyze("int main() { Vector<int> xs = []; xs.push(1); return xs.len; }\n")
    assert r.diagnostics == []
    assert r.analyzed is not None
    assert "Vector" in r.analyzed.class_table


def test_missing_import_reports_resolution_error():
    r = analyze("import ./missing.btrc;\nint main() { return 0; }\n")
    assert any("not found" in m for m in _msgs(r))


def test_lexer_error_reported_with_location():
    r = analyze('int main() {\n string s = "unterminated;\n return 0; }\n')
    assert r.diagnostics, "expected a lexer diagnostic"
    d = r.diagnostics[0]
    assert d.severity == lsp.DiagnosticSeverity.Error
    assert d.range.start.line == 1          # the bad string is on line 1 (0-based)
    assert d.source == "btrc"


def test_parser_error_reported():
    r = analyze("class { int x; }\n")        # missing class name
    assert r.diagnostics
    assert r.diagnostics[0].severity == lsp.DiagnosticSeverity.Error


def test_analyzer_error_reported_with_message_and_line():
    src = ("class Box { private int x; public Box() { self.x = 0; } }\n"
           "int main() { Box b = Box(); return b.x; }\n")
    r = analyze(src)
    assert any("private" in m for m in _msgs(r))
    assert any(d.range.start.line == 1 for d in r.diagnostics)  # b.x access on line 1


def test_analyzer_warning_reported_with_warning_severity():
    src = ("class Box { public int x; public Box() { self.x = 0; } }\n"
           "int main() { Box? b = new Box(); return b.x; }\n")
    r = analyze(src)
    warnings = [d for d in r.diagnostics if d.severity == lsp.DiagnosticSeverity.Warning]
    assert any("Non-optional access" in d.message for d in warnings)
    assert any(d.range.start.line == 1 for d in warnings)


def test_diagnostic_line_maps_after_import_expansion(tmp_path):
    lib = tmp_path / "lib.btrc"
    lib.write_text("class Box { private int x; public Box() { self.x = 0; } }\n")
    main = tmp_path / "main.btrc"
    source = "import ./lib.btrc;\nint main() { Box b = Box(); return b.x; }\n"
    main.write_text(source)

    r = analyze(source, uri=main.as_uri())

    assert any("private" in m for m in _msgs(r))
    assert any(d.range.start.line == 1 for d in r.diagnostics)


def test_diagnostic_range_is_well_formed():
    r = analyze("int main() { return undefinedThing(); }\n")
    # Whether or not this is an error, any emitted diagnostic must have a sane range.
    for d in r.diagnostics:
        assert d.range.start.line >= 0
        assert d.range.end.character >= d.range.start.character or d.range.end.line > d.range.start.line
