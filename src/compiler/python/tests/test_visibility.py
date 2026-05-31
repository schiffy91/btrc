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
