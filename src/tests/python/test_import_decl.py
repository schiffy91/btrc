"""Import declaration: parsing into ImportDecl specs + front-end resolution.

`import` is a real keyword parsed from the token stream into ImportDecl nodes
(see grammar.ebnf / ast.asdl), so imports inside comments or strings never
resolve. These tests pin both the parsed spec shapes and that resolution still
finds the right files via the front-end helpers.
"""

import pytest

from src.compiler.python.ast_nodes import (
    ImportDecl,
    PackagePath,
    QuotedPath,
    RelativePath,
    StdGlob,
    StdModules,
)
from src.compiler.python.frontend import IncludeResolutionError, resolve_includes
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


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
    spec = _spec("import std.vector;")
    assert isinstance(spec, StdModules)
    assert spec.names == ["vector"]


def test_std_module_no_semicolon():
    # The trailing ';' is optional.
    spec = _spec("import std.vector")
    assert isinstance(spec, StdModules)
    assert spec.names == ["vector"]


def test_std_brace_set():
    spec = _spec("import std.{vector, strings};")
    assert isinstance(spec, StdModules)
    assert spec.names == ["vector", "strings"]


def test_std_brace_trailing_comma():
    spec = _spec("import std.{vector, strings,};")
    assert isinstance(spec, StdModules)
    assert spec.names == ["vector", "strings"]


def test_std_glob_and_recursive_glob():
    assert _spec("import std.*;") == StdGlob(recursive=False)
    assert _spec("import std.**;") == StdGlob(recursive=True)


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
    decls = _parse("int a() { return 0; }\nimport std.vector;")
    imp = decls[1]
    assert isinstance(imp, ImportDecl)
    assert imp.line == 2


# -- comment / keyword behaviour (the headline fix) -------------------------


def test_commented_import_is_not_parsed():
    decls = _parse("/* import std.nonexistent; */\nint main() { return 0; }")
    assert not any(isinstance(d, ImportDecl) for d in decls)


def test_line_commented_import_is_not_parsed():
    decls = _parse("// import ./nope.btrc\nint main() { return 0; }")
    assert not any(isinstance(d, ImportDecl) for d in decls)


def test_import_is_reserved_keyword():
    from src.compiler.python.parser.core import ParseError

    with pytest.raises(ParseError):
        _parse("int main() { int import = 1; return import; }")


def test_import_not_first_on_line_is_rejected():
    # An import sharing a line with preceding code is never resolved by the
    # front-end directive scan, so accepting it as a no-op would silently drop
    # the import. The parser rejects it instead.
    from src.compiler.python.parser.core import ParseError

    with pytest.raises(ParseError) as exc:
        _parse("int x = 0; import ./foo.btrc;\nint main() { return 0; }")
    assert exc.value.line == 1  # points at the misplaced import


def test_import_with_trailing_code_on_line_is_rejected():
    # First on its line, but followed by other code — same non-resolution, same
    # rejection.
    from src.compiler.python.parser.core import ParseError

    with pytest.raises(ParseError):
        _parse("import ./foo.btrc; int y = 5;\nint main() { return 0; }")


def test_import_owning_its_line_is_accepted():
    # The legitimate shape (import alone on its line) still parses fine.
    decls = _parse("int a() { return 0; }\nimport std.vector;")
    assert any(isinstance(d, ImportDecl) for d in decls)


# -- resolution still finds the files ---------------------------------------


def test_resolve_std_brace(tmp_path):
    src = "import std.{strings, json}\nint main() { return 0; }"
    resolved = resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "class Strings" in resolved
    assert "class JsonObject" in resolved
    assert "import std" not in resolved


def test_resolve_std_glob(tmp_path):
    src = "import std.*\nint main() { return 0; }"
    resolved = resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "class Vector" in resolved


def test_resolve_relative_file(tmp_path):
    write(tmp_path / "rel.btrc", "int relfn() { return 1; }\n")
    src = "import ./rel.btrc;\nint main() { return 0; }"
    resolved = resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "int relfn" in resolved


def test_resolve_quoted_relative(tmp_path):
    write(tmp_path / "rel.btrc", "int relq() { return 1; }\n")
    src = 'import "./rel.btrc";\nint main() { return 0; }'
    resolved = resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "int relq" in resolved


def test_resolve_directory_glob_sorted(tmp_path):
    d = tmp_path / "mods"
    d.mkdir()
    write(d / "b.btrc", "int bb() { return 2; }\n")
    write(d / "a.btrc", "int aa() { return 1; }\n")
    src = "import ./mods/*\nint main() { return 0; }"
    resolved = resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert resolved.index("int aa") < resolved.index("int bb")


def test_resolve_recursive_glob(tmp_path):
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    write(nested / "c.btrc", "int cc() { return 3; }\n")
    src = "import ./deep/**\nint main() { return 0; }"
    resolved = resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "int cc" in resolved


def test_resolve_commented_import_ignored(tmp_path):
    # The headline fix end to end: a commented-out import never resolves, so a
    # bogus module reference inside a comment does not fail the build.
    src = "/* import std.nonexistent_xyz; */\nint main() { return 0; }"
    resolved = resolve_includes(src, write(tmp_path / "m.btrc", src))
    assert "main" in resolved  # resolved fine; no IncludeResolutionError


def test_resolve_missing_std_module_errors(tmp_path):
    src = "import std.nonexistent_xyz\nint main() { return 0; }"
    with pytest.raises(IncludeResolutionError):
        resolve_includes(src, write(tmp_path / "m.btrc", src), exit_on_error=False)
