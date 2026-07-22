"""CLI diagnostic positions: errors must point at the originating file's
native line/col and quote that file's source line, identically in both cache
modes (default stdlib-AST cache and --no-cache combined-source parse)."""

import pytest

from src.compiler.python.analyzer.core import Diag
from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.cli.compiler_cli import CompilerCLI

MODES = pytest.mark.parametrize("mode", [[], ["--no-cache"]], ids=["default", "no-cache"])


@pytest.fixture(scope="module")
def workdir(tmp_path_factory):
    """Shared cwd for compile outputs (the stdlib AST cache itself is shared
    session-wide via the conftest BTRC_CACHE_DIR fixture)."""
    return tmp_path_factory.mktemp("cli_diag_work")


def write(path, content):
    path.write_text(content)
    return str(path)


def compile_err(monkeypatch, capsys, workdir, argv):
    """Drive main() in-process, expect failure, return stderr."""
    monkeypatch.chdir(workdir)
    with pytest.raises(SystemExit):
        CompilerCLI().run([*argv, "-o", "/dev/null"])
    return capsys.readouterr().err


ANALYZER_BAD = 'int main() {\n    int x = "hello";\n    return 0;\n}\n'


# --------------------------------------------------------------------------
# (a) analyzer errors: native position + quoted line from the right file
# --------------------------------------------------------------------------


@MODES
def test_analyzer_error_native_position(tmp_path, monkeypatch, capsys, workdir, mode):
    src = write(tmp_path / "t.btrc", ANALYZER_BAD)
    err = compile_err(monkeypatch, capsys, workdir, [src] + mode)
    assert "Cannot assign 'string'" in err
    assert f"--> {src}:2:5" in err
    assert 'int x = "hello";' in err  # quoted from the user file...
    assert "Dynamic array" not in err  # ...not from the stdlib-prefixed source
    assert ":5171" not in err  # no combined-source line numbers


def test_analyzer_error_identical_across_modes(tmp_path, monkeypatch, capsys, workdir):
    src = write(tmp_path / "same.btrc", ANALYZER_BAD)
    default_err = compile_err(monkeypatch, capsys, workdir, [src])
    no_cache_err = compile_err(monkeypatch, capsys, workdir, [src, "--no-cache"])
    assert default_err == no_cache_err


# --------------------------------------------------------------------------
# (b) messages containing " at " are not corrupted by position parsing
# --------------------------------------------------------------------------


def test_message_containing_at_survives(tmp_path, monkeypatch, capsys, workdir):
    src = write(tmp_path / "at.btrc", "int main() { return 0; }\n")
    msg = "variable shadows a parameter declared at 3:1"
    real = SemanticAnalyzer.analyze

    def fake(self, program):
        result = real(self, program)
        result.errors.append(msg)  # raw, the way string-parsing used to corrupt
        result.diags.append(Diag(msg, 1, 5, "error", None))
        return result

    monkeypatch.setattr(SemanticAnalyzer, "analyze", fake)
    err = compile_err(monkeypatch, capsys, workdir, [src])
    assert msg in err  # full message intact, " at 3:1" tail not stripped
    assert f"--> {src}:1:5" in err  # position comes from the Diag, not the text


def test_warning_diag_native_position(tmp_path, monkeypatch, capsys, workdir):
    src = write(tmp_path / "w.btrc", 'int main() { print("OK"); return 0; }\n')
    real = SemanticAnalyzer.analyze

    def fake(self, program):
        result = real(self, program)
        result.warnings.append("suspicious cast at 1:14")
        result.diags.append(Diag("suspicious cast", 1, 14, "warning", None))
        return result

    monkeypatch.setattr(SemanticAnalyzer, "analyze", fake)
    monkeypatch.chdir(workdir)
    # Default (split-space) mode: injected diag lines are user-source native.
    CompilerCLI().run([src, "-o", "/dev/null"])  # warnings do not abort
    err = capsys.readouterr().err
    assert f"warning: suspicious cast\n  --> {src}:1:14" in err


# --------------------------------------------------------------------------
# (c) lexer and parser errors: native positions in both modes
# --------------------------------------------------------------------------


@MODES
def test_lexer_error_native_position(tmp_path, monkeypatch, capsys, workdir, mode):
    src = write(tmp_path / "lex.btrc", "int main() {\n    int x = @;\n    return 0;\n}\n")
    err = compile_err(monkeypatch, capsys, workdir, [src] + mode)
    assert f"--> {src}:2:13" in err and "int x = @;" in err
    assert ":5171" not in err


@MODES
def test_parse_error_native_position(tmp_path, monkeypatch, capsys, workdir, mode):
    src = write(tmp_path / "parse.btrc", "int main() {\n    int x = ;\n    return 0;\n}\n")
    err = compile_err(monkeypatch, capsys, workdir, [src] + mode)
    assert f"--> {src}:2:13" in err and "int x = ;" in err
    assert ":5171" not in err


# --------------------------------------------------------------------------
# (d) errors in imported files name the imported file at its native line
# --------------------------------------------------------------------------


def _two_file_project(tmp_path):
    helper = write(
        tmp_path / "helper.btrc",
        'class Helper {\n    public int bad() {\n        int y = "oops";\n        return y;\n    }\n}\n',
    )
    app = write(
        tmp_path / "app.btrc", "import ./helper.btrc\n\nint main() {\n    Helper h = new Helper();\n    return 0;\n}\n"
    )
    return helper, app


@MODES
def test_error_in_imported_file(tmp_path, monkeypatch, capsys, workdir, mode):
    helper, app = _two_file_project(tmp_path)
    err = compile_err(monkeypatch, capsys, workdir, [app] + mode)
    assert f"--> {helper}:3:9" in err  # the imported file, its native line
    assert 'int y = "oops";' in err
    assert "app.btrc:3" not in err


@MODES
def test_error_in_main_file_after_import(tmp_path, monkeypatch, capsys, workdir, mode):
    """Import expansion shifts resolved-source lines; positions stay native."""
    write(tmp_path / "helper.btrc", "class Helper {\n    public int ok() {\n        return 1;\n    }\n}\n")
    app = write(
        tmp_path / "app.btrc",
        'import ./helper.btrc\n\nint main() {\n    Helper h = new Helper();\n    int z = "bad";\n    return 0;\n}\n',
    )
    err = compile_err(monkeypatch, capsys, workdir, [app] + mode)
    assert f"--> {app}:5:5" in err  # not the import-shifted line 9/5175
    assert 'int z = "bad";' in err
