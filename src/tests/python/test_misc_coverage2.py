"""Assorted small coverage gaps: no-parameter functions, f-strings with string
operands, expression-bodied lambdas, generic struct/class field initializers,
and malformed-switch parse errors."""

import pytest

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError, Parser
from src.tests.python.test_codegen import emit_c


def test_no_parameter_function_emits_void_param_list():
    c = emit_c("int answer() { return 42; }\nint main() { return answer(); }")
    assert "answer(void)" in c


def test_fstring_with_string_operand():
    c = emit_c('int main() { string name = "world"; string s = f"hi {name}!"; print(s); return 0; }')
    assert "%s" in c


def test_expression_bodied_lambda_return_inference():
    c = emit_c("int main() { var f = (int x) => x + 1; return f(41); }")
    assert "41" in c or "+ 1" in c


def test_expression_bodied_lambda_void():
    c = emit_c('int main() { var f = (int x) => print("x"); f(1); return 0; }')
    assert "printf" in c


def test_string_concat_in_fstring_and_plus():
    c = emit_c('int main() { string a = "x"; string b = "y"; string c = a + b; print(c); return 0; }')
    assert "__btrc_str" in c or "strcat" in c or "malloc" in c


def test_malformed_switch_body_is_parse_error():
    with pytest.raises(ParseError):
        Parser(Lexer("int main() { int x = 1; switch (x) { x = 2; } return 0; }", "<t>").tokenize()).parse()
