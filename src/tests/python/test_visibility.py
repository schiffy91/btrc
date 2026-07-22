import sys

import pytest

from src.compiler.python import main as m
from src.compiler.python.frontend import compile_frontend
from src.compiler.python.frontend_models import (
    FrontendVisibilityError,
    SourceDependencyKind,
)
from src.compiler.python.import_visibility import ImportVisibilityChecker
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def write(path, content):
    path.write_text(content)
    return str(path)


def visibility_errors(entry):
    source = entry.read_text()
    resolved, provenance, graph = m.resolve_includes_traced(source, str(entry))
    program = Parser(Lexer(resolved, entry.name).tokenize()).parse()
    return ImportVisibilityChecker(program, provenance, graph).check()


def test_direct_import_grants_cross_file_access(tmp_path):
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc", "import ./b.btrc;\nB makeB() { B b = new B(); return b; }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_symlink_import_grants_access_by_canonical_file_identity(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    write(real / "b.btrc", "class B {}\n")
    try:
        (tmp_path / "alias").symlink_to(real, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")
    write(
        tmp_path / "a.btrc",
        "import ./alias/b.btrc;\nB makeB() { return new B(); }\n",
    )
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_missing_per_file_import_reports_symbol_owner(tmp_path):
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc", "B makeB() { B b = new B(); return b; }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    errors = visibility_errors(entry)

    assert errors
    assert errors[0][0] == "'B' is defined in b.btrc but a.btrc does not import it"


def test_legacy_include_fragments_share_one_compilation_unit(tmp_path):
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc", "B makeB() { return new B(); }\n")
    entry = tmp_path / "main.btrc"
    write(entry, '#include "a.btrc"\n#include "b.btrc"\nint main() { return 0; }\n')

    resolved, provenance, graph = m.resolve_includes_traced(entry.read_text(), str(entry))
    program = Parser(Lexer(resolved, entry.name).tokenize()).parse()

    assert ImportVisibilityChecker(program, provenance, graph).check() == []
    dependencies = graph.dependencies_from(str(entry))
    assert {dependency.kind for dependency in dependencies} == {SourceDependencyKind.INCLUDE}


def test_include_component_does_not_reverse_its_parent_import(tmp_path):
    write(tmp_path / "fragment.btrc", "Root makeRoot() { return new Root(); }\n")
    write(tmp_path / "package.btrc", '#include "fragment.btrc"\n')
    entry = tmp_path / "main.btrc"
    write(entry, "import ./package.btrc;\nclass Root {}\nint main() { return 0; }\n")

    errors = visibility_errors(entry)

    assert errors
    assert errors[0][0] == ("'Root' is defined in main.btrc but fragment.btrc does not import it")


def test_mega_header_import_grants_transitive_access(tmp_path):
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "prelude.btrc", "import ./b.btrc;\n")
    write(tmp_path / "a.btrc", "import ./prelude.btrc;\nB makeB() { B b = new B(); return b; }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


@pytest.mark.parametrize("flags", ([], ["--strict-imports"]), ids=("default", "explicit"))
def test_strict_imports_cli_reports_visibility_error(tmp_path, monkeypatch, capsys, flags):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc", "B makeB() { B b = new B(); return b; }\n")
    entry = write(tmp_path / "main.btrc", "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    monkeypatch.setattr(sys, "argv", ["btrc", entry, *flags, "--no-cache"])
    with pytest.raises(SystemExit) as exc:
        m.main()

    assert exc.value.code == 1
    assert "'B' is defined in b.btrc but a.btrc does not import it" in capsys.readouterr().err


def test_relaxed_imports_is_an_explicit_legacy_opt_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc", "B makeB() { return new B(); }\n")
    entry = write(
        tmp_path / "main.btrc",
        "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n",
    )

    monkeypatch.setattr(
        sys,
        "argv",
        ["btrc", entry, "--relaxed-imports", "--no-cache"],
    )
    m.main()

    assert (tmp_path / "main.c").is_file()


def test_compile_frontend_api_defaults_to_strict_imports(tmp_path):
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc", "B makeB() { return new B(); }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    with pytest.raises(FrontendVisibilityError):
        compile_frontend(
            entry.read_text(),
            str(entry),
            include_stdlib=False,
        )


def test_cache_identity_prevents_valid_graph_from_masking_missing_import(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "c.btrc", "class C {}\n")
    consumer = tmp_path / "a.btrc"
    entry = tmp_path / "main.btrc"
    write(
        entry,
        "import ./b.btrc;\nimport ./c.btrc;\nimport ./a.btrc;\nint main() { return 0; }\n",
    )

    write(consumer, "import ./b.btrc;\nB makeB() { return new B(); }\n")
    valid = m.resolve_frontend_source(entry.read_text(), str(entry), include_stdlib=False)
    monkeypatch.setattr(sys, "argv", ["btrc", str(entry)])
    m.main()
    capsys.readouterr()

    write(consumer, "import ./c.btrc;\nB makeB() { return new B(); }\n")
    invalid = m.resolve_frontend_source(entry.read_text(), str(entry), include_stdlib=False)
    assert invalid.source == valid.source
    assert invalid.source_positions == valid.source_positions
    assert invalid.cache_identity() != valid.cache_identity()

    with pytest.raises(SystemExit) as error:
        m.main()

    assert error.value.code == 1
    assert "'B' is defined in b.btrc but a.btrc does not import it" in (capsys.readouterr().err)


def test_local_shadowing_top_level_symbol_is_not_a_reference(tmp_path):
    """Locals/params named like a top-level symbol must not demand an import."""
    write(tmp_path / "b.btrc", "class Logger {}\nint helper() { return 1; }\n")
    write(
        tmp_path / "a.btrc",
        "int work(int helper) {\n"
        "    int Logger = helper + 1;\n"  # local shadows class
        "    for (int helper = 0; helper < 3; helper++) { Logger += helper; }\n"
        "    return Logger;\n"
        "}\n",
    )
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_loop_and_catch_variables_are_scoped(tmp_path):
    write(tmp_path / "b.btrc", "class Item {}\n")
    write(
        tmp_path / "a.btrc",
        "int scan(Vector<int> xs) {\n"
        "    int total = 0;\n"
        "    for Item in xs { total += Item; }\n"  # loop var shadows class
        "    try { total += 1; } catch (Item) { total = 0; }\n"
        "    return total;\n"
        "}\n",
    )
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_genuine_reference_still_reported_alongside_local(tmp_path):
    """Scoping must not hide real cross-file references."""
    write(tmp_path / "b.btrc", "class B {}\n")
    write(tmp_path / "a.btrc", "int f() { int x = 0; B b = new B(); return x; }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./a.btrc;\nimport ./b.btrc;\nint main() { return 0; }\n")

    errors = visibility_errors(entry)
    assert errors
    assert errors[0][0] == "'B' is defined in b.btrc but a.btrc does not import it"


def test_method_generic_does_not_bind_to_same_named_top_level_type(tmp_path):
    write(tmp_path / "u.btrc", "class U {}\n")
    write(
        tmp_path / "box.btrc",
        "class Box { public U identity<U>(U value) { return value; } }\n",
    )
    entry = tmp_path / "main.btrc"
    write(entry, "import ./u.btrc;\nimport ./box.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


@pytest.mark.parametrize(
    "consumer",
    (
        "int readShared() { return shared; }\n",
        "int initialized = shared;\n",
    ),
    ids=("function", "global-initializer"),
)
def test_global_variable_reference_requires_per_file_import(tmp_path, consumer):
    write(tmp_path / "globals.btrc", "int shared = 42;\n")
    write(tmp_path / "consumer.btrc", consumer)
    entry = tmp_path / "main.btrc"
    write(
        entry,
        "import ./globals.btrc;\nimport ./consumer.btrc;\nint main() { return 0; }\n",
    )

    errors = visibility_errors(entry)

    assert errors
    assert errors[0][0] == ("'shared' is defined in globals.btrc but consumer.btrc does not import it")


def test_explicit_import_grants_global_variable_access(tmp_path):
    write(tmp_path / "globals.btrc", "int shared = 42;\n")
    write(
        tmp_path / "consumer.btrc",
        "import ./globals.btrc;\nint initialized = shared;\n",
    )
    entry = tmp_path / "main.btrc"
    write(entry, "import ./consumer.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


@pytest.mark.parametrize(
    ("owner_source", "consumer_source", "symbol"),
    (
        ("enum Color { RED, BLUE };\n", "int color() { return RED; }\n", "RED"),
        ("#define ANSWER() 42\n", "int answer() { return ANSWER(); }\n", "ANSWER"),
    ),
    ids=("bare-enumerator", "source-macro"),
)
def test_non_declaration_top_level_symbols_require_import(tmp_path, owner_source, consumer_source, symbol):
    write(tmp_path / "owner.btrc", owner_source)
    write(tmp_path / "consumer.btrc", consumer_source)
    entry = tmp_path / "main.btrc"
    write(
        entry,
        "import ./owner.btrc;\nimport ./consumer.btrc;\nint main() { return 0; }\n",
    )

    errors = visibility_errors(entry)

    assert errors
    assert errors[0][0] == (f"'{symbol}' is defined in owner.btrc but consumer.btrc does not import it")


@pytest.mark.parametrize(
    ("owner_source", "consumer_source"),
    (
        ("enum Color { RED, BLUE };\n", "int color() { return RED; }\n"),
        ("#define ANSWER() 42\n", "int answer() { return ANSWER(); }\n"),
    ),
    ids=("bare-enumerator", "source-macro"),
)
def test_explicit_import_grants_non_declaration_symbol_access(tmp_path, owner_source, consumer_source):
    write(tmp_path / "owner.btrc", owner_source)
    write(
        tmp_path / "consumer.btrc",
        "import ./owner.btrc;\n" + consumer_source,
    )
    entry = tmp_path / "main.btrc"
    write(entry, "import ./consumer.btrc;\nint main() { return 0; }\n")

    assert visibility_errors(entry) == []


def test_duplicate_symbol_satisfied_by_any_declaring_file(tmp_path):
    """When two files declare the same name, importing either satisfies it."""
    write(tmp_path / "impl1.btrc", "int helper() { return 1; }\n")
    write(tmp_path / "impl2.btrc", "int helper() { return 2; }\n")
    write(tmp_path / "uses2.btrc", "import ./impl2.btrc;\nint go() { return helper(); }\n")
    entry = tmp_path / "main.btrc"
    write(entry, "import ./impl1.btrc;\nimport ./uses2.btrc;\nint main() { return 0; }\n")

    # uses2 imports impl2 (one of the declaring files): satisfied, even though
    # impl1 also declares 'helper' and was registered first.
    assert visibility_errors(entry) == []
