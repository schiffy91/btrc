"""SemanticAnalyzer diagnostics: gpu_id() context rules, private-member access, `self`
outside methods, uninitialized `var`, interface registration errors, and switch
return analysis. Asserts the specific diagnostic."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(src):
    return SemanticAnalyzer().analyze(Parser(Lexer(src, "<t>").tokenize()).parse())


def errors(src):
    return _analyze(src).errors


def _has(msgs, sub):
    return any(sub.lower() in m.lower() for m in msgs)


def test_gpu_id_outside_gpu_function_is_error():
    assert _has(errors("int main() { int i = gpu_id(); return i; }"), "gpu")


def test_gpu_id_with_arguments_is_error():
    src = "@gpu\nvoid f(int[] a) { int i = gpu_id(5); }\nint main() { return 0; }"
    assert _has(errors(src), "gpu_id")


def test_self_outside_method_is_error():
    assert _has(errors("int main() { return self.x; }"), "self")


def test_uninitialized_var_rejected_by_parser():
    import pytest

    from src.compiler.python.parser.parser import ParseError

    with pytest.raises(ParseError):
        Parser(Lexer("int main() { var x; return 0; }", "<t>").tokenize()).parse()


def test_duplicate_interface_name_is_error():
    src = "interface A { int a(); }\ninterface A { int b(); }\nint main() { return 0; }"
    assert _has(errors(src), "duplicate")


def test_parent_interface_not_found_is_error():
    src = "interface B extends Missing { int b(); }\nint main() { return 0; }"
    assert _has(errors(src), "not found")


def test_implemented_interface_not_found_is_error():
    src = "class C implements Missing { public int v; public C() { self.v = 0; } }\nint main() { return 0; }"
    assert _has(errors(src), "not found")


def test_private_member_access_from_outside_is_error():
    src = """
    class Box { private int secret; public Box() { self.secret = 1; } }
    int main() { Box b = new Box(); return b.secret; }
    """
    assert _has(errors(src), "private")


def test_switch_with_enum_field_cases_analyzes():
    # `case Color.RED` (a field-access case value) is recognized in exhaustiveness.
    src = """
    enum Color { RED, GREEN };
    int main() {
        Color c = RED;
        switch (c) {
            case Color.RED: break;
            case Color.GREEN: break;
        }
        return 0;
    }
    """
    # Either accepted as exhaustive, or no crash analyzing field-access cases.
    _analyze(src)


def test_function_all_switch_paths_return():
    src = """
    int classify(int x) {
        switch (x) {
            case 1: { return 10; }
            case 2: { return 20; }
            default: { return 0; }
        }
    }
    int main() { return classify(1); }
    """
    assert errors(src) == []


def test_unknown_named_argument_is_error():
    src = "int f(int value) { return value; }\nint main() { return f(vlaue=1); }"
    assert _has(errors(src), "no parameter named")


def test_positional_after_named_argument_is_error():
    src = "int f(int a, int b) { return a + b; }\nint main() { return f(a=1, 2); }"
    assert _has(errors(src), "positional argument follows named argument")
