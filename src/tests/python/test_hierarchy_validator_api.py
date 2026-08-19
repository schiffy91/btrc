"""Behavior contracts for hierarchy validation."""

from src.compiler.python.analyzer.declarations import (
    DeclarationRegistry,
    HierarchyValidator,
    SignatureTypePolicy,
)
from src.compiler.python.analyzer.program import AnalysisSession, DeclarationIndex
from src.compiler.python.analyzer.types import TypeIdentity
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _parse(source: str):
    return Parser(Lexer(source, "<hierarchy-validator>").tokenize()).parse()


def test_hierarchy_validator_rejects_incompatible_overrides():
    program = _parse(
        """
        class Base {
            public int read(int value) { return value; }
        }
        class Child extends Base {
            public string read(string value) { return value; }
        }
        """
    )
    session = AnalysisSession()
    index = DeclarationIndex()
    registry = DeclarationRegistry(session, index, TypeIdentity())
    registry.register(program)
    registry.resolve_interface_parents(program)
    validator = HierarchyValidator(session, index, SignatureTypePolicy(session, index, TypeIdentity()))

    validator.validate(program)

    assert any("incompatible return type" in error for error in session.errors)
    assert any("param 1" in error and "incompatible type" in error for error in session.errors)
