"""textDocument/codeAction: import-insert and did-you-mean quick-fixes."""

import importlib

from lsprotocol import types as lsp

from src.devex.lsp.code_actions import _closest, _levenshtein, get_code_actions
from src.devex.lsp.diagnostics import WORKSPACE, compute_diagnostics
from src.devex.lsp.tests.lsphelp import analyze

srv = importlib.import_module("src.devex.lsp.server")


def _actions(result, uri, line, c0=0, c1=40):
    rng = lsp.Range(
        start=lsp.Position(line=line, character=c0),
        end=lsp.Position(line=line, character=c1),
    )
    params = lsp.CodeActionParams(
        text_document=lsp.TextDocumentIdentifier(uri=uri),
        range=rng,
        context=lsp.CodeActionContext(diagnostics=[]),
    )
    return get_code_actions(result, params)


def test_levenshtein_basic():
    assert _levenshtein("Widget", "Widget", 2) == 0
    assert _levenshtein("Widgt", "Widget", 2) == 1
    assert _levenshtein("xyz", "Widget", 2) == 3  # capped
    assert _closest("Widgt", ["Widget", "Gadget"]) == "Widget"
    assert _closest("zzzzzz", ["Widget"]) is None  # too far


def test_did_you_mean_class_typo():
    src = "class Widget {\n    public int x;\n}\nint main() {\n    var w = Widgt();\n    return 0;\n}\n"
    r = analyze(src, uri="file:///dym.btrc")
    acts = _actions(r, "file:///dym.btrc", 4)
    titles = [a.title for a in acts]
    assert any("Widgt" in t and "Widget" in t for t in titles), titles
    # The edit changes 'Widgt' -> 'Widget'.
    fix = next(a for a in acts if "Widget" in a.title)
    edits = fix.edit.changes["file:///dym.btrc"]
    assert edits[0].new_text == "Widget"


def test_no_action_for_resolved_local():
    # 'w' is a resolved local; no spurious action for it.
    src = "class Widget {\n    public int x;\n}\nint main() {\n    var w = Widget();\n    return w.x;\n}\n"
    r = analyze(src, uri="file:///ok.btrc")
    acts = _actions(r, "file:///ok.btrc", 5)
    assert acts == []


def test_import_insert_for_stdlib_name():
    # Shadow stdlib DateTime so datetime.btrc is filtered out of the
    # composition; the sibling stdlib class Timer is then unresolved and the
    # import action offers 'import std.datetime;'.
    src = "class DateTime {\n    public int y;\n}\nint main() {\n    var t = Timer();\n    return 0;\n}\n"
    uri = "file:///stdimp.btrc"
    r = compute_diagnostics(uri, src)
    assert not (r.analyzed and "Timer" in r.analyzed.class_table)
    acts = _actions(r, uri, 4)
    imp = [a for a in acts if a.title.startswith("Add import")]
    assert imp, [a.title for a in acts]
    assert "std.datetime" in imp[0].title
    edits = imp[0].edit.changes[uri]
    assert edits[0].new_text == "import std.datetime;\n"
    assert edits[0].range.start.line == 0  # inserted at top (no existing imports)


def test_import_insert_for_sibling_file(tmp_path):
    lib = tmp_path / "lib.btrc"
    lib.write_text("class Gadget {\n    public int n;\n}\n")
    WORKSPACE.get_file_unit(str(lib))  # warm the sibling into the unit cache

    app_uri = (tmp_path / "app.btrc").as_uri()
    src = "int main() {\n    var g = Gadget();\n    return 0;\n}\n"
    r = compute_diagnostics(app_uri, src)
    acts = _actions(r, app_uri, 1)
    imp = [a for a in acts if a.title.startswith("Add import")]
    assert imp, [a.title for a in acts]
    assert "Gadget" in imp[0].title
    edits = imp[0].edit.changes[app_uri]
    assert edits[0].new_text == 'import "lib.btrc";\n'


def test_import_skipped_when_already_imported(tmp_path):
    lib = tmp_path / "lib2.btrc"
    lib.write_text("class Sprocket {\n    public int n;\n}\n")
    WORKSPACE.get_file_unit(str(lib))
    app_uri = (tmp_path / "app2.btrc").as_uri()
    # Already imports lib2.btrc, so no import action — but Sprocket now resolves,
    # so there is simply nothing unresolved to offer.
    src = 'import "lib2.btrc";\nint main() {\n    var s = Sprocket();\n    return 0;\n}\n'
    r = compute_diagnostics(app_uri, src)
    acts = _actions(r, app_uri, 2)
    assert not any(a.title.startswith("Add import") for a in acts)


def test_import_suggestion_excludes_cached_units_from_other_projects(tmp_path):
    foreign_root = tmp_path / "foreign"
    active_root = tmp_path / "active"
    foreign_root.mkdir()
    active_root.mkdir()
    foreign = foreign_root / "foreign.btrc"
    foreign.write_text("class ForeignOnlySuggestion { public int n; }\n")
    WORKSPACE.get_file_unit(str(foreign))

    app_uri = (active_root / "app.btrc").as_uri()
    source = "int main() { var item = ForeignOnlySuggestion(); return 0; }\n"
    result = compute_diagnostics(app_uri, source)
    actions = _actions(result, app_uri, 0)

    assert not any(action.title.startswith("Add import") for action in actions)


def test_import_suggestion_excludes_a_nested_project(tmp_path):
    (tmp_path / "btrc.toml").write_text("[dependencies]\n")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "btrc.toml").write_text("[dependencies]\n")
    foreign = nested / "foreign.btrc"
    foreign.write_text("class NestedProjectOnly { public int n; }\n")
    WORKSPACE.get_file_unit(str(foreign))

    app_uri = (tmp_path / "app.btrc").as_uri()
    source = "int main() { var item = NestedProjectOnly(); return 0; }\n"
    result = compute_diagnostics(app_uri, source)
    actions = _actions(result, app_uri, 0)

    assert not any(action.title.startswith("Add import") for action in actions)


def test_handler(tmp_path):
    src = "class Widget {\n    public int x;\n}\nint main() {\n    var w = Widgt();\n    return 0;\n}\n"
    uri = "file:///h.btrc"
    r = compute_diagnostics(uri, src)
    srv._analysis_cache[uri] = r
    srv._good_analysis_cache[uri] = r
    rng = lsp.Range(start=lsp.Position(line=4, character=0), end=lsp.Position(line=4, character=40))
    out = srv.code_action(
        lsp.CodeActionParams(
            text_document=lsp.TextDocumentIdentifier(uri=uri),
            range=rng,
            context=lsp.CodeActionContext(diagnostics=[]),
        )
    )
    assert any("Widget" in a.title for a in out)
    srv._analysis_cache.clear()
    srv._good_analysis_cache.clear()
