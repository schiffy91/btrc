"""Tests for the compiler driver (main.py): CLI flags, include/import
resolution, stdlib selection, error formatting, and IR dumping."""

import hashlib
import os
import shutil
import subprocess
import sys

import pytest

from src.compiler.python import frontend as fe
from src.compiler.python import main as m

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def write(path, content):
    with open(path, "w") as f:
        f.write(content)
    return str(path)


def run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["btrc"] + argv)
    m.main()


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
    src = write(tmp_path / "t.btrc",
                "enum Color { RED, GREEN = 5 };\n"
                "struct Point { int x; int y; };\n"
                "int add(int a, int b) { return a + b; }\n"
                "int main() { return add(1, 2); }\n")
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


def test_no_runtime(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "nr.btrc", BARE)
    run_main(monkeypatch, [src, "--no-runtime", "-o", str(tmp_path / "nr.c")])
    assert os.path.exists(tmp_path / "nr.c")


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
    run_main(monkeypatch, [src, "--profile", "-o", str(tmp_path / "p.c")])
    err = capsys.readouterr().err
    assert "btrc profile" in err
    assert "total" in err


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
    src = write(tmp_path / "ae.btrc",
                "class Box { private int x; public Box() { self.x = 0; } }\n"
                "int main() { Box b = Box(); return b.x; }\n")  # private field access
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src, "--no-cache"])
    assert "error:" in capsys.readouterr().err


def test_analyzer_error_fallback_format(tmp_path, monkeypatch, capsys):
    """An analyzer error without a ' at line:col' suffix uses the plain branch."""
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "af.btrc", BARE)

    real = m.Analyzer.analyze

    def fake(self, program):
        result = real(self, program)
        result.errors.append("a bare error with no location")
        return result

    monkeypatch.setattr(m.Analyzer, "analyze", fake)
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src, "--no-cache"])
    assert "a bare error with no location" in capsys.readouterr().err


def test_analyzer_error_bad_location(tmp_path, monkeypatch, capsys):
    """A ' at x:y' suffix with non-integer coords falls through to plain print."""
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "ab.btrc", BARE)
    real = m.Analyzer.analyze

    def fake(self, program):
        result = real(self, program)
        result.errors.append("bad loc at foo:bar")
        return result

    monkeypatch.setattr(m.Analyzer, "analyze", fake)
    with pytest.raises(SystemExit):
        run_main(monkeypatch, [src, "--no-cache"])
    assert "bad loc" in capsys.readouterr().err


def test_analyzer_warning(tmp_path, monkeypatch, capsys):
    """Warnings are printed (with and without location) but do not abort."""
    monkeypatch.chdir(tmp_path)
    src = write(tmp_path / "w.btrc", HELLO)
    real = m.Analyzer.analyze

    def fake(self, program):
        result = real(self, program)
        result.warnings.append("located warning at 1:1")
        result.warnings.append("plain warning no loc")
        result.warnings.append("bad warning at x:y")
        return result

    monkeypatch.setattr(m.Analyzer, "analyze", fake)
    run_main(monkeypatch, [src, "--no-cache", "-o", str(tmp_path / "w.c")])
    err = capsys.readouterr().err
    assert "warning:" in err
    assert os.path.exists(tmp_path / "w.c")


# --------------------------------------------------------------------------
# _format_error
# --------------------------------------------------------------------------

def test_format_error_normal():
    out = m._format_error("line one\nline two\n", "f.btrc", "boom", 2, 3)
    assert "boom" in out and "f.btrc:2:3" in out and "line two" in out and "^" in out


def test_format_error_out_of_range():
    out = m._format_error("only line\n", "f.btrc", "boom", 99, 1)
    assert out == "error: boom\n --> f.btrc:99:1"
    out2 = m._format_error("x", "f.btrc", "boom", 0, 1)
    assert "--> f.btrc:0:1" in out2


# --------------------------------------------------------------------------
# include / import resolution
# --------------------------------------------------------------------------

def test_resolve_hash_include(tmp_path):
    write(tmp_path / "lib.btrc", "int helper() { return 7; }\n")
    main_src = '#include "lib.btrc"\nint main() { return helper(); }\n'
    p = write(tmp_path / "m.btrc", main_src)
    resolved = m.resolve_includes(main_src, p)
    assert "int helper" in resolved


def test_resolve_missing_include(tmp_path, capsys):
    main_src = '#include "ghost.btrc"\nint main() { return 0; }\n'
    p = write(tmp_path / "m.btrc", main_src)
    with pytest.raises(SystemExit):
        m.resolve_includes(main_src, p)
    assert "not found" in capsys.readouterr().err


def test_resolve_circular_include(tmp_path):
    a = tmp_path / "a.btrc"
    b = tmp_path / "b.btrc"
    a.write_text('#include "b.btrc"\nint a() { return 1; }\n')
    b.write_text('#include "a.btrc"\nint b() { return 2; }\n')
    resolved = m.resolve_includes(a.read_text(), str(a))
    assert "int a" in resolved and "int b" in resolved  # no infinite loop


def test_import_stdlib_single(tmp_path):
    src = "import std.math;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "class Math" in resolved or "Math" in resolved


def test_import_stdlib_brace(tmp_path):
    src = "import std.{math, json};\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "Math" in resolved and "Json" in resolved


def test_import_stdlib_glob(tmp_path):
    src = "import std.*;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "class Vector" in resolved


def test_import_stdlib_not_found(tmp_path, capsys):
    src = "import std.nonexistent_module;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    with pytest.raises(SystemExit):
        m.resolve_includes(src, p)
    assert "not found" in capsys.readouterr().err


