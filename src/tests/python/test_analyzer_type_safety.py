"""Analyzer regressions for assignments that would otherwise reach invalid C."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<type-safety>").tokenize()).parse()
    return Analyzer().analyze(program).errors


def test_pointer_variable_rejects_scalar_initializer():
    errors = _errors("int main() { int* pointer = 1; return 0; }")
    assert any("cannot assign" in error.lower() for error in errors)


def test_primitive_variable_rejects_class_initializer():
    errors = _errors("""
        class Item {}
        int main() { int value = Item(); return value; }
    """)
    assert any("cannot assign" in error.lower() for error in errors)


def test_bare_generic_rejects_parameterized_initializer():
    errors = _errors("""
        class Box<T> { public Box() {} }
        int main() { Box value = new Box<int>(); return 0; }
    """)
    assert any("cannot assign" in error.lower() for error in errors)


def test_typedef_alias_uses_its_underlying_type_contract():
    errors = _errors("""
        typedef int MyInt;
        MyInt increment(MyInt value) {
            MyInt result = value + 1;
            return result;
        }
    """)
    assert errors == []


def test_class_cast_target_is_upgraded_to_reference_type():
    errors = _errors("""
        class Animal {}
        class Dog extends Animal {}
        Animal upcast(Dog dog) { return (Animal)dog; }
    """)
    assert errors == []
