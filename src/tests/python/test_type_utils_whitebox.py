"""Contracts for the concrete semantic type-system owner."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import TypeExpr

_SRC = """
interface Speaker { int speak(); }
class A implements Speaker { public int v; public A() { self.v = 0; } public int speak() { return 1; } }
class B extends A { public B() { self.v = 1; } }
class C extends B { public C() { self.v = 2; } }
int main() { return 0; }
"""


def _types():
    analyzer = SemanticAnalyzer()
    analyzer.analyze(Parser(Lexer(_SRC, "<t>").tokenize()).parse())
    return analyzer.types


def test_is_subclass_transitive_parent_chain():
    types = _types()
    assert types.is_subclass("C", "A") is True  # C -> B -> A
    assert types.is_subclass("C", "C") is True
    assert types.is_subclass("A", "C") is False


def test_is_subclass_interface_via_inheritance():
    types = _types()
    assert types.is_subclass("C", "Speaker") is True  # C inherits A's interface
    assert types.is_subclass("B", "Speaker") is True
    assert types.is_subclass("A", "Speaker") is True


def test_format_type_with_generics_and_pointers():
    types = _types()
    t = TypeExpr(base="Map", generic_args=[TypeExpr(base="string"), TypeExpr(base="int")], pointer_depth=1)
    assert types.format_type(t) == "Map<string, int>*"


def test_types_compatible_subclass_and_numeric():
    types = _types()
    assert types.types_compatible(TypeExpr(base="A"), TypeExpr(base="C")) is True
    assert types.types_compatible(TypeExpr(base="int"), TypeExpr(base="double")) is True
    # Two distinct known, non-numeric types are incompatible.
    assert types.types_compatible(TypeExpr(base="bool"), TypeExpr(base="string")) is False


def test_types_compatible_is_structural_for_pointers_and_generics():
    types = _types()
    assert not types.types_compatible(TypeExpr(base="int", pointer_depth=1), TypeExpr(base="int"))
    assert not types.types_compatible(
        TypeExpr(base="Vector", generic_args=[TypeExpr(base="int")]),
        TypeExpr(base="Vector"),
    )
    assert not types.types_compatible(
        TypeExpr(base="Vector", generic_args=[TypeExpr(base="int")]),
        TypeExpr(base="Vector", generic_args=[TypeExpr(base="string")]),
    )


def test_interface_compatibility_requires_implementation():
    types = _types()
    assert types.types_compatible(TypeExpr(base="Speaker"), TypeExpr(base="C"))
    assert not types.types_compatible(TypeExpr(base="Speaker"), TypeExpr(base="string"))
