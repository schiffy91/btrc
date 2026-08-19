"""Extra lexer-literal coverage: CR/CRLF in triple-quoted strings, the full
set of integer suffixes, and unterminated char / f-string errors."""

import pytest

from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.syntax.tokens import TokenKind


def toks(src):
    return Lexer(src, "<t>").tokenize()


def first(src, kind):
    for t in toks(src):
        if t.type == kind:
            return t
    raise AssertionError(f"no {kind} token in {src!r}")


# --- triple-quoted strings with carriage returns (lines 36-40) ---


def test_triple_quoted_with_cr():
    t = first('"""a\rb"""', TokenKind.STRING_LIT)
    assert "a" in t.value and "b" in t.value


def test_triple_quoted_with_crlf():
    t = first('"""a\r\nb"""', TokenKind.STRING_LIT)
    assert "b" in t.value


# --- unterminated literals ---


def test_unterminated_char():
    with pytest.raises(LexerError):
        toks("'a")  # no closing quote → line 88


def test_fstring_literal_newline():
    with pytest.raises(LexerError):
        toks('f"abc\n"')  # raw newline inside f-string → line 206


def test_fstring_unterminated():
    with pytest.raises(LexerError):
        toks('f"abc')  # EOF before close → line 209


# --- integer suffixes (lines 214-230) ---


@pytest.mark.parametrize(
    "lit",
    ["1u", "1U", "1ul", "1ull", "1l", "1L", "1ll", "1llu", "1lu", "2UL", "3ULL"],
)
def test_integer_suffixes(lit):
    t = first(lit + ";", TokenKind.INT_LIT)
    assert t.value == lit
