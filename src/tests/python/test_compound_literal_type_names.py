"""C object type names distinguish array storage from btrc's T[] type spelling."""

import pytest

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError, Parser
from src.compiler.python.syntax.ast.generated import BinaryExpr, IntLiteral
from src.compiler.python.syntax.tokens import TokenKind


def parse_type_name(source):
    parser = Parser(Lexer("(" + source + ")").tokenize())
    parser._expect(TokenKind.LPAREN)
    result = parser._parse_type_name()
    end = parser.pos
    assert parser._scan_type_name(1) == end
    assert parser.pos == end
    parser._expect(TokenKind.RPAREN)
    parser._expect(TokenKind.EOF)
    return result


@pytest.mark.parametrize(
    ("source", "base", "pointers", "array", "bound"),
    [
        ("int", "int", 0, False, None),
        ("struct Point", "struct Point", 0, False, None),
        ("union Value*", "union Value", 1, False, None),
        ("int[]", "int", 0, True, None),
        ("int[3]", "int", 0, True, 3),
        ("int*[]", "int", 1, True, None),
        ("int**[4]", "int", 2, True, 4),
        ("Number[2]", "Number", 0, True, 2),
    ],
)
def test_c_type_name_storage_shape(source, base, pointers, array, bound):
    result = parse_type_name(source)
    assert (result.base, result.pointer_depth, result.is_array) == (base, pointers, array)
    assert (result.line, result.col) == (1, 2)
    if bound is None:
        assert result.array_size is None
    else:
        assert isinstance(result.array_size, IntLiteral)
        assert result.array_size.value == bound


def test_array_bound_remains_an_expression_for_the_constant_owner():
    result = parse_type_name("int[1 + 2]")
    assert isinstance(result.array_size, BinaryExpr)
    assert result.array_size.op == "+"
    assert (result.array_size.left.value, result.array_size.right.value) == (1, 2)


def test_pointer_qualifiers_stay_inside_array_storage():
    result = parse_type_name("const int?[]")
    assert result.is_const and result.is_nullable and result.is_array
    assert result.pointer_depth == 1
    assert result.nullable_outer_depth == 1


def test_abstract_callback_type_uses_the_existing_declarator_owner():
    result = parse_type_name("int (*)(const char*)")
    assert result.base == "__fn_ptr"
    assert not result.is_array
    assert [argument.base for argument in result.generic_args] == ["int", "char"]
    assert result.generic_args[1].is_const
    assert result.generic_args[1].pointer_depth == 1


@pytest.mark.parametrize("source", ["int[][2]", "int[2][3]", "int[]*", "int (*named)(int)"])
def test_type_name_refuses_unrepresented_or_named_declarators(source):
    with pytest.raises(ParseError):
        parse_type_name(source)


def test_ordinary_btrc_array_type_spelling_keeps_its_parse():
    parser = Parser(Lexer("int[]*").tokenize())
    result = parser._parse_type_expr()
    parser._expect(TokenKind.EOF)
    assert result.base == "int" and result.is_array and result.pointer_depth == 1
    assert result.array_size is None


@pytest.mark.parametrize("source", ["42", "int[", "int[(2)"])
def test_type_name_lookahead_stops_on_non_types_and_unclosed_bounds(source):
    parser = Parser(Lexer(source).tokenize())
    assert parser._scan_type_name(0) is None
    assert parser.pos == 0


def test_type_name_lookahead_preserves_the_multi_dimension_refusal():
    parser = Parser(Lexer("int[2][3])").tokenize())
    end = parser._scan_type_name(0)
    assert end is not None and parser.tokens[end].type == TokenKind.RPAREN
    assert parser.pos == 0
