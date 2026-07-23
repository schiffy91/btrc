"""Ownership and behavior contracts for hierarchy validation."""

import importlib.util

from src.compiler.python.analyzer.analysis_context import AnalysisContext
from src.compiler.python.analyzer.core_models import Scope
from src.compiler.python.analyzer.declarations.registry import DeclarationRegistry
from src.compiler.python.analyzer.declarations.signature_types import SignatureTypePolicy
from src.compiler.python.analyzer.hierarchy_validator import HierarchyValidator
from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.type_identity import TypeIdentity


def _parse(source: str):
    return Parser(Lexer(source, "<hierarchy-validator>").tokenize()).parse()


def test_semantic_analyzer_composes_hierarchy_validator_dependencies():
    analyzer = SemanticAnalyzer()

    assert isinstance(analyzer.hierarchy, HierarchyValidator)
    assert isinstance(analyzer.declaration_policy.signatures, SignatureTypePolicy)
    assert vars(analyzer.hierarchy) == {
        "context": analyzer.context,
        "registry": analyzer.declarations,
        "signature_types": analyzer.declaration_policy.signatures,
    }


def test_hierarchy_validation_is_absent_from_analyzer_mro_and_api():
    analyzer = SemanticAnalyzer()
    owners = {owner.__name__ for owner in SemanticAnalyzer.__mro__}

    assert "HierarchyValidationMixin" not in owners
    assert not hasattr(analyzer, "_validate_inheritance")
    assert not hasattr(analyzer, "_validate_interfaces")
    assert not hasattr(analyzer, "_validate_overrides")
    assert importlib.util.find_spec("src.compiler.python.analyzer.hierarchy") is None


def test_hierarchy_validator_runs_as_an_independent_pass_two_atom():
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
    context = AnalysisContext()
    registry = DeclarationRegistry(context, Scope(), TypeIdentity())
    registry.register(program)
    registry.resolve_interface_parents(program)
    validator = HierarchyValidator(context, registry, registry.policy.signatures)

    validator.validate(program)

    assert any("incompatible return type" in error for error in context.errors)
    assert any("param 1" in error and "incompatible type" in error for error in context.errors)
