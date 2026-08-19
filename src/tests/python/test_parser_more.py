"""Parser coverage for property accessor errors, @gpu placement errors, and
sizeof-of-expression."""

import pytest

from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import ParseError
from src.compiler.python.parser.parser import Parser


def parse(src):
    return Parser(Lexer(src, "<t>").tokenize()).parse()


def test_malformed_property_getter_is_error():
    with pytest.raises(ParseError):
        parse("class C { public int v; public int x { get get } }\nint main() { return 0; }")


def test_malformed_property_setter_is_error():
    with pytest.raises(ParseError):
        parse("class C { public int v; public int x { set set } }\nint main() { return 0; }")


def test_gpu_on_global_variable_is_error():
    with pytest.raises(ParseError):
        parse("@gpu int counter = 0;\nint main() { return 0; }")


def test_gpu_on_local_variable_is_error():
    with pytest.raises(ParseError):
        parse("int main() { @gpu int x = 0; return 0; }")


def test_sizeof_of_expression_parses():
    prog = parse("int main() { int n = sizeof(1 + 2); int m = sizeof(int); return n + m; }")
    assert prog.declarations


def test_valid_property_with_getter_and_setter():
    src = (
        "class Temp {\n"
        "    public int celsius;\n"
        "    public int fahrenheit {\n"
        "        get { return self.celsius * 9 / 5 + 32; }\n"
        "        set { self.celsius = (value - 32) * 5 / 9; }\n"
        "    }\n"
        "    public Temp() { self.celsius = 0; }\n"
        "}\n"
        "int main() { Temp t = new Temp(); t.fahrenheit = 212; return t.celsius; }"
    )
    prog = parse(src)
    assert prog.declarations
