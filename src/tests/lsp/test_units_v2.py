"""Per-file unit pipeline: native positions, composition, caching, debounce."""

import os

from lsprotocol import types as lsp

from src.compiler.python.frontend.sources import (
    SourceDependencyGraph,
    SourceDependencyKind,
)
from src.compiler.python.syntax.ast.generated import (
    FunctionDecl,
    ImportDecl,
    Program,
    RelativePath,
    StdModules,
)
from src.devex.lsp.protocol.server import BtrcLanguageServer
from src.devex.lsp.workspace.units import FileUnit
from src.devex.lsp.workspace.workspace import Composition, Workspace
from src.tests.lsp.lsphelp import compute_diagnostics, get_definition, get_hover_info, pos_of

srv = BtrcLanguageServer(debounce_seconds=0)


def test_file_unit_reads_typed_dependencies_in_native_coordinates():
    src = 'import std.vector\n#include "legacy.btrc"\nimport ./lib/*;\n\nint main() { return 0; }\n'
    unit = FileUnit.parse("/x/main.btrc", src)
    dependencies = list(unit.dependencies)
    assert [dependency.line for dependency in dependencies] == [1, 2, 3]
    specs = [dependency.spec for dependency in dependencies]
    assert specs[0] == StdModules(names=["vector"])
    assert specs[1] == RelativePath(path="legacy.btrc")
    assert specs[2] == RelativePath(path="./lib/*")
    assert [dependency.kind for dependency in dependencies] == [
        SourceDependencyKind.IMPORT,
        SourceDependencyKind.INCLUDE,
        SourceDependencyKind.IMPORT,
    ]
    assert unit.error is None
    # Files parse as-is (no blanking): ImportDecl nodes carry native lines and
    # main() keeps its real line (5).
    assert [d.line for d in unit.decls if isinstance(d, ImportDecl)] == [1, 3]
    main = next(d for d in unit.decls if isinstance(d, FunctionDecl))
    assert main.line == 5
    assert main.source_file == "/x/main.btrc"


def test_parse_unit_name_positions_land_on_names():
    # The name-span side-table was retired: each decl/member carries its own
    # name_line/name_col, populated by the parser and read directly.
    src = "class Point {\n    public int x;\n    public int getX() { return self.x; }\n}\n"
    unit = FileUnit.parse("/x/p.btrc", src)
    cls = unit.decls[0]
    assert (cls.name_line, cls.name_col) == (1, 7)  # 'Point'
    field, method = cls.members[0], cls.members[1]
    assert (field.name_line, field.name_col) == (2, 16)  # 'x'
    assert (method.name_line, method.name_col) == (3, 16)  # 'getX'


def _write_project(tmp_path, lib_source=None):
    lib = tmp_path / "lib.btrc"
    lib.write_text(lib_source or "class Helper {\n    public int v;\n    public Helper(int v) { self.v = v; }\n}\n")
    main = tmp_path / "main.btrc"
    source = "import ./lib.btrc;\nint main() {\n    Helper h = new Helper(1);\n    return h.v;\n}\n"
    main.write_text(source)
    return main, source


def test_hover_on_import_line_is_none(tmp_path):
    main, source = _write_project(tmp_path)
    r = compute_diagnostics(main.as_uri(), source)
    # The historic bug: unmapped import-line positions aliased into the
    # concatenated stdlib and hover showed stdlib classes (e.g. ListNode).
    h = get_hover_info(r, lsp.Position(line=0, character=10))
    assert h is None


def test_cross_file_definition_lands_on_name_token(tmp_path):
    main, source = _write_project(tmp_path)
    r = compute_diagnostics(main.as_uri(), source)
    loc = get_definition(r, pos_of(source, "new Helper", offset=5))
    assert loc is not None
    assert loc.uri == (tmp_path / "lib.btrc").as_uri()
    assert (loc.range.start.line, loc.range.start.character) == (0, 6)  # 'Helper'


def test_broken_import_diagnosed_on_import_line(tmp_path):
    main, source = _write_project(tmp_path, lib_source="class Broken {\n")
    r = compute_diagnostics(main.as_uri(), source)
    lines = [d.range.start.line for d in r.diagnostics]
    assert 0 in lines  # the `import ./lib.btrc;` line
    assert any("lib.btrc" in d.message for d in r.diagnostics)


def test_missing_import_diagnosed_on_import_line(tmp_path):
    main = tmp_path / "main.btrc"
    source = "import ./nope.btrc;\nint main() { return 0; }\n"
    main.write_text(source)
    r = compute_diagnostics(main.as_uri(), source)
    assert any(d.range.start.line == 0 for d in r.diagnostics)


def test_visibility_diagnostics_are_scoped_to_the_active_file(tmp_path):
    library = tmp_path / "library.btrc"
    library_source = "int count(Vector<int> values) { return values.len; }\n"
    library.write_text(library_source)
    main = tmp_path / "main.btrc"
    main_source = "import ./library.btrc;\nint main() { return 0; }\n"
    main.write_text(main_source)

    main_result = compute_diagnostics(main.as_uri(), main_source)
    library_result = compute_diagnostics(library.as_uri(), library_source)

    assert not any("library.btrc does not import" in diagnostic.message for diagnostic in main_result.diagnostics)
    assert any("library.btrc does not import" in diagnostic.message for diagnostic in library_result.diagnostics)


