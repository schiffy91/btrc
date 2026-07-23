"""Planner, composition, and call-site contracts for initializers."""

import importlib.util

import pytest

from src.compiler.python.analyzer.analysis_context import AnalysisContext
from src.compiler.python.analyzer.core_models import Scope
from src.compiler.python.analyzer.declarations.registry import DeclarationRegistry
from src.compiler.python.analyzer.initializer_analyzer import (
    InitializerAnalyzer,
    InitializerArrayFieldCheck,
    InitializerCompatibilityCheck,
    InitializerTypeContext,
    InitializerTypeLayout,
)
from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.type_identity import TypeIdentity


def _parse(source: str):
    return Parser(Lexer(source, "<initializer-analyzer>").tokenize()).parse()


def _errors(source: str) -> list[str]:
    return SemanticAnalyzer().analyze(_parse(source)).errors


def test_semantic_analyzer_composes_initializer_planner_dependencies():
    analyzer = SemanticAnalyzer()

    assert isinstance(analyzer.initializers, InitializerAnalyzer)
    assert isinstance(analyzer.initializers.types, InitializerTypeLayout)
    assert vars(analyzer.initializers) == {
        "context": analyzer.context,
        "registry": analyzer.declarations,
        "types": analyzer.initializers.types,
    }
    assert vars(analyzer.initializers.types) == {
        "registry": analyzer.declarations,
    }


def test_initializer_validation_mixin_and_recursive_api_are_removed():
    analyzer = SemanticAnalyzer()
    owners = {owner.__name__ for owner in SemanticAnalyzer.__mro__}

    assert "InitializerValidationMixin" not in owners
    for method in (
        "_validate_typed_initializer",
        "_contextualize_aggregate_initializer",
        "_contextualize_collection_initializer",
        "_validate_collection_element",
        "_validate_map_initializer",
    ):
        assert not hasattr(analyzer, method)
    assert importlib.util.find_spec("src.compiler.python.analyzer.initializers") is None


def test_initializer_analyzer_plans_nested_struct_checks_directly():
    program = _parse(
        """
        struct Pair { int count; string name; };
        void run() { Pair value = {1, "ok"}; }
        """
    )
    declaration = program.declarations[1].body.statements[0]
    context = AnalysisContext()
    registry = DeclarationRegistry(context, Scope(), TypeIdentity())
    registry.register(program)
    planner = InitializerAnalyzer(
        context,
        registry,
        InitializerTypeLayout(registry),
    )

    plan = planner.plan_aggregate(
        declaration.type,
        declaration.initializer,
        "Initializer for 'value'",
        declaration.line,
        declaration.col,
    )

    assert plan.contextual
    assert sum(isinstance(step, InitializerArrayFieldCheck) for step in plan.steps) == 2
    compatibility = [step for step in plan.steps if isinstance(step, InitializerCompatibilityCheck)]
    assert [step.expected.base for step in compatibility] == ["int", "string"]
    contexts = [step for step in plan.steps if isinstance(step, InitializerTypeContext)]
    assert len(contexts) == 1
    assert contexts[0].value is declaration.initializer
    assert contexts[0].expected is declaration.type


def test_initializer_analyzer_owns_structural_shape_diagnostics():
    program = _parse(
        """
        struct Count { int value; };
        void run() { Count count = {1, 2}; }
        """
    )
    declaration = program.declarations[1].body.statements[0]
    context = AnalysisContext()
    registry = DeclarationRegistry(context, Scope(), TypeIdentity())
    registry.register(program)
    planner = InitializerAnalyzer(
        context,
        registry,
        InitializerTypeLayout(registry),
    )

    planner.plan_aggregate(
        declaration.type,
        declaration.initializer,
        "Initializer for 'count'",
        declaration.line,
        declaration.col,
    )

    assert any("has 2 initializer elements but struct 'Count' has 1 fields" in error for error in context.errors)


@pytest.mark.parametrize(
    "body",
    (
        'void run() { Pair value = {"bad"}; }',
        'void run() { Pair value = {1}; value = {"bad"}; }',
        'Pair make() { return {"bad"}; }',
        'void take(Pair value) {} void run() { take({"bad"}); }',
        'class Box { public Pair value = {"bad"}; }',
        'void run(Pair value = {"bad"}) {}',
    ),
)
def test_initializer_plans_are_consumed_at_semantic_call_sites(body: str):
    errors = _errors(f"struct Pair {{ int count; }};\n{body}")

    assert any("Field 'count' expects 'int' but got 'string'" in error for error in errors)


def test_collection_plans_preserve_element_key_and_value_diagnostics():
    errors = _errors(
        """
        void run() {
            Vector<int> values = [1, "bad"];
            Map<string, int> mapped = {1: "bad"};
        }
        """
    )

    assert any("Initializer for 'values' expects 'int' elements but got 'string'" in error for error in errors)
    assert any("Initializer for 'mapped' key expects 'string' elements but got 'int'" in error for error in errors)
    assert any("Initializer for 'mapped' value expects 'int' elements but got 'string'" in error for error in errors)
