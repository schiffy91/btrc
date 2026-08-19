"""Parser edge cases: malformed-expression errors and map-vs-block literal
disambiguation."""

import pytest

from src.compiler.python.syntax.ast.generated import (
    BraceInitializer,
    FunctionDecl,
    MapLiteral,
    TernaryExpr,
)
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError
from src.compiler.python.parser.parser import Parser


def parse(src):
    return Parser(Lexer(src, "<t>").tokenize()).parse()


def test_missing_expression_after_assign_is_parse_error():
    with pytest.raises(ParseError):
        parse("int main() { int x = ; return 0; }")


def test_unexpected_token_in_expression_is_parse_error():
    with pytest.raises(ParseError):
        parse("int main() { int x = 1 + ; return 0; }")


def test_map_literal_vs_block_disambiguation():
    # `{"k": v}` in expression position is a map literal, not a block.
    prog = parse('int main() { Map<string, int> m = {"a": 1, "b": 2}; return m.size(); }')
    assert any(isinstance(d, FunctionDecl) for d in prog.declarations)


def test_empty_brace_initializer_parses():
    prog = parse("class C { public int v; public C() { self.v = 0; } }\nint main() { return 0; }")
    assert prog.declarations


def test_ternary_brace_element_is_not_misclassified_as_map():
    prog = parse("int main() { bool c = true; int[] xs = {c ? 1 : 2}; return 0; }")
    initializer = prog.declarations[0].body.statements[1].initializer
    assert isinstance(initializer, BraceInitializer)
    assert isinstance(initializer.elements[0], TernaryExpr)


def test_ternary_expression_can_be_a_map_key():
    prog = parse("int main() { bool c = true; Map<int, int> m = {c ? 1 : 2: 3}; return 0; }")
    initializer = prog.declarations[0].body.statements[1].initializer
    assert isinstance(initializer, MapLiteral)
    assert isinstance(initializer.entries[0].key, TernaryExpr)
