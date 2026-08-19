"""Tests for the btrc lexer."""

import pytest

from src.compiler.python.lexer.lexer import Lexer, LexerError
from src.compiler.python.syntax.tokens import TokenKind


def lex(source: str) -> list:
    return Lexer(source).tokenize()


def types(source: str) -> list[TokenKind]:
    return [t.type for t in lex(source)]


def values(source: str) -> list[str]:
    return [t.value for t in lex(source)]


# --- Basic tokens ---


class TestBasicTokens:
    def test_empty_input(self):
        tokens = lex("")
        assert len(tokens) == 1
        assert tokens[0].type == TokenKind.EOF

    def test_single_int(self):
        assert types("42") == [TokenKind.INT_LIT, TokenKind.EOF]
        assert values("42")[0] == "42"

    def test_hex_literal(self):
        assert types("0xFF") == [TokenKind.INT_LIT, TokenKind.EOF]
        assert values("0xFF")[0] == "0xFF"

    def test_hex_literal_upper(self):
        assert types("0XAB") == [TokenKind.INT_LIT, TokenKind.EOF]
        assert values("0XAB")[0] == "0XAB"

    def test_binary_literal(self):
        assert types("0b1010") == [TokenKind.INT_LIT, TokenKind.EOF]
        assert values("0b1010")[0] == "0b1010"

    def test_octal_literal(self):
        assert types("0o777") == [TokenKind.INT_LIT, TokenKind.EOF]
        assert values("0o777")[0] == "0o777"

    def test_octal_literal_upper(self):
        assert types("0O10") == [TokenKind.INT_LIT, TokenKind.EOF]
        assert values("0O10")[0] == "0O10"

    def test_float_literal(self):
        assert types("3.14") == [TokenKind.FLOAT_LIT, TokenKind.EOF]
        assert values("3.14")[0] == "3.14"

    def test_float_literal_with_suffix(self):
        assert types("3.14f") == [TokenKind.FLOAT_LIT, TokenKind.EOF]
        assert values("3.14f")[0] == "3.14f"

    def test_float_literal_with_exponent(self):
        assert types("1e10") == [TokenKind.FLOAT_LIT, TokenKind.EOF]
        assert values("1e10")[0] == "1e10"

    def test_float_exponent_with_sign(self):
        assert types("2.5e-3") == [TokenKind.FLOAT_LIT, TokenKind.EOF]

    def test_string_literal(self):
        assert types('"hello"') == [TokenKind.STRING_LIT, TokenKind.EOF]
        assert values('"hello"')[0] == '"hello"'

    def test_string_escape(self):
        assert types('"hello\\n"') == [TokenKind.STRING_LIT, TokenKind.EOF]
        assert values('"hello\\n"')[0] == '"hello\\n"'

    def test_char_literal(self):
        assert types("'a'") == [TokenKind.CHAR_LIT, TokenKind.EOF]
        assert values("'a'")[0] == "'a'"

    def test_char_escape(self):
        assert types("'\\n'") == [TokenKind.CHAR_LIT, TokenKind.EOF]
        assert values("'\\n'")[0] == "'\\n'"

    @pytest.mark.parametrize(
        "source",
        ["'\\0'", "'\\123'", "'\\377'", "'\\x4'", "'\\x41'", "'\\x000041'"],
    )
    def test_portable_char_escape_forms(self, source):
        assert types(source) == [TokenKind.CHAR_LIT, TokenKind.EOF]

    @pytest.mark.parametrize(
        "source",
        [
            "''",
            "'ab'",
            "'é'",
            "'\\e'",
            "'\\8'",
            "'\\400'",
            "'\\x'",
            "'\\x123'",
            "'\\x000100'",
            "'\\u0041'",
            "'a\nb'",
        ],
    )
    def test_invalid_character_literal_fails_closed(self, source):
        with pytest.raises(LexerError):
            lex(source)


# --- Keywords ---


