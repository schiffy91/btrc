"""Tests for the compiler driver (main.py): CLI flags, include/import
resolution, stdlib selection, error formatting, and IR dumping."""

import json
import os
import pickle
import shutil
import subprocess

import pytest

from src.compiler.python import Compiler, frontend_c_imports
from src.compiler.python import stdlib_ast_cache as ast_cache
from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.cli.compiler_cli import CompilerCLI
from src.compiler.python.cli_diagnostics import format_error
from src.compiler.python.frontend import stdlib as frontend_stdlib_owner
from src.compiler.python.frontend.resolver import SourceResolver
from src.compiler.python.frontend.stdlib import StdlibRepository
from src.compiler.python.pkg import IncludeResolutionError

RESOLVER = SourceResolver()
STDLIB = StdlibRepository()

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def write(path, content):
    with open(path, "w") as f:
        f.write(content)
    return str(path)


def run_main(monkeypatch, argv):
    CompilerCLI().run(argv)


HELLO = 'int main() { print("PASS"); return 0; }\n'
BARE = "int main() { return 0; }\n"


# --------------------------------------------------------------------------
# end-to-end driver flags
# --------------------------------------------------------------------------


def test_default_compile_writes_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "a.btrc", HELLO)
    run_main(monkeypatch, [src, "-o", str(tmp_path / "a.c")])
    out = capsys.readouterr().out
    assert "Transpiled" in out
    assert os.path.exists(tmp_path / "a.c")
    assert "int main" in (tmp_path / "a.c").read_text()


def test_default_output_name(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "prog.btrc", HELLO)
    run_main(monkeypatch, [src])
    assert os.path.exists(tmp_path / "prog.c")


def test_cached_second_run(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "c.btrc", HELLO)
    run_main(monkeypatch, [src, "-o", str(tmp_path / "c.c")])
    capsys.readouterr()
    run_main(monkeypatch, [src, "-o", str(tmp_path / "c.c")])
    assert "(cached)" in capsys.readouterr().out


def test_cached_default_output(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "d.btrc", HELLO)
    run_main(monkeypatch, [src])
    capsys.readouterr()
    run_main(monkeypatch, [src])  # cache hit, default output path branch
    assert "(cached)" in capsys.readouterr().out


def test_emit_tokens(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "t.btrc", BARE)
    run_main(monkeypatch, [src, "--emit-tokens"])
    out = capsys.readouterr().out
    assert "Token" in out


def test_emit_ast(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "t.btrc", BARE)
    run_main(monkeypatch, [src, "--emit-ast"])
    assert "FunctionDecl" in capsys.readouterr().out


def test_emit_ir(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(
        tmp_path / "t.btrc",
        "enum Color { RED, GREEN = 5 };\n"
        "struct Point { int x; int y; };\n"
        "int add(int a, int b) { return a + b; }\n"
        "int main() { return add(1, 2); }\n",
    )
    run_main(monkeypatch, [src, "--emit-ir"])
    out = capsys.readouterr().out
    assert "IRModule:" in out
    assert "enum Color" in out
    assert "struct Point" in out
    assert "fn " in out


def test_emit_optimized_ir(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "t.btrc", BARE)
    run_main(monkeypatch, [src, "--emit-optimized-ir"])
    assert "IRModule:" in capsys.readouterr().out


def test_no_stdlib(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "n.btrc", BARE)
    run_main(monkeypatch, [src, "--no-stdlib", "-o", str(tmp_path / "n.c")])
    assert os.path.exists(tmp_path / "n.c")


def test_debug_line_directives(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "dbg.btrc", HELLO)
    run_main(monkeypatch, [src, "--debug", "-o", str(tmp_path / "dbg.c")])
    assert os.path.exists(tmp_path / "dbg.c")


def test_no_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "nc.btrc", HELLO)
    run_main(monkeypatch, [src, "--no-cache", "-o", str(tmp_path / "nc.c")])
    assert os.path.exists(tmp_path / "nc.c")


def test_profile(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "p.btrc", HELLO)
    # --no-cache: profiling needs the full pipeline, and the session-shared
    # disk cache may already hold this source from an earlier test.
    run_main(monkeypatch, [src, "--no-cache", "--profile", "-o", str(tmp_path / "p.c")])
    err = capsys.readouterr().err
    assert "btrc profile" in err
    assert "total" in err


def test_profile_bypasses_existing_compiled_c_cache(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))
    src = write(tmp_path / "profile-cache.btrc", BARE)
    output = str(tmp_path / "profile-cache.c")

    run_main(monkeypatch, [src, "--no-stdlib", "-o", output])
    capsys.readouterr()
    run_main(monkeypatch, [src, "--no-stdlib", "--profile", "-o", output])
    captured = capsys.readouterr()

    assert "(cached)" not in captured.out
    assert "btrc profile" in captured.err