def test_composition_fingerprint_includes_dependency_topology(tmp_path):
    active = FileUnit.parse(str(tmp_path / "main.btrc"), "int main() { return 0; }\n")
    imported = FileUnit.parse(str(tmp_path / "dep.btrc"), "class Dependency {}\n")

    import_graph = SourceDependencyGraph()
    import_graph.add_import(active.path, imported.path)
    include_graph = SourceDependencyGraph()
    include_graph.add_include(active.path, imported.path)

    def composition(graph):
        return Composition(
            active=active,
            imported=[imported],
            stdlib=[],
            program=Program(declarations=active.decls + imported.decls),
            import_errors=[],
            graph=graph,
        )

    assert composition(import_graph).snapshot_fingerprint("file:///main.btrc") != composition(
        include_graph
    ).snapshot_fingerprint("file:///main.btrc")


def test_imported_units_are_cached_across_keystrokes(tmp_path):
    main, source = _write_project(tmp_path)
    w = Workspace()
    a1 = w.parse_active(str(main), source)
    c1 = w.compose(a1)
    a2 = w.parse_active(str(main), source + "\n// edit")
    c2 = w.compose(a2)
    assert c1.imported[0] is c2.imported[0]  # same unit object: no re-parse
    assert a1 is not a2


def test_seeded_analysis_matches_full_analysis(tmp_path):
    from src.compiler.python.analyzer.analyzer import SemanticAnalyzer

    main = tmp_path / "main.btrc"
    source = (
        "import std.vector;\n"
        "int main() {\n"
        "    var v = Vector(3);\n"
        "    v.push(1.5);\n"
        "    bogusCall();\n"  # one real error
        "    return v.len();\n"
        "}\n"
    )
    main.write_text(source)
    w = Workspace()
    seeded = w.analyze(w.compose(w.parse_active(str(main), source)))
    # The full-analysis baseline uses a fresh parse (the old pipeline's
    # behavior); analyzing the same AST objects twice is not supported.
    w2 = Workspace()
    full = SemanticAnalyzer().analyze(w2.compose(w2.parse_active(str(main), source)).program)
    key = lambda d: (d.message, d.line, d.severity)  # noqa: E731
    seeded_diags = [key(d) for d in seeded.diags if d.file == str(main)]
    full_diags = [key(d) for d in full.diags if d.file == str(main)]
    assert seeded_diags == full_diags
    assert seeded_diags  # the bogus constructor arity error is present
    assert set(seeded.class_table) == set(full.class_table)


def test_reanalysis_of_cached_imports_is_idempotent(tmp_path):
    # Imported units keep their AST between keystrokes; the analyzer upgrades
    # class-typed params/returns in place. A second analysis must not report
    # its own upgrades as 'Redundant pointer' errors.
    lib = tmp_path / "lib.btrc"
    lib.write_text(
        "class Node {\n"
        "    public int v;\n"
        "    public Node(int v) { self.v = v; }\n"
        "    public Node combine(Node other) { return new Node(self.v + other.v); }\n"
        "}\n"
    )
    main = tmp_path / "main.btrc"
    source = (
        "import ./lib.btrc;\n"
        "int main() {\n"
        "    Node a = new Node(1);\n"
        "    Node b = a.combine(new Node(2));\n"
        "    return b.v;\n"
        "}\n"
    )
    main.write_text(source)
    w = Workspace()
    for i in range(3):  # three keystrokes, same imported unit object each time
        comp = w.compose(w.parse_active(str(main), source + "\n" * i))
        analyzed = w.analyze(comp)
        assert not analyzed.diags, f"keystroke {i}: {[d.message for d in analyzed.diags]}"


def test_warm_keystroke_is_fast(tmp_path):
    import time

    main, source = _write_project(tmp_path)
    compute_diagnostics(main.as_uri(), source)  # warm stdlib units + base
    elapsed_samples = []
    for newline_count in (1, 2, 3):
        start = time.process_time()
        result = compute_diagnostics(main.as_uri(), source + "\n" * newline_count)
        elapsed_samples.append(time.process_time() - start)
        assert result.analyzed is not None
    # Generous CI budget; locally this is ~1-5ms (was ~500ms pre-v2).
    # Process time measures parser/analyzer work without charging an xdist
    # worker for time it was descheduled by another native compiler process.
    best = min(elapsed_samples)
    samples = ", ".join(f"{elapsed * 1000:.0f}ms" for elapsed in elapsed_samples)
    assert best < 0.15, f"warm keystrokes took [{samples}]"


def test_debounce_coalesces_validations(monkeypatch, tmp_path):
    import time

    runs = []
    # Scheduled runs now pass their schedule-time generation so stale runs
    # can be dropped before publishing; the stub accepts the keyword.
    monkeypatch.setattr(srv, "_validate_document", lambda uri, src, generation=None: runs.append(src))
    for i in range(5):
        srv._schedule_validation("file:///d.btrc", f"v{i}", 0.05)
    time.sleep(0.3)
    assert runs == ["v4"]  # only the last edit validated


def test_active_file_overlay_used_for_imports(tmp_path):
    main, source = _write_project(tmp_path)
    w = Workspace()
    overlay_text = "class Helper {\n    public int v;\n    public int extra;\n}\n"
    w.overlay_provider = lambda path: overlay_text if os.path.basename(path) == "lib.btrc" else None
    comp = w.compose(w.parse_active(str(main), source))
    helper = next(d for d in comp.imported[0].decls if getattr(d, "name", "") == "Helper")
    assert any(getattr(m, "name", "") == "extra" for m in helper.members)
