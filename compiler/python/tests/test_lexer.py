"""Tests for the btrc lexer."""

import pytest
from compiler.python.lexer import Lexer, LexerError
from compiler.python.tokens import TokenType


def lex(source: str) -> list:
    return Lexer(source).tokenize()


def types(source: str) -> list[TokenType]:
    return [t.type for t in lex(source)]


def values(source: str) -> list[str]:
    return [t.value for t in lex(source)]


# --- Basic tokens ---

class TestBasicTokens:
    def test_empty_input(self):
        tokens = lex("")
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_single_int(self):
        assert types("42") == [TokenType.INT_LIT, TokenType.EOF]
        assert values("42")[0] == "42"

    def test_hex_literal(self):
        assert types("0xFF") == [TokenType.INT_LIT, TokenType.EOF]
        assert values("0xFF")[0] == "0xFF"

    def test_hex_literal_upper(self):
        assert types("0XAB") == [TokenType.INT_LIT, TokenType.EOF]
        assert values("0XAB")[0] == "0XAB"

    def test_binary_literal(self):
        assert types("0b1010") == [TokenType.INT_LIT, TokenType.EOF]
        assert values("0b1010")[0] == "0b1010"

    def test_float_literal(self):
        assert types("3.14") == [TokenType.FLOAT_LIT, TokenType.EOF]
        assert values("3.14")[0] == "3.14"

    def test_float_literal_with_suffix(self):
        assert types("3.14f") == [TokenType.FLOAT_LIT, TokenType.EOF]
        assert values("3.14f")[0] == "3.14f"

    def test_float_literal_with_exponent(self):
        assert types("1e10") == [TokenType.FLOAT_LIT, TokenType.EOF]
        assert values("1e10")[0] == "1e10"

    def test_float_exponent_with_sign(self):
        assert types("2.5e-3") == [TokenType.FLOAT_LIT, TokenType.EOF]

    def test_string_literal(self):
        assert types('"hello"') == [TokenType.STRING_LIT, TokenType.EOF]
        assert values('"hello"')[0] == '"hello"'

    def test_string_escape(self):
        assert types('"hello\\n"') == [TokenType.STRING_LIT, TokenType.EOF]
        assert values('"hello\\n"')[0] == '"hello\\n"'

    def test_char_literal(self):
        assert types("'a'") == [TokenType.CHAR_LIT, TokenType.EOF]
        assert values("'a'")[0] == "'a'"

    def test_char_escape(self):
        assert types("'\\n'") == [TokenType.CHAR_LIT, TokenType.EOF]
        assert values("'\\n'")[0] == "'\\n'"


# --- Keywords ---

