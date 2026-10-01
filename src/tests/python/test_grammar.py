"""The EBNF grammar loader: operator token naming, brace-block extraction,
@lexical parsing, and the cached GrammarRepository snapshot."""

import pytest

import src.compiler.python.syntax.grammar as ebnf

GRAMMAR_PARSER = ebnf.EbnfGrammarParser()


def test_op_to_token_name_single_unknown():
    with pytest.raises(ValueError):
        GRAMMAR_PARSER.operator_token_name("§")


def test_op_to_token_name_multi_unknown():
    with pytest.raises(ValueError):
        GRAMMAR_PARSER.operator_token_name("+§")  # multi-char with an unknown component


def test_op_to_token_name_known():
    assert GRAMMAR_PARSER.operator_token_name("+=") == "PLUS_EQ"
    assert GRAMMAR_PARSER.operator_token_name("->") == "ARROW"


def test_extract_brace_block_missing_marker():
    assert GRAMMAR_PARSER.extract_brace_block("nothing here", "@nope") is None


def test_extract_brace_block_unbalanced():
    assert GRAMMAR_PARSER.extract_brace_block("@x { unbalanced", "@x") is None


def test_extract_brace_block_with_comments_and_strings():
    body = GRAMMAR_PARSER.extract_brace_block('@x { -- line comment\n (* block *) "a" /regex/ }', "@x")
    assert '"a"' in body


def test_parse_grammar_no_lexical():
    with pytest.raises(ValueError):
        GRAMMAR_PARSER.parse("no lexical section here")


def test_parse_grammar_minimal():
    info = GRAMMAR_PARSER.parse('@lexical { @keywords { if while } @operators { "+" "==" } @annotations { gpu } }')
    assert "if" in info.keywords and "while" in info.keywords
    assert "+" in info.operators and "==" in info.operators
    assert "gpu" in info.annotations
    assert info.op_to_token["+"] == "PLUS"


def test_extract_brace_block_escapes():
    # Escaped quote inside a string and escaped slash inside a regex.
    body = GRAMMAR_PARSER.extract_brace_block(r'@x { "a\"b" /a\/b/ }', "@x")
    assert body is not None


def test_grammar_repository_loads_real_grammar_once():
    repository = ebnf.GrammarRepository.canonical()
    info = repository.load()
    assert "class" in info.keywords
    assert repository.load() is info  # cached by this explicit owner


def test_grammar_repository_does_not_publish_a_failed_snapshot(tmp_path):
    grammar_path = tmp_path / "grammar.ebnf"
    grammar_path.write_text("malformed")
    repository = ebnf.GrammarRepository(str(grammar_path))

    with pytest.raises(ValueError):
        repository.load()

    grammar_path.write_text('@lexical { @keywords { class } @operators { "+" } }')
    assert repository.load().keywords == frozenset({"class"})
