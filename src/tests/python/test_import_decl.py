"""Import declaration: parsing into ImportDecl specs + front-end resolution.

`import` is a real keyword parsed from the token stream into ImportDecl nodes
(see grammar.ebnf / ast.asdl), so imports inside comments or strings never
resolve. These tests pin both the parsed spec shapes and that resolution still
finds the right files via the front-end helpers.
"""

import pytest

from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.packages import IncludeResolutionError
from src.compiler.python.frontend.sources import SourceDirectiveScanner
from src.compiler.python.frontend.stage import FrontendStage
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import (
    ImportDecl,
    LibraryGlob,
    LibraryModules,
    PackagePath,
    QuotedPath,
    RelativePath,
)

RESOLVER = FrontendStage().resolver


def _parse(src: str):
    return Parser(Lexer(src).tokenize()).parse().declarations


def _spec(src: str):
    decls = _parse(src)
    assert len(decls) == 1
    assert isinstance(decls[0], ImportDecl)
    return decls[0].spec


def write(path, text):
    path.write_text(text)
    return str(path)


# -- parsed spec shapes -----------------------------------------------------


def test_std_single_module():
    spec = _spec("import Library.Vector;")
    assert isinstance(spec, LibraryModules)
    assert spec.names == ["Vector"]


def test_std_module_no_semicolon():
    # The trailing ';' is optional.
    spec = _spec("import Library.Vector")
    assert isinstance(spec, LibraryModules)
    assert spec.names == ["Vector"]


def test_nested_library_modules():
    assert _spec("import Library.Audio.MacOS.CoreAudioDevice;") == LibraryModules(names=["Audio.MacOS.CoreAudioDevice"])
    assert _spec("import Library.{Audio.AudioDevice, Audio.RealtimeAudio,};") == LibraryModules(
        names=["Audio.AudioDevice", "Audio.RealtimeAudio"]
    )


def test_std_brace_set():
    spec = _spec("import Library.{Vector, Strings};")
    assert isinstance(spec, LibraryModules)
    assert spec.names == ["Vector", "Strings"]


def test_std_brace_trailing_comma():
    spec = _spec("import Library.{Vector, Strings,};")
    assert isinstance(spec, LibraryModules)
    assert spec.names == ["Vector", "Strings"]


def test_std_glob_and_recursive_glob():
    assert _spec("import Library.*;") == LibraryGlob(recursive=False)
    assert _spec("import Library.**;") == LibraryGlob(recursive=True)


def test_relative_paths():
    assert _spec("import ./lib.btrc;") == RelativePath(path="./lib.btrc")
    assert _spec("import ./dir/*") == RelativePath(path="./dir/*")
    assert _spec("import ./dir/**") == RelativePath(path="./dir/**")
    assert _spec("import ../up/x.btrc") == RelativePath(path="../up/x.btrc")


def test_quoted_path_strips_quotes():
    spec = _spec('import "rel/path.btrc";')
    assert isinstance(spec, QuotedPath)
    assert spec.path == "rel/path.btrc"


def test_package_path():
    assert _spec("import mathx;") == PackagePath(segments=["mathx"])
    assert _spec("import mathx.vec;") == PackagePath(segments=["mathx", "vec"])


def test_import_line_recorded():
    decls = _parse("int a() { return 0; }\nimport Library.Vector;")
    imp = decls[1]
    assert isinstance(imp, ImportDecl)
    assert imp.line == 2


# -- comment / keyword behaviour (the headline fix) -------------------------


def test_commented_import_is_not_parsed():
    decls = _parse("/* import Library.nonexistent; */\nint main() { return 0; }")
    assert not any(isinstance(d, ImportDecl) for d in decls)


def test_line_commented_import_is_not_parsed():
    decls = _parse("// import ./nope.btrc\nint main() { return 0; }")
    assert not any(isinstance(d, ImportDecl) for d in decls)


def test_import_is_reserved_keyword():
    from src.compiler.python.parser.parser import ParseError

    with pytest.raises(ParseError):
        _parse("int main() { int import = 1; return import; }")


def test_import_not_first_on_line_is_rejected():
    # An import sharing a line with preceding code is never resolved by the
    # front-end directive scan, so accepting it as a no-op would silently drop
    # the import. The parser rejects it instead.
    from src.compiler.python.parser.parser import ParseError

    with pytest.raises(ParseError) as exc:
        _parse("int x = 0; import ./foo.btrc;\nint main() { return 0; }")
    assert exc.value.line == 1  # points at the misplaced import


def test_import_with_trailing_code_on_line_is_rejected():
    # First on its line, but followed by other code — same non-resolution, same
    # rejection.
    from src.compiler.python.parser.parser import ParseError

    with pytest.raises(ParseError):
        _parse("import ./foo.btrc; int y = 5;\nint main() { return 0; }")


def test_import_owning_its_line_is_accepted():
    # The legitimate shape (import alone on its line) still parses fine.
    decls = _parse("int a() { return 0; }\nimport Library.Vector;")
    assert any(isinstance(d, ImportDecl) for d in decls)


# -- resolution still finds the files ---------------------------------------


def test_resolve_std_brace(tmp_path):
    src = "import Library.{Strings, JSON}\nint main() { return 0; }"
    resolved = RESOLVER.resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "class Strings" in resolved
    assert "class JSONObject" in resolved
    assert "import std" not in resolved


