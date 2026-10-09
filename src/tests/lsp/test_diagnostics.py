"""Diagnostics = inline compile errors. Clean code reports nothing; lexer,
parser, and analyzer errors are reported with the right line and severity."""

from lsprotocol import types as lsp

from src.tests.lsp.lsphelp import analyze, compute_diagnostics


def _msgs(r):
    return [d.message for d in r.diagnostics]


def test_clean_source_has_no_diagnostics():
    r = analyze("int main() { return 0; }\n")
    assert r.diagnostics == []
    assert r.ast is not None and r.analyzed is not None


def test_unimported_stdlib_symbol_reports_strict_visibility_error():
    r = analyze("int main() { Vector<int> xs = []; return xs.len; }\n")

    assert any("'Vector' is defined in Vector.btrc" in message for message in _msgs(r))
    assert r.analyzed is not None
    assert "Vector" in r.analyzed.class_table


def test_explicit_stdlib_import_preserves_seeded_analysis_context():
    r = analyze("import Library.Vector;\nint main() { Vector<int> xs = []; xs.push(1); return xs.len; }\n")
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
    assert d.range.start.line == 1  # the bad string is on line 1 (0-based)
    assert d.source == "btrc"


def test_parser_error_reported():
    r = analyze("class { int x; }\n")  # missing class name
    assert r.diagnostics
    assert r.diagnostics[0].severity == lsp.DiagnosticSeverity.Error


def test_analyzer_error_reported_with_message_and_line():
    src = "class Box { private int x; public Box() { self.x = 0; } }\nint main() { Box b = Box(); return b.x; }\n"
    r = analyze(src)
    assert any("private" in m for m in _msgs(r))
    assert any(d.range.start.line == 1 for d in r.diagnostics)  # b.x access on line 1


def test_analyzer_warning_reported_with_warning_severity():
    src = "class Box { public int x; public Box() { self.x = 0; } }\nint read(Box? b) { return b.x; }\n"
    r = analyze(src)
    warnings = [d for d in r.diagnostics if d.severity == lsp.DiagnosticSeverity.Warning]
    assert any("Non-optional access" in d.message for d in warnings)
    assert any(d.range.start.line == 1 for d in warnings)


def test_diagnostic_line_maps_after_import_expansion(tmp_path):
    lib = tmp_path / "lib.btrc"
    lib.write_text("class Box { private int x; public Box() { self.x = 0; } }\n")
    main = tmp_path / "Main.btrc"
    source = "import ./lib.btrc;\nint main() { Box b = Box(); return b.x; }\n"
    main.write_text(source)

    r = analyze(source, uri=main.as_uri())

    assert any("private" in m for m in _msgs(r))
    assert any(d.range.start.line == 1 for d in r.diagnostics)


VENDOR_HEADER = (
    "#ifndef VENDOR_H\n#define VENDOR_H\nstruct Timer { long ticks; };\n"
    "struct ListNode { int value; struct ListNode* next; };\n"
    "enum Result { RESULT_OK = 7, RESULT_FAIL = 8 };\nunion Path { int i; float f; };\n#endif\n"
)


def test_header_tags_named_like_stdlib_types_report_nothing(tmp_path):
    """The editor composes the whole stdlib for completion; a header's own
    `struct Timer` collides with nothing the compilers see (C row 9)."""
    (tmp_path / "vendor.h").write_text(VENDOR_HEADER)
    main = tmp_path / "Main.btrc"
    source = (
        '#include "vendor.h"\nint main() {\n\tstruct Timer timer; timer.ticks = 5;\n'
        "\tstruct ListNode node = {3, null};\n\tenum Result result = RESULT_OK;\n"
        "\tunion Path path; path.i = 2;\n\treturn (int)timer.ticks + node.value + (int)result + path.i - 17;\n}\n"
    )
    main.write_text(source)

    r = analyze(source, uri=main.as_uri())

    assert _msgs(r) == []


def test_tag_of_a_stdlib_record_outside_the_program_reports_nothing(tmp_path):
    main = tmp_path / "Main.btrc"
    source = "int main() {\n\tstruct SPSCQueueStorage* storage = null;\n\treturn storage == null ? 0 : 1;\n}\n"
    main.write_text(source)

    r = analyze(source, uri=main.as_uri())

    assert _msgs(r) == []


def test_wrong_keyword_tag_of_a_program_record_is_still_reported():
    r = analyze("struct P { int v; };\nint main() { union P* p = null; return p == null ? 0 : 1; }\n")

    assert "'union P' does not name a union: 'P' is a struct" in _msgs(r)


def test_imported_generic_cannot_hide_a_flexible_struct_it_cannot_name(tmp_path):
    """r13: the library cannot name the program's `Entry`, so its type
    parameter hides nothing, in the editor as in the compilers."""
    (tmp_path / "CacheLib.btrc").write_text(
        "class Cache<Entry> {\n\tpublic Entry* slot;\n\tpublic Cache() { self.slot = null; }\n}\n"
    )
    main = tmp_path / "Main.btrc"
    source = (
        "import ./CacheLib.btrc;\nstruct Entry { int length; char text[]; };\n"
        "int main() { Cache<int> cache = new Cache<int>(); return cache.slot == null ? 0 : 1; }\n"
    )
    main.write_text(source)

    r = analyze(source, uri=main.as_uri())

    # The library's own diagnostics are filtered from this document's list,
    # so read the analysis the editor shares across its documents.
    assert r.analyzed is not None
    messages = _msgs(r) + [diagnostic.message for diagnostic in r.analyzed.diags]
    assert not any("Type parameter" in message for message in messages), messages


def test_diagnostic_range_is_well_formed():
    r = analyze("int main() { return undefinedThing(); }\n")
    # Whether or not this is an error, any emitted diagnostic must have a sane range.
    for d in r.diagnostics:
        assert d.range.start.line >= 0
        assert d.range.end.character >= d.range.start.character or d.range.end.line > d.range.start.line


def test_diagnostics_missing_include_is_tolerated():
    # include resolution failure is caught and falls back to the raw source —
    # the analysis must complete without crashing.
    r = analyze('#include "definitely_missing_file.btrc"\nint main() { return 0; }\n')
    assert r is not None and r.source


def test_unlocated_analyzer_error_becomes_diagnostic(monkeypatch):
    # an analyzer diag without a position (line/col 0) maps to a 1:1 diagnostic
    from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
    from src.compiler.python.analyzer.program import Diag

    real = SemanticAnalyzer.analyze

    def fake(self, program):
        res = real(self, program)
        res.diags.append(Diag("a problem with no position", 0, 0))
        return res

    monkeypatch.setattr(SemanticAnalyzer, "analyze", fake)
    # A unique URI keeps the shared workspace's snapshot cache from serving a
    # result computed before the monkeypatch (xdist order-dependent otherwise).
    r = compute_diagnostics("file:///t_unlocated_diag.btrc", "int main() { return 0; }\n")
    assert any("no position" in d.message for d in r.diagnostics)
    bad = next(d for d in r.diagnostics if "no position" in d.message)
    assert (bad.range.start.line, bad.range.start.character) == (0, 0)
