"""Lexical generic parameters must shadow same-named global declarations."""

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<generic-shadowing>").tokenize()).parse()
    return program, SemanticAnalyzer().analyze(program)


def test_global_one_letter_class_does_not_capture_template_parameter():
    program, analyzed = _analyze("""
        class T { public T() {} }
        class Inner<U> {
            public U value;
            public Inner(U value) { self.value = value; }
        }
        class Outer<T> {
            public Inner<T> child;
            public Outer(Inner<T> child) { self.child = child; }
        }
        int main() {
            Inner<int> inner = new Inner<int>(3);
            Outer<int> outer = new Outer<int>(inner);
            return outer.child.value == 3 ? 0 : 1;
        }
    """)

    assert not analyzed.errors
    outer = next(decl for decl in program.declarations if getattr(decl, "name", None) == "Outer")
    child_type = outer.members[0].type
    assert child_type.pointer_depth == 1
    assert child_type.generic_args[0].base == "T"
    assert child_type.generic_args[0].pointer_depth == 0


def test_method_parameter_shadows_global_class_and_class_parameter():
    program, analyzed = _analyze("""
        class T {}
        class U {}
        class Box<T> {
            public U identity<U>(U value) { return value; }
        }
    """)

    assert not analyzed.errors
    box = next(decl for decl in program.declarations if getattr(decl, "name", None) == "Box")
    method = box.members[0]
    assert method.return_type.pointer_depth == 0
    assert method.params[0].type.pointer_depth == 0


def test_type_parameter_shadows_runtime_forbidden_interface_name():
    _, analyzed = _analyze("""
        interface Value { int get(); }
        class Box<Value> {
            public Value stored;
            public Box(Value stored) { self.stored = stored; }
            public Value get() { return self.stored; }
        }
    """)

    assert not analyzed.errors