# --------------------------------------------------------------------------
# true end-to-end: source → CLI → C → compile → run
# --------------------------------------------------------------------------


def test_cli_end_to_end_compiles_and_runs(tmp_path, monkeypatch, capsys):
    """The whole pipeline: drive main() to emit C, compile it with a real C
    compiler, run the binary, and assert its computed output — proving the CLI
    produces a correct, runnable program (not just that a .c file is written)."""
    cc = shutil.which("cc") or shutil.which("gcc")
    if cc is None:
        pytest.skip("no C compiler available")
    monkeypatch.chdir(tmp_path)
    prog = (
        "int fib(int n) { if (n < 2) { return n; } return fib(n - 1) + fib(n - 2); }\n"
        'int main() { if (fib(10) != 55) { return 1; } print("E2E_OK"); return 0; }\n'
    )
    src = write(tmp_path / "e2e.btrc", prog)
    out_c = str(tmp_path / "e2e.c")
    run_main(monkeypatch, [src, "-o", out_c])
    assert "Transpiled" in capsys.readouterr().out

    binp = str(tmp_path / "e2e_bin")
    subprocess.run([cc, "-std=c11", out_c, "-o", binp, "-lm", "-lpthread"], check=True)
    result = subprocess.run([binp], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "E2E_OK" in result.stdout


# --------------------------------------------------------------------------
# error paths
# --------------------------------------------------------------------------


def test_file_not_found(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [str(tmp_path / "nope.btrc")])
    assert "not found" in capsys.readouterr().err


def test_invalid_utf8_input_reports_a_clean_error(tmp_path, monkeypatch, capsys):
    source = tmp_path / "invalid.btrc"
    source.write_bytes(b"int main() { return 0; }\xff")
    with pytest.raises(SystemExit) as stopped:
        run_main(monkeypatch, [str(source)])
    captured = capsys.readouterr()
    assert stopped.value.code == 1
    assert "not valid UTF-8" in captured.err
    assert "Traceback" not in captured.err


def test_lexer_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    # An unterminated string is a lexer error.
    src = write(tmp_path / "le.btrc", 'int main() { string s = "unterminated;\n return 0; }\n')
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src, "--no-cache"])
    assert "error:" in capsys.readouterr().err


def test_parser_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "pe.btrc", "class { int x; }\n")  # missing class name
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src, "--no-cache"])
    assert "error:" in capsys.readouterr().err


def test_analyzer_error_with_location(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(
        tmp_path / "ae.btrc",
        "class Box { private int x; public Box() { self.x = 0; } }\nint main() { Box b = Box(); return b.x; }\n",
    )  # private field access
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src, "--no-cache"])
    assert "error:" in capsys.readouterr().err


def test_analyzer_error_fallback_format(tmp_path, monkeypatch, capsys):
    """An analyzer error without a ' at line:col' suffix uses the plain branch."""
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "af.btrc", BARE)

    real = SemanticAnalyzer.analyze

    def fake(self, program):
        result = real(self, program)
        result.errors.append("a bare error with no location")
        return result

    monkeypatch.setattr(SemanticAnalyzer, "analyze", fake)
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src, "--no-cache"])
    assert "a bare error with no location" in capsys.readouterr().err


def test_analyzer_error_bad_location(tmp_path, monkeypatch, capsys):
    """A ' at x:y' suffix with non-integer coords falls through to plain print."""
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "ab.btrc", BARE)
    real = SemanticAnalyzer.analyze

    def fake(self, program):
        result = real(self, program)
        result.errors.append("bad loc at foo:bar")
        return result

    monkeypatch.setattr(SemanticAnalyzer, "analyze", fake)
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src, "--no-cache"])
    assert "bad loc" in capsys.readouterr().err


def test_analyzer_warning(tmp_path, monkeypatch, capsys):
    """Warnings are printed (with and without location) but do not abort."""
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "w.btrc", HELLO)
    real = SemanticAnalyzer.analyze

    def fake(self, program):
        result = real(self, program)
        result.warnings.append("located warning at 1:1")
        result.warnings.append("plain warning no loc")
        result.warnings.append("bad warning at x:y")
        return result

    monkeypatch.setattr(SemanticAnalyzer, "analyze", fake)
    run_main(monkeypatch, [src, "--no-cache", "-o", str(tmp_path / "w.c")])
    err = capsys.readouterr().err
    assert "warning:" in err
    assert os.path.exists(tmp_path / "w.c")


