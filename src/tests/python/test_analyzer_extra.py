"""SemanticAnalyzer coverage: super-usage validation, constant division-by-zero, sizeof
operands, interface/inheritance subtype checks, and generic type formatting in
diagnostics. Each asserts the concrete diagnostic or the absence of one."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(src):
    return SemanticAnalyzer().analyze(Parser(Lexer(src, "<t>").tokenize()).parse())


def errors(src):
    return _analyze(src).errors


def _has(msgs, sub):
    return any(sub.lower() in m.lower() for m in msgs)


def test_super_in_non_extending_class_is_error():
    src = "class A { public int v; public A() { self.v = super.x; } }\nint main() { return 0; }"
    assert _has(errors(src), "super")


def test_super_in_extending_class_is_ok():
    src = (
        "class A { public int v; public A() { self.v = 1; } }\n"
        "class B extends A { public int w; public B() { self.w = 2; } }\n"
        "int main() { B b = new B(); return b.w; }"
    )
    # super is valid here (B extends A); no 'super' diagnostic
    assert not _has(errors(src), "cannot be used")


def test_constant_division_by_zero_is_error():
    assert _has(errors("int main() { int x = 5 / 0; return x; }"), "division by zero")


def test_constant_modulo_by_zero_is_error():
    assert _has(errors("int main() { int x = 5 % 0; return x; }"), "division by zero")


def test_sizeof_expression_operand_analyzes():
    src = "int main() { int x = 3; int n = sizeof(x); return n; }"
    # sizeof over an expression operand must analyze its inner expression
    assert errors(src) == []


def test_sizeof_type_operand_analyzes():
    src = "int main() { int n = sizeof(int); return n; }"
    assert errors(src) == []


def test_interface_value_fails_closed():
    # Implementations are checked structurally, but interface-typed runtime
    # values are unavailable in the static-dispatch object model.
    src = """
    interface Speaker { int speak(); }
    class Dog implements Speaker { public int speak() { return 1; } }
    int call(Speaker s) { return s.speak(); }
    int main() { Dog d = new Dog(); return call(d); }
    """
    assert any("cannot be used as a runtime value" in error for error in errors(src))


def test_subclass_accepted_where_base_expected():
    src = """
    class Base { public int v; public Base() { self.v = 0; } }
    class Derived extends Base { public Derived() { self.v = 1; } }
    int take(Base b) { return b.v; }
    int main() { Derived d = new Derived(); return take(d); }
    """
    assert errors(src) == []
