"""White-box tests for the analyzer's type-compatibility helpers: generic type
formatting, the subclass/interface chain walk, and assignment compatibility.
Driven directly on an analyzer whose tables are populated by analyze()."""

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

_SRC = """
interface Speaker { int speak(); }
class A implements Speaker { public int v; public A() { self.v = 0; } public int speak() { return 1; } }
class B extends A { public B() { self.v = 1; } }
class C extends B { public C() { self.v = 2; } }
int main() { return 0; }
"""


def _analyzer():
    a = Analyzer()
    a.analyze(Parser(Lexer(_SRC, "<t>").tokenize()).parse())
    return a


def test_is_subclass_transitive_parent_chain():
    a = _analyzer()
    assert a._is_subclass("C", "A") is True  # C -> B -> A
    assert a._is_subclass("C", "C") is True
    assert a._is_subclass("A", "C") is False


def test_is_subclass_interface_via_inheritance():
    a = _analyzer()
    assert a._is_subclass("C", "Speaker") is True  # C inherits A's interface
    assert a._is_subclass("B", "Speaker") is True
    assert a._is_subclass("A", "Speaker") is True


def test_format_type_with_generics_and_pointers():
    a = _analyzer()
    t = TypeExpr(base="Map", generic_args=[TypeExpr(base="string"), TypeExpr(base="int")], pointer_depth=1)
    assert a._format_type(t) == "Map<string, int>*"


def test_types_compatible_subclass_and_numeric():
    a = _analyzer()
    assert a._types_compatible(TypeExpr(base="A"), TypeExpr(base="C")) is True
    assert a._types_compatible(TypeExpr(base="int"), TypeExpr(base="double")) is True
    # Two distinct known, non-numeric types are incompatible.
    assert a._types_compatible(TypeExpr(base="bool"), TypeExpr(base="string")) is False


def test_types_compatible_is_structural_for_pointers_and_generics():
    a = _analyzer()
    assert not a._types_compatible(TypeExpr(base="int", pointer_depth=1), TypeExpr(base="int"))
    assert not a._types_compatible(
        TypeExpr(base="Vector", generic_args=[TypeExpr(base="int")]),
        TypeExpr(base="Vector"),
    )
    assert not a._types_compatible(
        TypeExpr(base="Vector", generic_args=[TypeExpr(base="int")]),
        TypeExpr(base="Vector", generic_args=[TypeExpr(base="string")]),
    )


def test_interface_compatibility_requires_implementation():
    a = _analyzer()
    assert a._types_compatible(TypeExpr(base="Speaker"), TypeExpr(base="C"))
    assert not a._types_compatible(TypeExpr(base="Speaker"), TypeExpr(base="string"))