class TestKeywords:
    def test_c_keywords(self):
        source = "int float void return if else while for"
        expected = [
            TokenKind.INT,
            TokenKind.FLOAT,
            TokenKind.VOID,
            TokenKind.RETURN,
            TokenKind.IF,
            TokenKind.ELSE,
            TokenKind.WHILE,
            TokenKind.FOR,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_all_c_keywords(self):
        c_keywords = [
            "auto",
            "break",
            "case",
            "char",
            "const",
            "continue",
            "default",
            "do",
            "double",
            "else",
            "enum",
            "extern",
            "float",
            "for",
            "goto",
            "if",
            "int",
            "long",
            "register",
            "return",
            "short",
            "signed",
            "sizeof",
            "static",
            "struct",
            "switch",
            "typedef",
            "union",
            "unsigned",
            "void",
            "volatile",
            "while",
        ]
        for kw in c_keywords:
            tokens = lex(kw)
            assert tokens[0].type != TokenKind.IDENT, f"'{kw}' should be a keyword, not IDENT"

    def test_btrc_keywords(self):
        source = "class public private self in parallel"
        expected = [
            TokenKind.CLASS,
            TokenKind.PUBLIC,
            TokenKind.PRIVATE,
            TokenKind.SELF,
            TokenKind.IN,
            TokenKind.PARALLEL,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_builtin_types(self):
        # List/Map/Array are now identifiers (defined as classes in stdlib)
        source = "List Map Array string bool"
        expected = [
            TokenKind.IDENT,
            TokenKind.IDENT,
            TokenKind.IDENT,
            TokenKind.STRING,
            TokenKind.BOOL,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_true_false_null(self):
        source = "true false null"
        expected = [TokenKind.TRUE, TokenKind.FALSE, TokenKind.NULL, TokenKind.EOF]
        assert types(source) == expected

    def test_new_delete(self):
        source = "new delete"
        expected = [TokenKind.NEW, TokenKind.DELETE, TokenKind.EOF]
        assert types(source) == expected

    def test_identifier_not_keyword(self):
        source = "myVar foo_bar _private"
        expected = [TokenKind.IDENT, TokenKind.IDENT, TokenKind.IDENT, TokenKind.EOF]
        assert types(source) == expected

    def test_var_keyword(self):
        assert types("var") == [TokenKind.VAR, TokenKind.EOF]
        assert values("var")[0] == "var"

    def test_var_in_declaration(self):
        source = "var x = 42"
        expected = [
            TokenKind.VAR,
            TokenKind.IDENT,
            TokenKind.EQ,
            TokenKind.INT_LIT,
            TokenKind.EOF,
        ]
        assert types(source) == expected


# --- Operators ---


class TestOperators:
    def test_single_char_ops(self):
        source = "+ - * / % = < > ! & | ^ ~ . ? :"
        expected = [
            TokenKind.PLUS,
            TokenKind.MINUS,
            TokenKind.STAR,
            TokenKind.SLASH,
            TokenKind.PERCENT,
            TokenKind.EQ,
            TokenKind.LT,
            TokenKind.GT,
            TokenKind.BANG,
            TokenKind.AMP,
            TokenKind.PIPE,
            TokenKind.CARET,
            TokenKind.TILDE,
            TokenKind.DOT,
            TokenKind.QUESTION,
            TokenKind.COLON,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_multi_char_ops(self):
        # Test each multi-char operator individually to avoid ambiguity
        cases = [
            ("==", TokenKind.EQ_EQ),
            ("!=", TokenKind.BANG_EQ),
            ("<=", TokenKind.LT_EQ),
            (">=", TokenKind.GT_EQ),
            ("&&", TokenKind.AMP_AMP),
            ("||", TokenKind.PIPE_PIPE),
            ("++", TokenKind.PLUS_PLUS),
            ("--", TokenKind.MINUS_MINUS),
            ("->", TokenKind.ARROW),
            ("<<", TokenKind.LT_LT),
            (">>", TokenKind.GT_GT),
            ("+=", TokenKind.PLUS_EQ),
            ("-=", TokenKind.MINUS_EQ),
            ("*=", TokenKind.STAR_EQ),
            ("/=", TokenKind.SLASH_EQ),
            ("%=", TokenKind.PERCENT_EQ),
            ("&=", TokenKind.AMP_EQ),
            ("|=", TokenKind.PIPE_EQ),
            ("^=", TokenKind.CARET_EQ),
            ("<<=", TokenKind.LT_LT_EQ),
            (">>=", TokenKind.GT_GT_EQ),
        ]
        for source, expected_type in cases:
            tokens = lex(source)
            assert tokens[0].type == expected_type, f"'{source}' should be {expected_type}"
            assert tokens[0].value == source


# --- Annotations ---


class TestAnnotations:
    def test_at_gpu(self):
        assert types("@gpu") == [TokenKind.AT_GPU, TokenKind.EOF]
        assert values("@gpu")[0] == "@gpu"

    def test_at_gpu_before_function(self):
        t = types("@gpu void foo")
        assert t == [TokenKind.AT_GPU, TokenKind.VOID, TokenKind.IDENT, TokenKind.EOF]

    def test_at_unknown(self):
        with pytest.raises(LexerError):
            lex("@foo")


# --- Delimiters ---


class TestDelimiters:
    def test_delimiters(self):
        source = "( ) [ ] { } , ;"
        expected = [
            TokenKind.LPAREN,
            TokenKind.RPAREN,
            TokenKind.LBRACKET,
            TokenKind.RBRACKET,
            TokenKind.LBRACE,
            TokenKind.RBRACE,
            TokenKind.COMMA,
            TokenKind.SEMICOLON,
            TokenKind.EOF,
        ]
        assert types(source) == expected


# --- Preprocessor ---


class TestPreprocessor:
    def test_preprocessor_include(self):
        source = "#include <stdio.h>"
        tokens = lex(source)
        assert tokens[0].type == TokenKind.PREPROCESSOR
        assert tokens[0].value == "#include <stdio.h>"

    def test_preprocessor_define(self):
        source = "#define MAX 100"
        tokens = lex(source)
        assert tokens[0].type == TokenKind.PREPROCESSOR
        assert tokens[0].value == "#define MAX 100"

    def test_preprocessor_multiline(self):
        source = "#define MACRO \\\nvalue"
        tokens = lex(source)
        assert tokens[0].type == TokenKind.PREPROCESSOR
        assert "MACRO" in tokens[0].value

    def test_preprocessor_followed_by_code(self):
        source = "#include <stdio.h>\nint x;"
        t = types(source)
        assert t == [TokenKind.PREPROCESSOR, TokenKind.INT, TokenKind.IDENT, TokenKind.SEMICOLON, TokenKind.EOF]


# --- Comments ---


class TestComments:
    def test_line_comment(self):
        source = "int x; // comment\nint y;"
        expected = [
            TokenKind.INT,
            TokenKind.IDENT,
            TokenKind.SEMICOLON,
            TokenKind.INT,
            TokenKind.IDENT,
            TokenKind.SEMICOLON,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_block_comment(self):
        source = "int /* comment */ x;"
        expected = [TokenKind.INT, TokenKind.IDENT, TokenKind.SEMICOLON, TokenKind.EOF]
        assert types(source) == expected

    def test_multiline_block_comment(self):
        source = "int /* line1\nline2\nline3 */ x;"
        expected = [TokenKind.INT, TokenKind.IDENT, TokenKind.SEMICOLON, TokenKind.EOF]
        assert types(source) == expected

    def test_unterminated_block_comment(self):
        with pytest.raises(LexerError):
            lex("/* oops")


# --- Complex inputs ---


class TestComplexInputs:
    def test_class_header(self):
        source = "class Vec3<T> {"
        expected = [
            TokenKind.CLASS,
            TokenKind.IDENT,
            TokenKind.LT,
            TokenKind.IDENT,
            TokenKind.GT,
            TokenKind.LBRACE,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_for_in(self):
        source = "for item in list {"
        expected = [
            TokenKind.FOR,
            TokenKind.IDENT,
            TokenKind.IN,
            TokenKind.IDENT,
            TokenKind.LBRACE,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_parallel_for(self):
        source = "parallel for x in data {"
        expected = [
            TokenKind.PARALLEL,
            TokenKind.FOR,
            TokenKind.IDENT,
            TokenKind.IN,
            TokenKind.IDENT,
            TokenKind.LBRACE,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_method_call(self):
        source = "obj.method(a, b)"
        expected = [
            TokenKind.IDENT,
            TokenKind.DOT,
            TokenKind.IDENT,
            TokenKind.LPAREN,
            TokenKind.IDENT,
            TokenKind.COMMA,
            TokenKind.IDENT,
            TokenKind.RPAREN,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_generic_type(self):
        # List is now an identifier (defined as class in stdlib)
        source = "List<int>"
        expected = [TokenKind.IDENT, TokenKind.LT, TokenKind.INT, TokenKind.GT, TokenKind.EOF]
        assert types(source) == expected

    def test_nested_generic(self):
        # >> is lexed as GT_GT (longest match). The parser splits it in generic context.
        # Map/List are now identifiers (defined as classes in stdlib)
        source = "Map<string, List<int>>"
        expected = [
            TokenKind.IDENT,
            TokenKind.LT,
            TokenKind.STRING,
            TokenKind.COMMA,
            TokenKind.IDENT,
            TokenKind.LT,
            TokenKind.INT,
            TokenKind.GT_GT,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_list_literal(self):
        source = "[1, 2, 3]"
        expected = [
            TokenKind.LBRACKET,
            TokenKind.INT_LIT,
            TokenKind.COMMA,
            TokenKind.INT_LIT,
            TokenKind.COMMA,
            TokenKind.INT_LIT,
            TokenKind.RBRACKET,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_map_literal(self):
        source = '{"a": 1, "b": 2}'
        expected = [
            TokenKind.LBRACE,
            TokenKind.STRING_LIT,
            TokenKind.COLON,
            TokenKind.INT_LIT,
            TokenKind.COMMA,
            TokenKind.STRING_LIT,
            TokenKind.COLON,
            TokenKind.INT_LIT,
            TokenKind.RBRACE,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_new_expr(self):
        source = "new Vec3(1, 2, 3)"
        expected = [
            TokenKind.NEW,
            TokenKind.IDENT,
            TokenKind.LPAREN,
            TokenKind.INT_LIT,
            TokenKind.COMMA,
            TokenKind.INT_LIT,
            TokenKind.COMMA,
            TokenKind.INT_LIT,
            TokenKind.RPAREN,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_self_access(self):
        source = "self.x = 5"
        expected = [
            TokenKind.SELF,
            TokenKind.DOT,
            TokenKind.IDENT,
            TokenKind.EQ,
            TokenKind.INT_LIT,
            TokenKind.EOF,
        ]
        assert types(source) == expected

    def test_delete_statement(self):
        source = "delete ptr;"
        expected = [TokenKind.DELETE, TokenKind.IDENT, TokenKind.SEMICOLON, TokenKind.EOF]
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
        assert tokens[0].col == 1  # int
        assert tokens[1].col == 5  # x
        assert tokens[2].col == 7  # =
        assert tokens[3].col == 9  # 5


# --- Error cases ---


class TestErrors:
    def test_unterminated_string(self):
        with pytest.raises(LexerError):
            lex('"hello')

    def test_unterminated_block_comment(self):
        with pytest.raises(LexerError):
            lex("/* oops")

    def test_unexpected_character(self):
        with pytest.raises(LexerError):
            lex("`")

    def test_unknown_annotation(self):
        with pytest.raises(LexerError):
            lex("@unknown")


# --- F-strings ---


class TestInvalidLiterals:
    def test_hex_no_digits(self):
        with pytest.raises(LexerError):
            lex("0x;")

    def test_binary_no_digits(self):
        with pytest.raises(LexerError):
            lex("0b;")

    def test_octal_no_digits(self):
        with pytest.raises(LexerError):
            lex("0o;")

    def test_float_incomplete_exponent(self):
        with pytest.raises(LexerError):
            lex("1e;")

    def test_float_incomplete_exponent_sign(self):
        with pytest.raises(LexerError):
            lex("1e+;")


class TestFStrings:
    def test_fstring_basic(self):
        tokens = lex('f"hello {name}"')
        assert tokens[0].type == TokenKind.FSTRING_LIT
        assert tokens[0].value == "hello {name}"

    def test_fstring_no_interp(self):
        tokens = lex('f"just text"')
        assert tokens[0].type == TokenKind.FSTRING_LIT
        assert tokens[0].value == "just text"

    def test_fstring_empty(self):
        tokens = lex('f""')
        assert tokens[0].type == TokenKind.FSTRING_LIT
        assert tokens[0].value == ""

    def test_f_as_identifier(self):
        """Bare 'f' not followed by quote should be an identifier."""
        tokens = lex("f + 1")
        assert tokens[0].type == TokenKind.IDENT
        assert tokens[0].value == "f"

    def test_fstring_nested_braces(self):
        tokens = lex('f"val={fn(x)}"')
        assert tokens[0].type == TokenKind.FSTRING_LIT
        assert tokens[0].value == "val={fn(x)}"

    def test_fstring_multiple_interp(self):
        tokens = lex('f"{a} + {b} = {c}"')
        assert tokens[0].type == TokenKind.FSTRING_LIT
        assert tokens[0].value == "{a} + {b} = {c}"


class TestTripleQuoteStrings:
    def test_basic_multiline(self):
        tokens = lex('"""hello\nworld"""')
        assert tokens[0].type == TokenKind.STRING_LIT
        assert tokens[0].value == '"hello\\nworld"'

    def test_single_line(self):
        tokens = lex('"""hello"""')
        assert tokens[0].type == TokenKind.STRING_LIT
        assert tokens[0].value == '"hello"'

    def test_empty(self):
        tokens = lex('""""""')
        assert tokens[0].type == TokenKind.STRING_LIT
        assert tokens[0].value == '""'

    def test_embedded_double_quote(self):
        tokens = lex('"""he said "hi" there"""')
        assert tokens[0].type == TokenKind.STRING_LIT
        assert tokens[0].value == '"he said "hi" there"'

    def test_embedded_two_double_quotes(self):
        tokens = lex('"""a""b"""')
        assert tokens[0].type == TokenKind.STRING_LIT
        assert tokens[0].value == '"a""b"'

    def test_multiple_newlines(self):
        tokens = lex('"""a\nb\nc"""')
        assert tokens[0].type == TokenKind.STRING_LIT
        assert tokens[0].value == '"a\\nb\\nc"'

    def test_preserves_escapes(self):
        tokens = lex('"""hello\\tworld"""')
        assert tokens[0].type == TokenKind.STRING_LIT
        assert tokens[0].value == '"hello\\tworld"'

    def test_unterminated(self):
        with pytest.raises(LexerError):
            lex('"""hello')

    def test_in_expression(self):
        tokens = lex('var s = """hello\nworld""";')
        assert tokens[0].type == TokenKind.VAR
        assert tokens[1].type == TokenKind.IDENT
        assert tokens[2].type == TokenKind.EQ
        assert tokens[3].type == TokenKind.STRING_LIT
        assert tokens[3].value == '"hello\\nworld"'
        assert tokens[4].type == TokenKind.SEMICOLON
