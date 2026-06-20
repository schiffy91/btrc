import sys

import pytest

from src.compiler.python import main as m
from src.compiler.python.import_visibility import check_visibility
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def write(path, content):
    path.write_text(content)
    return str(path)


def visibility_errors(entry):
    source = entry.read_text()
    resolved, provenance, graph = m.resolve_includes_traced(source, str(entry))
    program = Parser(Lexer(resolved, entry.name).tokenize()).parse()
    return check_visibility(program, provenance, graph)


def test_direct_import_grants_cross_file_access(tmp_path):
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc",
          "import ./b.btrc;\nB makeB() { B b = new B(); return b; }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_missing_per_file_import_reports_symbol_owner(tmp_path):
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc",
          "B makeB() { B b = new B(); return b; }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    errors = visibility_errors(entry)

    assert errors
    assert errors[0][0] == "'B' is defined in b.btrc but a.btrc does not import it"


def test_mega_header_import_grants_transitive_access(tmp_path):
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "prelude.btrc", "import ./b.btrc;\n")
    write(tmp_path / "a.btrc",
          "import ./prelude.btrc;\nB makeB() { B b = new B(); return b; }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_strict_imports_cli_reports_visibility_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc",
          "B makeB() { B b = new B(); return b; }\n")
    entry = write(tmp_path / "main.btrc",
                  "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    monkeypatch.setattr(sys, "argv", ["btrc", entry, "--strict-imports", "--no-cache"])
    with pytest.raises(SystemExit) as exc:
        m.main()

    assert exc.value.code == 1
    assert "'B' is defined in b.btrc but a.btrc does not import it" in capsys.readouterr().err


def test_local_shadowing_top_level_symbol_is_not_a_reference(tmp_path):
    """Locals/params named like a top-level symbol must not demand an import."""
    write(tmp_path / "b.btrc", "class Logger {}\nint helper() { return 1; }\n")
    write(tmp_path / "a.btrc",
          "int work(int helper) {\n"
          "    int Logger = helper + 1;\n"          # local shadows class
          "    for (int helper = 0; helper < 3; helper++) { Logger += helper; }\n"
          "    return Logger;\n"
          "}\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_loop_and_catch_variables_are_scoped(tmp_path):
    write(tmp_path / "b.btrc", "class Item {}\n")
    write(tmp_path / "a.btrc",
          "int scan(Vector<int> xs) {\n"
          "    int total = 0;\n"
          "    for Item in xs { total += Item; }\n"  # loop var shadows class
          "    try { total += 1; } catch (Item) { total = 0; }\n"
          "    return total;\n"
          "}\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_genuine_reference_still_reported_alongside_local(tmp_path):
    """Scoping must not hide real cross-file references."""
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc",
          "int f() { int x = 0; B b = new B(); return x; }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    errors = visibility_errors(entry)
    assert errors
    assert errors[0][0] == "'B' is defined in b.btrc but a.btrc does not import it"


def test_duplicate_symbol_satisfied_by_any_declaring_file(tmp_path):
    """When two files declare the same name, importing either satisfies it."""
    write(tmp_path / "impl1.btrc", "int helper() { return 1; }\n")
    write(tmp_path / "impl2.btrc", "int helper() { return 2; }\n")
    write(tmp_path / "uses2.btrc",
          "import ./impl2.btrc;\nint go() { return helper(); }\n")
    entry = tmp_path / "main.btrc"
    write(entry,
          "import ./impl1.btrc;\nimport ./uses2.btrc;\n"
          "int main() { return 0; }\n")

    # uses2 imports impl2 (one of the declaring files): satisfied, even though
    # impl1 also declares 'helper' and was registered first.
    assert visibility_errors(entry) == []