# --------------------------------------------------------------------------
# _format_error
# --------------------------------------------------------------------------


def test_format_error_normal():
    out = format_error("line one\nline two\n", "f.btrc", "boom", 2, 3)
    assert "boom" in out and "f.btrc:2:3" in out and "line two" in out and "^" in out


def test_format_error_out_of_range():
    out = format_error("only line\n", "f.btrc", "boom", 99, 1)
    assert out == "error: boom\n --> f.btrc:99:1"
    out2 = format_error("x", "f.btrc", "boom", 0, 1)
    assert "--> f.btrc:0:1" in out2


# --------------------------------------------------------------------------
# include / import resolution
# --------------------------------------------------------------------------


def test_resolve_hash_include(tmp_path):
    write(tmp_path / "lib.btrc", "int helper() { return 7; }\n")
    main_src = '#include "lib.btrc"\nint main() { return helper(); }\n'
    p = write(tmp_path / "m.btrc", main_src)
    resolved = RESOLVER.resolve_includes(main_src, p)
    assert "int helper" in resolved


def test_resolve_missing_include(tmp_path, capsys):
    main_src = '#include "ghost.btrc"\nint main() { return 0; }\n'
    p = write(tmp_path / "m.btrc", main_src)
    with pytest.raises(SystemExit):
        RESOLVER.resolve_includes(main_src, p)
    assert "not found" in capsys.readouterr().err


def test_resolve_invalid_utf8_include_reports_resolution_error(tmp_path):
    included = tmp_path / "invalid.btrc"
    included.write_bytes(b"int helper() { return 1; }\xff")
    source = '#include "invalid.btrc"\nint main() { return 0; }\n'
    root = write(tmp_path / "main.btrc", source)
    with pytest.raises(IncludeResolutionError, match="not valid UTF-8"):
        RESOLVER.resolve_includes(source, root, exit_on_error=False)


def test_resolve_circular_include(tmp_path):
    a = tmp_path / "a.btrc"
    b = tmp_path / "b.btrc"
    a.write_text('#include "b.btrc"\nint a() { return 1; }\n')
    b.write_text('#include "a.btrc"\nint b() { return 2; }\n')
    resolved = RESOLVER.resolve_includes(a.read_text(), str(a))
    assert "int a" in resolved and "int b" in resolved  # no infinite loop


