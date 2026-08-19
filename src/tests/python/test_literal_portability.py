"""Strict-C literal spelling and fail-closed lexer contracts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.ir.lowering.types import CTypeLowerer
from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.syntax.tokens import TokenKind

COMPILERS = [path for name in ("gcc", "clang") if (path := shutil.which(name))]


@pytest.mark.parametrize(
    "source",
    [
        r'"plain\a\b\f\n\r\t\v\?\'\"\\"',
        r'"\0\123\377"',
        r'"\x41g\x000ff"',
        r'"\u0024\u00a0\u03a9\U0001F600"',
        r'"""triple\n\u03a9"""',
        r'f"format\t\u03a9"',
        '"line\\\ncontinued"',
        '"line\\\r\ncontinued"',
        'f"line\\\ncontinued"',
    ],
)
def test_portable_string_escape_forms_are_preserved(source: str):
    tokens = Lexer(source, "<literal>").tokenize()

    assert tokens[-1].type is TokenKind.EOF
    assert tokens[0].type in {TokenKind.STRING_LIT, TokenKind.FSTRING_LIT}


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (r'"\q"', r"Invalid escape sequence '\q' in string literal"),
        (r'"""\q"""', r"Invalid escape sequence '\q' in string literal"),
        (r'f"\q"', r"Invalid escape sequence '\q' in f-string literal"),
        (r'"\8"', r"Invalid escape sequence '\8' in string literal"),
        ('"\\é"', "Invalid non-ASCII escape in string literal"),
        (r'"\x"', "Hex escape sequence requires digits in string literal"),
        (r'"\x100"', "Hex escape sequence out of range in string literal"),
        (r'"\400"', "Octal escape sequence out of range in string literal"),
        (r'"\u123"', "Invalid universal character escape in string literal"),
        (r'"\u0041"', "Invalid universal character escape in string literal"),
        (r'"\ud800"', "Invalid universal character escape in string literal"),
        (r'"\U00110000"', "Invalid universal character escape in string literal"),
        ('"raw\rcarriage"', "Unterminated string literal"),
        ('f"raw\rcarriage"', "Unterminated f-string literal"),
        ('"splice\\\rcarriage"', "Unterminated string literal"),
    ],
)
def test_nonportable_string_escape_forms_fail_at_lexer(
    source: str,
    message: str,
):
    with pytest.raises(LexerError, match=message.replace("\\", r"\\")) as exc:
        Lexer(source, "<literal>").tokenize()

    assert (exc.value.line, exc.value.col) == (1, 1)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("123abc", "Invalid numeric literal '123abc'"),
        ("0x1g", "Invalid numeric literal '0x1g'"),
        ("0x1p2", "Invalid numeric literal '0x1p2'"),
        ("0b102", "Invalid digit '2' in binary literal"),
        ("0o78", "Invalid digit '8' in octal literal"),
        ("09", "Invalid digit '9' in octal literal"),
        ("1uu", "Invalid integer suffix 'uu'"),
        ("1lll", "Invalid integer suffix 'lll'"),
        ("1lL", "Invalid integer suffix 'lL'"),
        ("1f", "Invalid numeric literal '1f'"),
        ("1.0ff", "Invalid numeric literal '1.0ff'"),
        ("1.0u", "Invalid numeric literal '1.0u'"),
        ("1e2L", "Invalid numeric literal '1e2L'"),
        ("1_value", "Invalid numeric literal '1_value'"),
        ("1é", "Unexpected non-ASCII character"),
    ],
)
def test_invalid_numeric_token_boundaries_fail_at_lexer(
    source: str,
    message: str,
):
    with pytest.raises(LexerError, match=message):
        Lexer(source, "<literal>").tokenize()


def test_failed_python_scan_is_sticky_and_discards_its_valid_prefix():
    lexer = Lexer("int valid = 1; int broken = 09", "<literal>")

    with pytest.raises(LexerError) as first_failure:
        lexer.tokenize()

    assert lexer.tokens == []
    with pytest.raises(LexerError) as repeated_failure:
        lexer.tokenize()
    assert repeated_failure.value is first_failure.value
    assert lexer.tokens == []


def test_successful_python_scan_is_idempotent():
    lexer = Lexer("int value = 1;", "<literal>")

    first = lexer.tokenize()
    second = lexer.tokenize()

    assert second is first
    assert sum(token.type is TokenKind.EOF for token in second) == 1


@pytest.mark.parametrize("source", ["é", "nameé"])
def test_identifiers_are_ascii_as_specified_by_the_grammar(source: str):
    with pytest.raises(LexerError, match="Unexpected non-ASCII character"):
        Lexer(source, "<literal>").tokenize()


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_line_splice_updates_following_token_position(newline: str):
    tokens = Lexer(f'"left\\{newline}right" int', "<literal>").tokenize()

    assert tokens[0].type is TokenKind.STRING_LIT
    assert tokens[1].type is TokenKind.INT
    assert tokens[1].line == 2


def test_integer_grammar_excludes_invalid_leading_zero_decimal():
    grammar = (Path(__file__).parents[3] / "src/language/grammar.ebnf").read_text()
    integer_spec = grammar.split("INT_LIT", 1)[1].split("FLOAT_LIT", 1)[0]

    assert "| /0(" in integer_spec
    assert "| /0[0-7]+" in integer_spec
    assert "| /[1-9][0-9]*" in integer_spec
    assert "| /[0-9]+" not in integer_spec


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_accepted_string_tokens_compile_as_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    sources = [
        r'"simple\n\t\\\""',
        r'"\0\123\377\x000ff"',
        r'"\u0024\u00a0\u03a9\U0001F600"',
        '"line\\\ncontinued"',
        '"line\\\r\ncontinued"',
        r'f"format\t\u03a9"',
    ]
    declarations = []
    for index, source in enumerate(sources):
        token = Lexer(source, "<literal>").tokenize()[0]
        literal = token.value
        if token.type is TokenKind.FSTRING_LIT:
            literal = f'"{literal}"'
        declarations.append(f"static const char *value_{index} = {literal};")
    for index, source in enumerate((r"'\377'", r"'\x000041'")):
        token = Lexer(source, "<literal>").tokenize()[0]
        assert token.type is TokenKind.CHAR_LIT
        declarations.append(f"static const unsigned char char_{index} = {token.value};")
    c_file = tmp_path / "strings.c"
    c_file.write_text("\n".join((*declarations, "int main(void) { return 0; }")))

    result = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-fsyntax-only",
            str(c_file),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_accepted_numeric_tokens_lower_to_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    integers = [
        ("42u", 42),
        ("42UL", 42),
        ("42LLu", 42),
        ("0x2aULL", 42),
        ("0123", 0o123),
        ("0b101u", 5),
        ("0o17UL", 15),
    ]
    declarations = []
    for index, (raw, value) in enumerate(integers):
        token = Lexer(raw, "<literal>").tokenize()[0]
        assert token.type is TokenKind.INT_LIT
        spelling = CTypeLowerer.format_c_integer_literal(raw, value)
        declarations.append(f"static const unsigned long long value_{index} = {spelling};")
    for index, raw in enumerate(("1.5", "1.5e2F")):
        token = Lexer(raw, "<literal>").tokenize()[0]
        assert token.type is TokenKind.FLOAT_LIT
        declarations.append(f"static const double float_{index} = {raw};")
    c_file = tmp_path / "numbers.c"
    c_file.write_text("\n".join((*declarations, "int main(void) { return 0; }")))

    result = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-fsyntax-only",
            str(c_file),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