def test_resolve_std_glob(tmp_path):
    src = "import Library.*\nint main() { return 0; }"
    resolved = RESOLVER.resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "class Vector" in resolved


def test_resolve_relative_file(tmp_path):
    write(tmp_path / "rel.btrc", "int relfn() { return 1; }\n")
    src = "import ./rel.btrc;\nint main() { return 0; }"
    resolved = RESOLVER.resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "int relfn" in resolved


def test_resolve_quoted_relative(tmp_path):
    write(tmp_path / "rel.btrc", "int relq() { return 1; }\n")
    src = 'import "./rel.btrc";\nint main() { return 0; }'
    resolved = RESOLVER.resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "int relq" in resolved


def test_resolve_directory_glob_sorted(tmp_path):
    d = tmp_path / "mods"
    d.mkdir()
    write(d / "b.btrc", "int bb() { return 2; }\n")
    write(d / "a.btrc", "int aa() { return 1; }\n")
    src = "import ./mods/*\nint main() { return 0; }"
    resolved = RESOLVER.resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert resolved.index("int aa") < resolved.index("int bb")


def test_resolve_recursive_glob(tmp_path):
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    write(nested / "c.btrc", "int cc() { return 3; }\n")
    src = "import ./deep/**\nint main() { return 0; }"
    resolved = RESOLVER.resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "int cc" in resolved


def test_resolve_commented_import_ignored(tmp_path):
    # The headline fix end to end: a commented-out import never resolves, so a
    # bogus module reference inside a comment does not fail the build.
    src = "/* import Library.nonexistent_xyz; */\nint main() { return 0; }"
    resolved = RESOLVER.resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "main" in resolved  # resolved fine; no IncludeResolutionError


def test_resolve_missing_std_module_errors(tmp_path):
    src = "import Library.nonexistent_xyz\nint main() { return 0; }"
    with pytest.raises(IncludeResolutionError):
        RESOLVER.resolve_includes(src, write(tmp_path / "m.btrc", src), exit_on_error=False)


@pytest.mark.parametrize(
    "directives",
    [
        "import Library.Vector;\n",
        "import Library.{Vector,\n Strings,};\n",
        "import Library.**;\nimport dependency.API;\n",
        'import "./relative.btrc";\nimport ./modules/**;\n',
        '#include "Other.btrc"\n',
        '/* import ./missing.btrc; */\nstring text = "import ./missing.btrc;";\n',
        "",
    ],
)
def test_directive_cache_reparses_only_owned_fragments(tmp_path, monkeypatch, directives):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    source = directives + "\n".join(f"int function{index}() {{ return {index}; }}" for index in range(100))
    path = str(tmp_path / "Main.btrc")
    expected = SourceDirectiveScanner().scan(source)
    assert SourceDirectiveScanner(CompilerCache()).scan(source, cache_input=path) == expected
    assert list((tmp_path / "cache").glob("*.directives.json"))
    scanner = SourceDirectiveScanner(CompilerCache())
    original = scanner._scan
    scanned = []

    def scan_fragment(fragment):
        scanned.append(fragment)
        return original(fragment)

    monkeypatch.setattr(scanner, "_scan", scan_fragment)
    assert scanner.scan(source, cache_input=path) == expected
    assert source not in scanned
    assert len(scanned) == len(expected)


@pytest.mark.parametrize(
    "source", ["/* begins\n*/ import ./Other.btrc;\n", "import ./Other.btrc; /* begins\n ends */\n"]
)
def test_cached_directive_with_external_comment_context_falls_back(tmp_path, monkeypatch, source):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    expected = SourceDirectiveScanner().scan(source)
    assert len(expected) == 1
    path = str(tmp_path / "Main.btrc")
    for _ in range(2):
        assert SourceDirectiveScanner(CompilerCache()).scan(source, cache_input=path) == expected


def test_invalid_source_does_not_publish_an_empty_directive_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path))
    scanner = SourceDirectiveScanner(CompilerCache())
    assert scanner.scan('import ./Other.btrc;\n"unterminated', cache_input=str(tmp_path / "Main.btrc")) == []
    assert not list(tmp_path.glob("*.directives.json"))


def test_cached_import_syntax_still_resolves_current_directory_membership(tmp_path, monkeypatch):
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    modules = tmp_path / "modules"
    modules.mkdir()
    first = modules / "First.btrc"
    first.write_text("int first() { return 1; }\n")
    source = "import ./modules/*;\nint main() { return first(); }\n"
    path = write(tmp_path / "Main.btrc", source)

    def resolve():
        imports = ImportResolver(directive_scanner=SourceDirectiveScanner(CompilerCache()))
        return FrontendStage(imports=imports).resolve(source, path)

    before = resolve()
    assert resolve().source == before.source
    first.touch()
    assert resolve().source == before.source
    second = modules / "Second.btrc"
    second.write_text("int second() { return 2; }\n")
    assert "int second()" in resolve().source
    first.write_text("int first() { return 3; }\n")
    assert "return 3" in resolve().source
    second.unlink()
    assert "int second()" not in resolve().source
    first.write_text("import ./Missing.btrc;\nint first() { return 3; }\n")
    with pytest.raises(IncludeResolutionError, match="Missing"):
        resolve()