def test_resolve_symlink_cycle_uses_canonical_identity(tmp_path):
    source = '#include "loop/a.btrc"\nint a() { return 1; }\n'
    path = tmp_path / "a.btrc"
    path.write_text(source)
    try:
        (tmp_path / "loop").symlink_to(tmp_path, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks unavailable: {error}")

    resolved = RESOLVER.resolve_includes(source, str(path))
    assert resolved.count("int a()") == 1


def test_import_stdlib_single(tmp_path):
    src = "import std.math;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "class Math" in resolved or "Math" in resolved


def test_import_stdlib_brace(tmp_path):
    src = "import std.{math, json};\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "Math" in resolved and "Json" in resolved


def test_import_stdlib_glob(tmp_path):
    src = "import std.*;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "class Vector" in resolved


def test_import_stdlib_not_found(tmp_path, capsys):
    src = "import std.nonexistent_module;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    with pytest.raises(SystemExit):
        RESOLVER.resolve_includes(src, p)
    assert "not found" in capsys.readouterr().err


def test_import_relative_file(tmp_path):
    write(tmp_path / "rel.btrc", "int rel() { return 1; }\n")
    src = "import ./rel.btrc;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "int rel" in resolved


def test_import_relative_quoted(tmp_path):
    write(tmp_path / "rel.btrc", "int relq() { return 1; }\n")
    src = 'import "./rel.btrc";\nint main() { return 0; }\n'
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "int relq" in resolved


def test_import_directory_direct_glob(tmp_path):
    d = tmp_path / "mods"
    d.mkdir()
    write(d / "one.btrc", "int one() { return 1; }\n")
    write(d / "two.btrc", "int two() { return 2; }\n")
    src = "import ./mods/*;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "int one" in resolved and "int two" in resolved


def test_import_directory_recursive_glob(tmp_path):
    d = tmp_path / "deep" / "nested"
    d.mkdir(parents=True)
    write(d / "x.btrc", "int deepx() { return 1; }\n")
    src = "import ./deep/**;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "int deepx" in resolved


def test_import_directory_not_found(tmp_path, capsys):
    src = "import ./missing_dir/*;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    with pytest.raises(SystemExit):
        RESOLVER.resolve_includes(src, p)
    assert "not found" in capsys.readouterr().err


def test_import_plain_directory(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    write(d / "a.btrc", "int plaina() { return 1; }\n")
    src = "import ./plain;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "int plaina" in resolved


def test_import_c_file(tmp_path):
    write(tmp_path / "native.c", "int native(void) { return 1; }\n")
    src = "import ./native.c;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert '#include "' in resolved and "native.c" in resolved


def test_repeated_c_import_is_emitted_once_by_canonical_identity(tmp_path):
    native = tmp_path / "native.c"
    write(native, "int native(void) { return 1; }\n")
    try:
        (tmp_path / "native_alias.c").symlink_to(native)
    except OSError as error:
        pytest.skip(f"file symlinks unavailable: {error}")
    source = "import ./native.c;\nimport ./native_alias.c;\nint main() { return native(); }\n"
    root = write(tmp_path / "main.btrc", source)
    resolved = RESOLVER.resolve_includes(source, root)
    assert resolved.count("#include") == 1


@pytest.mark.parametrize("unsafe", ['bad"name.c', "bad\nname.c", "bad??/name.c"])
def test_c_import_rejects_paths_that_c11_cannot_quote_safely(unsafe):
    with pytest.raises(IncludeResolutionError, match="cannot import C file"):
        frontend_c_imports.c_include_directive(unsafe)


def test_c_import_preserves_spaces_and_backslashes():
    path = r"C:\source tree\native.c"
    assert frontend_c_imports.c_include_directive(path) == f'#include "{path}"'


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _parse_one(src: str):
    """Parse a snippet and return its single top-level declaration."""
    from src.compiler.python.lexer import Lexer
    from src.compiler.python.parser.parser import Parser

    return Parser(Lexer(src).tokenize()).parse().declarations[0]


def test_quoted_import_strips_quotes():
    # Quote stripping moved from the frontend regex into the parser.
    from src.compiler.python.ast_nodes import QuotedPath

    spec = _parse_one('import "std/math.btrc";').spec
    assert isinstance(spec, QuotedPath)
    assert spec.path == "std/math.btrc"


def test_brace_import_expands_into_names():
    # Brace expansion moved from the frontend regex into the parser.
    from src.compiler.python.ast_nodes import StdModules

    spec = _parse_one("import std.{a, b};").spec
    assert isinstance(spec, StdModules)
    assert spec.names == ["a", "b"]
    single = _parse_one("import std.math;").spec
    assert isinstance(single, StdModules)
    assert single.names == ["math"]


def test_discover_stdlib_files():
    files = STDLIB.discover_files()
    assert files[0] == "vector.btrc"  # foundation first
    assert "strings.btrc" in files


def test_get_stdlib_source_skips_redefined():
    # User redefining Vector means vector.btrc is skipped → shorter output.
    full = STDLIB.source("")
    skipped = STDLIB.source("class Vector<T> { public int len; }\n")
    assert len(skipped) < len(full)


def test_get_stdlib_source_skips_redefined_interface():
    skipped = STDLIB.source("interface Iterable<T> { bool hasNext(); }\n")
    assert "interface Iterable" not in skipped


def test_find_stdlib_file_subdir():
    # gui/gui.btrc lives in a subdirectory; basename lookup should find it.
    path = STDLIB.find_file("gui.btrc")
    assert path is not None and path.endswith("gui.btrc")


def test_cached_stdlib_decls_roundtrip(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache_dir))
    stdlib_src = "class Tiny { public int x; public Tiny(int x) { self.x = x; } }\n"
    first = STDLIB.cached_declarations(stdlib_src)
    assert first  # parsed
    cache_files = list(cache_dir.glob("stdlib-*.ast.json"))
    assert len(cache_files) == 1
    assert json.loads(cache_files[0].read_text())["schema"] == ast_cache.SCHEMA_VERSION

    def unexpected_parse(_self):
        raise AssertionError("cache hit reparsed the stdlib")

    monkeypatch.setattr(frontend_stdlib_owner.Parser, "parse", unexpected_parse)
    second = STDLIB.cached_declarations(stdlib_src)
    assert second == first


def test_lexer_error_cached_path(tmp_path, monkeypatch, capsys):
    """Lexer error on the default (ast-cache) path hits its own except arm."""
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "lec.btrc", 'int main() { string s = "oops;\n return 0; }\n')
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src])  # default flags → use_ast_cache path
    assert "error:" in capsys.readouterr().err


def test_parser_error_cached_path(tmp_path, monkeypatch, capsys):
    """Parser error on the default (ast-cache) path hits its own except arm."""
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "pec.btrc", "class { int x; }\n")
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src])
    assert "error:" in capsys.readouterr().err


