"""LSP source mapping for files that textually expand imports."""

from src.devex.lsp.definition import get_definition
from src.devex.lsp.hover import get_hover_info
from src.devex.lsp.references import get_references, get_rename_edits
from src.devex.lsp.tests.lsphelp import analyze, hover_text, pos_of


def _write_import_case(tmp_path):
    lib = tmp_path / "lib.btrc"
    lib.write_text(
        "class Imported {\n"
        "    public int value;\n"
        "    public Imported(int value) { self.value = value; }\n"
        "    public int get() { return self.value; }\n"
        "}\n"
        "\n"
        "int importedHelper() { return 1; }\n"
    )
    main = tmp_path / "main.btrc"
    source = (
        "import ./lib.btrc;\n"
        "int main() {\n"
        "    Imported item = Imported(3);\n"
        "    int n = importedHelper();\n"
        "    return item.get() + n;\n"
        "}\n"
    )
    main.write_text(source)
    return lib, main, source


def test_definition_maps_imported_symbol_to_original_file(tmp_path):
    lib, main, source = _write_import_case(tmp_path)

    loc = get_definition(
        analyze(source, uri=main.as_uri()),
        pos_of(source, "importedHelper();", offset=1),
    )

    assert loc is not None
    assert loc.uri == lib.as_uri()
    assert loc.range.start.line == 6


def test_definition_maps_stdlib_static_method_to_installed_source():
    source = 'int main() { var items = Strings.split("a,b", ","); return items.len(); }\n'

    loc = get_definition(
        analyze(source),
        pos_of(source, "Strings.split", offset=9),
    )

    assert loc is not None
    assert loc.uri.endswith("/src/stdlib/strings.btrc")
    assert loc.range.start.line == 85


def test_hover_maps_document_position_after_import(tmp_path):
    _lib, main, source = _write_import_case(tmp_path)

    hover = get_hover_info(
        analyze(source, uri=main.as_uri()),
        pos_of(source, "Imported item", offset=1),
    )

    assert "class Imported" in hover_text(hover)


def test_self_member_resolution_after_import_stays_in_local_class(tmp_path):
    lib = tmp_path / "lib.btrc"
    lib.write_text(
        "class Imported {\n"
        "    public int value;\n"
        "    public Imported(int value) { self.value = value; }\n"
        "}\n"
    )
    main = tmp_path / "main.btrc"
    source = (
        "import ./lib.btrc;\n"
        "class Payload {\n"
        "    public string name;\n"
        "    public Payload(string name) { self.name = name; }\n"
        "}\n"
        "class Local {\n"
        "    public Payload value;\n"
        "    public Local(Payload value) { self.value = value; }\n"
        "    public Payload get() { return self.value; }\n"
        "}\n"
    )
    main.write_text(source)
    result = analyze(source, uri=main.as_uri())

    loc = get_definition(result, pos_of(source, "return self.value", offset=12))
    hover = hover_text(
        get_hover_info(result, pos_of(source, "return self.value", offset=12))
    )

    assert loc is not None
    assert loc.uri == main.as_uri()
    assert loc.range.start.line == 6
    assert "Field of `Local`" in hover
    assert "TypeExpr(" not in hover
    assert "Payload value" in hover
    assert "Payload* value" not in hover


def test_references_and_rename_group_cross_file_locations(tmp_path):
    lib, main, source = _write_import_case(tmp_path)
    result = analyze(source, uri=main.as_uri())
    cursor = pos_of(source, "importedHelper();", offset=1)

    refs = get_references(result, cursor)
    edit = get_rename_edits(result, cursor, "renamedHelper")

    assert {loc.uri for loc in refs} == {lib.as_uri(), main.as_uri()}
    assert edit is not None
    assert set(edit.changes or {}) == {lib.as_uri(), main.as_uri()}


def test_parse_diagnostic_maps_after_import_expansion(tmp_path):
    lib = tmp_path / "lib.btrc"
    lib.write_text("int helper() { return 1; }\n")
    main = tmp_path / "main.btrc"
    source = "import ./lib.btrc;\nclass { int x; }\n"
    main.write_text(source)

    diagnostics = analyze(source, uri=main.as_uri()).diagnostics

    assert diagnostics
    assert diagnostics[0].range.start.line == 1
