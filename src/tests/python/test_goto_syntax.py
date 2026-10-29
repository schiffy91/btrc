"""Source syntax and end-to-end execution for function-local jumps."""

import subprocess

import pytest

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError, Parser
from src.compiler.python.syntax.ast.generated import GotoStmt, LabelStmt, VarDeclStmt
from src.tests.c_toolchains import configured_c_compiler, requires_host_c_compiler
from src.tests.python.test_jump_lowering import _emit


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def test_label_and_target_positions():
    body = parse("void f() {\n  goto done;\n  done:\n}").declarations[0].body
    jump, label = body.statements
    assert isinstance(jump, GotoStmt) and isinstance(label, LabelStmt)
    assert (jump.name, jump.line, jump.col, jump.name_line, jump.name_col) == ("done", 2, 3, 2, 8)
    assert (label.name, label.line, label.col) == ("done", 3, 3)


def test_consecutive_labels_before_declaration_and_at_end():
    statements = parse("void f() { first: second: int value = 1; last: }").declarations[0].body.statements
    assert [type(item) for item in statements] == [LabelStmt, LabelStmt, VarDeclStmt, LabelStmt]


@pytest.mark.parametrize("header", ["if (true)", "while (false)", "for (;;)"])
def test_braceless_labels_keep_body_position_and_empty_statement(header):
    body = parse(f"void f() {{ {header} first: second: ; }}").declarations[0].body.statements[0]
    body = getattr(body, "then_block", None) or body.body
    assert [item.name for item in body.statements] == ["first", "second"]
    assert (body.line, body.col) == (body.statements[0].line, body.statements[0].col)


@pytest.mark.parametrize(
    ("source", "message", "token"),
    [
        ("void f() { goto; }", "Expected IDENT, got SEMICOLON ';'", ";"),
        ("void f() { goto new; }", "'new' is a reserved word and cannot be used as a name", "new"),
        ("void f() { return: ; }", "'return' is a reserved word and cannot be used as a name", "return"),
        ("void f() { int: ; }", "'int' is a reserved word and cannot be used as a name", "int"),
        ("void f() { _Atomic: ; }", "C11 '_Atomic' is not supported", "_Atomic"),
        ("void f() { if (true) done: }", "Expected a statement after label 'done'", "}"),
        ("void f() { if (true) done: int value; }", "A declaration cannot be the body", "int"),
    ],
)
def test_targeted_parse_errors(source, message, token):
    with pytest.raises(ParseError) as failure:
        parse(source)
    assert str(failure.value).startswith(message)
    assert (failure.value.line, failure.value.col) == (1, source.index(token) + 1)


@pytest.mark.parametrize(
    "source",
    [
        "int main() { goto done; done: return 0; }",
        "int main() { int n = 0; again: n++; if (n < 3) goto again; return n - 3; }",
        "int main() { { goto done; } done: return 0; }",
        "int main() { var run = () => { goto done; done: return 0; }; goto done; done: return run(); }",
        "int main() { switch (1) { case 1: goto done; done: case 2: break; } return 0; }",
    ],
)
@requires_host_c_compiler
def test_source_goto_runs_as_strict_c11(source, tmp_path):
    c_source = tmp_path / "goto.c"
    c_source.write_text(_emit(source))
    executable = tmp_path / "goto"
    result = subprocess.run(
        [
            *configured_c_compiler(),
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(c_source),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("keyword", ["var", "auto", "register", "if", "goto", "new"])
@pytest.mark.parametrize("prefix", ["", "if (true) "])
def test_keyword_label_uses_reserved_name_error(keyword, prefix):
    with pytest.raises(ParseError, match=f"'{keyword}' is a reserved word and cannot be used as a name"):
        parse(f"void f() {{ {prefix}{keyword}: ; }}")