def test_codegen_error_is_reported_without_a_traceback(tmp_path, monkeypatch, capsys):
    src = write(
        tmp_path / "unsupported_directive.btrc",
        "#undef UNSUPPORTED\nint main() { return 0; }\n",
    )
    with pytest.raises(SystemExit) as stopped:
        run_main(monkeypatch, ["--no-cache", "--no-stdlib", src])
    captured = capsys.readouterr()
    assert stopped.value.code == 1
    assert "unsupported preprocessor directive '#undef'" in captured.err
    assert "Traceback" not in captured.err


def test_cached_stdlib_decls_write_failure(tmp_path, monkeypatch):
    """A failed atomic cache write is swallowed; declarations still return."""
    monkeypatch.setenv("BTRC_CACHE_DIR", str(tmp_path / "cache"))

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(ast_cache, "atomic_write_json", boom)
    decls = STDLIB.cached_declarations("class TinyW { public int x; public TinyW(int x) { self.x = x; } }\n")
    assert decls


def test_cached_stdlib_decls_unavailable_cache_still_parses(monkeypatch):
    def unavailable():
        raise PermissionError("read-only cache root")

    monkeypatch.setattr(frontend_stdlib_owner, "resolve_cache_dir", unavailable)
    decls = STDLIB.cached_declarations("class Cacheless { public int x; public Cacheless() { self.x = 1; } }\n")
    assert decls


def test_disk_cache_write_failure_does_not_fail_compilation(tmp_path, monkeypatch):
    source = write(tmp_path / "cacheless.btrc", "int main() { return 0; }\n")
    output = tmp_path / "cacheless.c"

    class UnavailableCache:
        def load(self, *_args, **_kwargs):
            return None

        def store(self, *_args, **_kwargs):
            raise PermissionError("read-only cache root")

    CompilerCLI(Compiler(cache=UnavailableCache())).run(["--no-stdlib", source, "-o", str(output)])
    assert "int main(void)" in output.read_text()


def test_discover_stdlib_files_missing_dir():
    unavailable = StdlibRepository(directory="/no/such/stdlib/dir")
    assert unavailable.discover_files() == []


def test_get_stdlib_source_missing_listed_file(monkeypatch):
    monkeypatch.setattr(STDLIB, "discover_files", lambda: ["does_not_exist.btrc"])
    assert STDLIB.source("") == ""  # listed-but-absent file skipped


def test_resolve_include_via_stdlib(tmp_path):
    # No local math.btrc → #include resolves to the stdlib copy (line 186).
    src = '#include "math.btrc"\nint main() { return 0; }\n'
    p = write(tmp_path / "ms.btrc", src)
    resolved = RESOLVER.resolve_includes(src, p)
    assert "Math" in resolved


def test_import_relative_ghost(tmp_path, capsys):
    src = "import ./ghost_file.btrc;\nint main() { return 0; }\n"
    p = write(tmp_path / "g.btrc", src)
    with pytest.raises(SystemExit):
        RESOLVER.resolve_includes(src, p)
    assert "not found" in capsys.readouterr().err


def test_cached_stdlib_decls_corrupt_cache(tmp_path, monkeypatch):
    # Pin the cache dir so corrupt JSON is planted at the current cache path.
    cache_dir = tmp_path / ".btrc-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache_dir))
    stdlib_src = "class Tiny2 { public int x; public Tiny2(int x) { self.x = x; } }\n"
    path = STDLIB.ast_cache.path(
        str(cache_dir),
        STDLIB.ast_version,
        stdlib_src,
    )
    with open(path, "wb") as cache_file:
        cache_file.write(b"not valid JSON")
    decls = STDLIB.cached_declarations(stdlib_src)  # must reparse, not crash
    assert decls
    with open(path, encoding="utf-8") as cache_file:
        assert json.load(cache_file)["schema"] == ast_cache.SCHEMA_VERSION


def test_cached_stdlib_decls_never_executes_legacy_pickle(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    marker = tmp_path / "pickle-executed"

    class Exploit:
        def __reduce__(self):
            return os.mkdir, (str(marker),)

    legacy = cache_dir / "stdlib-malicious.ast"
    with open(legacy, "wb") as cache_file:
        pickle.dump(Exploit(), cache_file)
    monkeypatch.setenv("BTRC_CACHE_DIR", str(cache_dir))

    decls = STDLIB.cached_declarations("class Safe { public int x; public Safe() { self.x = 0; } }\n")

    assert decls and not marker.exists()
    assert not legacy.exists()
    assert list(cache_dir.glob("stdlib-*.ast.json"))