class TestKeywords:
    def test_c_keywords(self):
        source = "int float void return if else while for"
        expected = [
            TokenType.INT, TokenType.FLOAT, TokenType.VOID, TokenType.RETURN,
            TokenType.IF, TokenType.ELSE, TokenType.WHILE, TokenType.FOR,
            TokenType.EOF,
        ]
        assert types(source) == expected

    def test_all_c_keywords(self):
        c_keywords = [
            "auto", "break", "case", "char", "const", "continue", "default",
            "do", "double", "else", "enum", "extern", "float", "for", "goto",
            "if", "int", "long", "register", "return", "short", "signed",
            "sizeof", "static", "struct", "switch", "typedef", "union",
            "unsigned", "void", "volatile", "while",
        ]
        for kw in c_keywords:
            tokens = lex(kw)
            assert tokens[0].type != TokenType.IDENT, f"'{kw}' should be a keyword, not IDENT"

    def test_btrc_keywords(self):
        source = "class public private self in parallel"
        expected = [
            TokenType.CLASS, TokenType.PUBLIC, TokenType.PRIVATE,
            TokenType.SELF, TokenType.IN, TokenType.PARALLEL,
            TokenType.EOF,
        ]
        assert types(source) == expected

    def test_builtin_types(self):
        source = "List Map Array string bool"
        expected = [
            TokenType.LIST, TokenType.MAP, TokenType.ARRAY,
            TokenType.STRING, TokenType.BOOL, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_true_false_null(self):
        source = "true false null"
        expected = [TokenType.TRUE, TokenType.FALSE, TokenType.NULL, TokenType.EOF]
        assert types(source) == expected

    def test_new_delete(self):
        source = "new delete"
        expected = [TokenType.NEW, TokenType.DELETE, TokenType.EOF]
        assert types(source) == expected

    def test_identifier_not_keyword(self):
        source = "myVar foo_bar _private"
        expected = [TokenType.IDENT, TokenType.IDENT, TokenType.IDENT, TokenType.EOF]
        assert types(source) == expected

    def test_var_keyword(self):
        assert types("var") == [TokenType.VAR, TokenType.EOF]
        assert values("var")[0] == "var"

    def test_var_in_declaration(self):
        source = "var x = 42"
        expected = [
            TokenType.VAR, TokenType.IDENT, TokenType.EQ,
            TokenType.INT_LIT, TokenType.EOF,
        ]
        assert types(source) == expected


# --- Operators ---

class TestOperators:
    def test_single_char_ops(self):
        source = "+ - * / % = < > ! & | ^ ~ . ? :"
        expected = [
            TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH,
            TokenType.PERCENT, TokenType.EQ, TokenType.LT, TokenType.GT,
            TokenType.BANG, TokenType.AMP, TokenType.PIPE, TokenType.CARET,
            TokenType.TILDE, TokenType.DOT, TokenType.QUESTION, TokenType.COLON,
            TokenType.EOF,
        ]
        assert types(source) == expected

    def test_multi_char_ops(self):
        # Test each multi-char operator individually to avoid ambiguity
        cases = [
            ("==", TokenType.EQ_EQ),
            ("!=", TokenType.BANG_EQ),
            ("<=", TokenType.LT_EQ),
            (">=", TokenType.GT_EQ),
            ("&&", TokenType.AMP_AMP),
            ("||", TokenType.PIPE_PIPE),
            ("++", TokenType.PLUS_PLUS),
            ("--", TokenType.MINUS_MINUS),
            ("->", TokenType.ARROW),
            ("<<", TokenType.LT_LT),
            (">>", TokenType.GT_GT),
            ("+=", TokenType.PLUS_EQ),
            ("-=", TokenType.MINUS_EQ),
            ("*=", TokenType.STAR_EQ),
            ("/=", TokenType.SLASH_EQ),
            ("%=", TokenType.PERCENT_EQ),
            ("&=", TokenType.AMP_EQ),
            ("|=", TokenType.PIPE_EQ),
            ("^=", TokenType.CARET_EQ),
            ("<<=", TokenType.LT_LT_EQ),
            (">>=", TokenType.GT_GT_EQ),
        ]
        for source, expected_type in cases:
            tokens = lex(source)
            assert tokens[0].type == expected_type, f"'{source}' should be {expected_type}"
            assert tokens[0].value == source


# --- Annotations ---

class TestAnnotations:
    def test_at_gpu(self):
        assert types("@gpu") == [TokenType.AT_GPU, TokenType.EOF]
        assert values("@gpu")[0] == "@gpu"

    def test_at_gpu_before_function(self):
        t = types("@gpu void foo")
        assert t == [TokenType.AT_GPU, TokenType.VOID, TokenType.IDENT, TokenType.EOF]

    def test_at_unknown(self):
        with pytest.raises(LexerError):
            lex("@foo")


# --- Delimiters ---

class TestDelimiters:
    def test_delimiters(self):
        source = "( ) [ ] { } , ;"
        expected = [
            TokenType.LPAREN, TokenType.RPAREN, TokenType.LBRACKET,
            TokenType.RBRACKET, TokenType.LBRACE, TokenType.RBRACE,
            TokenType.COMMA, TokenType.SEMICOLON, TokenType.EOF,
        ]
        assert types(source) == expected


# --- Preprocessor ---

class TestPreprocessor:
    def test_preprocessor_include(self):
        source = '#include <stdio.h>'
        tokens = lex(source)
        assert tokens[0].type == TokenType.PREPROCESSOR
        assert tokens[0].value == '#include <stdio.h>'

    def test_preprocessor_define(self):
        source = '#define MAX 100'
        tokens = lex(source)
        assert tokens[0].type == TokenType.PREPROCESSOR
        assert tokens[0].value == '#define MAX 100'

    def test_preprocessor_multiline(self):
        source = '#define MACRO \\\nvalue'
        tokens = lex(source)
        assert tokens[0].type == TokenType.PREPROCESSOR
        assert 'MACRO' in tokens[0].value

    def test_preprocessor_followed_by_code(self):
        source = '#include <stdio.h>\nint x;'
        t = types(source)
        assert t == [TokenType.PREPROCESSOR, TokenType.INT, TokenType.IDENT, TokenType.SEMICOLON, TokenType.EOF]


# --- Comments ---

class TestComments:
    def test_line_comment(self):
        source = 'int x; // comment\nint y;'
        expected = [
            TokenType.INT, TokenType.IDENT, TokenType.SEMICOLON,
            TokenType.INT, TokenType.IDENT, TokenType.SEMICOLON,
            TokenType.EOF,
        ]
        assert types(source) == expected

    def test_block_comment(self):
        source = 'int /* comment */ x;'
        expected = [TokenType.INT, TokenType.IDENT, TokenType.SEMICOLON, TokenType.EOF]
        assert types(source) == expected

    def test_multiline_block_comment(self):
        source = 'int /* line1\nline2\nline3 */ x;'
        expected = [TokenType.INT, TokenType.IDENT, TokenType.SEMICOLON, TokenType.EOF]
        assert types(source) == expected

    def test_unterminated_block_comment(self):
        with pytest.raises(LexerError):
            lex('/* oops')


# --- Complex inputs ---

class TestComplexInputs:
    def test_class_header(self):
        source = 'class Vec3<T> {'
        expected = [
            TokenType.CLASS, TokenType.IDENT, TokenType.LT,
            TokenType.IDENT, TokenType.GT, TokenType.LBRACE, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_for_in(self):
        source = 'for item in list {'
        expected = [
            TokenType.FOR, TokenType.IDENT, TokenType.IN,
            TokenType.IDENT, TokenType.LBRACE, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_parallel_for(self):
        source = 'parallel for x in data {'
        expected = [
            TokenType.PARALLEL, TokenType.FOR, TokenType.IDENT,
            TokenType.IN, TokenType.IDENT, TokenType.LBRACE, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_method_call(self):
        source = 'obj.method(a, b)'
        expected = [
            TokenType.IDENT, TokenType.DOT, TokenType.IDENT,
            TokenType.LPAREN, TokenType.IDENT, TokenType.COMMA,
            TokenType.IDENT, TokenType.RPAREN, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_generic_type(self):
        source = 'List<int>'
        expected = [TokenType.LIST, TokenType.LT, TokenType.INT, TokenType.GT, TokenType.EOF]
        assert types(source) == expected

    def test_nested_generic(self):
        # >> is lexed as GT_GT (longest match). The parser splits it in generic context.
        source = 'Map<string, List<int>>'
        expected = [
            TokenType.MAP, TokenType.LT, TokenType.STRING, TokenType.COMMA,
            TokenType.LIST, TokenType.LT, TokenType.INT, TokenType.GT_GT,
            TokenType.EOF,
        ]
        assert types(source) == expected

    def test_list_literal(self):
        source = '[1, 2, 3]'
        expected = [
            TokenType.LBRACKET, TokenType.INT_LIT, TokenType.COMMA,
            TokenType.INT_LIT, TokenType.COMMA, TokenType.INT_LIT,
            TokenType.RBRACKET, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_map_literal(self):
        source = '{"a": 1, "b": 2}'
        expected = [
            TokenType.LBRACE, TokenType.STRING_LIT, TokenType.COLON,
            TokenType.INT_LIT, TokenType.COMMA, TokenType.STRING_LIT,
            TokenType.COLON, TokenType.INT_LIT, TokenType.RBRACE, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_new_expr(self):
        source = 'new Vec3(1, 2, 3)'
        expected = [
            TokenType.NEW, TokenType.IDENT, TokenType.LPAREN,
            TokenType.INT_LIT, TokenType.COMMA, TokenType.INT_LIT,
            TokenType.COMMA, TokenType.INT_LIT, TokenType.RPAREN, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_self_access(self):
        source = 'self.x = 5'
        expected = [
            TokenType.SELF, TokenType.DOT, TokenType.IDENT,
            TokenType.EQ, TokenType.INT_LIT, TokenType.EOF,
        ]
        assert types(source) == expected

    def test_delete_statement(self):
        source = 'delete ptr;'
        expected = [TokenType.DELETE, TokenType.IDENT, TokenType.SEMICOLON, TokenType.EOF]
        assert types(source) == expected


# --- Line and column tracking ---

class TestPositionTracking:
    def test_line_col_first_token(self):
        tokens = lex("int")
        assert tokens[0].line == 1
        assert tokens[0].col == 1

    def test_line_col_multiline(self):
        source = "int\nfloat"
        tokens = lex(source)
        assert tokens[0].line == 1  # int
        assert tokens[1].line == 2  # float
        assert tokens[1].col == 1

    def test_col_tracking(self):
        source = "int x = 5;"
        tokens = lex(source)
        assert tokens[0].col == 1   # int
        assert tokens[1].col == 5   # x
        assert tokens[2].col == 7   # =
        assert tokens[3].col == 9   # 5


# --- Error cases ---

class TestErrors:
    def test_unterminated_string(self):
        with pytest.raises(LexerError):
            lex('"hello')

    def test_unterminated_block_comment(self):
        with pytest.raises(LexerError):
            lex('/* oops')

    def test_unexpected_character(self):
        with pytest.raises(LexerError):
            lex('`')

    def test_unknown_annotation(self):
        with pytest.raises(LexerError):
            lex('@unknown')


# --- F-strings ---

class TestFStrings:
    def test_fstring_basic(self):
        tokens = lex('f"hello {name}"')
        assert tokens[0].type == TokenType.FSTRING_LIT
        assert tokens[0].value == "hello {name}"

    def test_fstring_no_interp(self):
        tokens = lex('f"just text"')
        assert tokens[0].type == TokenType.FSTRING_LIT
        assert tokens[0].value == "just text"

    def test_fstring_empty(self):
        tokens = lex('f""')
        assert tokens[0].type == TokenType.FSTRING_LIT
        assert tokens[0].value == ""

    def test_f_as_identifier(self):
        """Bare 'f' not followed by quote should be an identifier."""
        tokens = lex('f + 1')
        assert tokens[0].type == TokenType.IDENT
        assert tokens[0].value == "f"

    def test_fstring_nested_braces(self):
        tokens = lex('f"val={fn(x)}"')
        assert tokens[0].type == TokenType.FSTRING_LIT
        assert tokens[0].value == "val={fn(x)}"

    def test_fstring_multiple_interp(self):
        tokens = lex('f"{a} + {b} = {c}"')
        assert tokens[0].type == TokenType.FSTRING_LIT
        assert tokens[0].value == "{a} + {b} = {c}"