def test_import_relative_file(tmp_path):
    write(tmp_path / "rel.btrc", "int rel() { return 1; }\n")
    src = "import ./rel.btrc;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "int rel" in resolved


def test_import_relative_quoted(tmp_path):
    write(tmp_path / "rel.btrc", "int relq() { return 1; }\n")
    src = 'import "./rel.btrc";\nint main() { return 0; }\n'
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "int relq" in resolved


def test_import_directory_direct_glob(tmp_path):
    d = tmp_path / "mods"
    d.mkdir()
    write(d / "one.btrc", "int one() { return 1; }\n")
    write(d / "two.btrc", "int two() { return 2; }\n")
    src = "import ./mods/*;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "int one" in resolved and "int two" in resolved


def test_import_directory_recursive_glob(tmp_path):
    d = tmp_path / "deep" / "nested"
    d.mkdir(parents=True)
    write(d / "x.btrc", "int deepx() { return 1; }\n")
    src = "import ./deep/**;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "int deepx" in resolved


def test_import_directory_not_found(tmp_path, capsys):
    src = "import ./missing_dir/*;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    with pytest.raises(SystemExit):
        m.resolve_includes(src, p)
    assert "not found" in capsys.readouterr().err


def test_import_plain_directory(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    write(d / "a.btrc", "int plaina() { return 1; }\n")
    src = "import ./plain;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "int plaina" in resolved


def test_import_c_file(tmp_path):
    write(tmp_path / "native.c", "int native(void) { return 1; }\n")
    src = "import ./native.c;\nint main() { return 0; }\n"
    p = write(tmp_path / "m.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert '#include "' in resolved and "native.c" in resolved


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def test_strip_import_quotes():
    assert m._strip_import_quotes('  "std.math" ;') == "std.math"
    assert m._strip_import_quotes("std.math;") == "std.math"
    assert m._strip_import_quotes("std.math") == "std.math"


def test_expand_brace_import():
    assert m._expand_brace_import("std.{a, b}") == ["std.a", "std.b"]
    assert m._expand_brace_import("std.math") == ["std.math"]
    assert m._expand_brace_import("std.{}") == []  # empty braces


def test_discover_stdlib_files():
    files = m._discover_stdlib_files()
    assert files[0] == "vector.btrc"  # foundation first
    assert "strings.btrc" in files


def test_get_stdlib_source_skips_redefined():
    # User redefining Vector means vector.btrc is skipped → shorter output.
    full = m.get_stdlib_source("")
    skipped = m.get_stdlib_source("class Vector<T> { public int len; }\n")
    assert len(skipped) < len(full)


def test_get_stdlib_source_skips_redefined_interface():
    skipped = m.get_stdlib_source("interface Iterable<T> { bool hasNext(); }\n")
    assert "interface Iterable" not in skipped


def test_find_stdlib_file_subdir():
    # gui/gui.btrc lives in a subdirectory; basename lookup should find it.
    path = m._find_stdlib_file("gui.btrc")
    assert path is not None and path.endswith("gui.btrc")


def test_cached_stdlib_decls_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stdlib_src = "class Tiny { public int x; public Tiny(int x) { self.x = x; } }\n"
    first = m._cached_stdlib_decls(stdlib_src)
    assert first  # parsed
    # Second call reads the pickle.
    second = m._cached_stdlib_decls(stdlib_src)
    assert len(second) == len(first)


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


def test_cached_stdlib_decls_write_failure(tmp_path, monkeypatch):
    """A failed pickle write is swallowed; decls still return."""
    monkeypatch.chdir(tmp_path)

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(fe.pickle, "dump", boom)
    decls = m._cached_stdlib_decls(
        "class TinyW { public int x; public TinyW(int x) { self.x = x; } }\n")
    assert decls


def test_discover_stdlib_files_missing_dir(monkeypatch):
    monkeypatch.setattr(fe, "_get_stdlib_dir", lambda: "/no/such/stdlib/dir")
    assert m._discover_stdlib_files() == []


def test_get_stdlib_source_missing_listed_file(monkeypatch):
    monkeypatch.setattr(fe, "_discover_stdlib_files", lambda: ["does_not_exist.btrc"])
    assert m.get_stdlib_source("") == ""  # listed-but-absent file skipped


def test_resolve_include_via_stdlib(tmp_path):
    # No local math.btrc → #include resolves to the stdlib copy (line 186).
    src = '#include "math.btrc"\nint main() { return 0; }\n'
    p = write(tmp_path / "ms.btrc", src)
    resolved = m.resolve_includes(src, p)
    assert "Math" in resolved


def test_import_relative_ghost(tmp_path, capsys):
    src = "import ./ghost_file.btrc;\nint main() { return 0; }\n"
    p = write(tmp_path / "g.btrc", src)
    with pytest.raises(SystemExit):
        m.resolve_includes(src, p)
    assert "not found" in capsys.readouterr().err


def test_cached_stdlib_decls_corrupt_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    stdlib_src = "class Tiny2 { public int x; public Tiny2(int x) { self.x = x; } }\n"
    key = hashlib.sha256(
        f"astv{m._STDLIB_AST_VERSION}\n{stdlib_src}".encode()
    ).hexdigest()
    cache_dir = tmp_path / ".btrc-cache"
    cache_dir.mkdir()
    (cache_dir / f"stdlib-{key}.ast").write_bytes(b"not a valid pickle")
    decls = m._cached_stdlib_decls(stdlib_src)  # must reparse, not crash
    assert decls
