"""Shared reference-compatibility edge cases."""

from src.compiler.python.ast_nodes import TypeExpr
from src.compiler.python.operator_semantics import coalesce_domain
from src.compiler.python.reference_semantics import reference_types_compatible


def test_scalar_string_and_single_char_pointer_are_symmetric_references():
    string = TypeExpr(base="string")
    char_pointer = TypeExpr(base="char", pointer_depth=1)

    assert reference_types_compatible(string, char_pointer)
    assert reference_types_compatible(char_pointer, string)
    assert coalesce_domain(string, char_pointer) == "reference"
    assert coalesce_domain(char_pointer, string) == "reference"


def test_scalar_string_does_not_admit_pointer_to_pointer():
    string = TypeExpr(base="string")
    char_pointer_pointer = TypeExpr(base="char", pointer_depth=2)

    assert not reference_types_compatible(string, char_pointer_pointer)
