"""Shared reference-compatibility edge cases."""

from src.compiler.python.analyzer.types import OperatorSemantics, TypeIdentity
from src.compiler.python.syntax.ast.generated import TypeExpr

IDENTITY = TypeIdentity()
OPERATORS = OperatorSemantics(IDENTITY)


def test_scalar_string_and_single_char_pointer_are_symmetric_references():
    string = TypeExpr(base="string")
    char_pointer = TypeExpr(base="char", pointer_depth=1)

    assert IDENTITY.references_compatible(string, char_pointer)
    assert IDENTITY.references_compatible(char_pointer, string)
    assert OPERATORS.coalesce_domain(string, char_pointer) == "reference"
    assert OPERATORS.coalesce_domain(char_pointer, string) == "reference"


def test_scalar_string_does_not_admit_pointer_to_pointer():
    string = TypeExpr(base="string")
    char_pointer_pointer = TypeExpr(base="char", pointer_depth=2)

    assert not IDENTITY.references_compatible(string, char_pointer_pointer)
