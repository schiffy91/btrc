"""Durable API and ownership contracts for semantic analysis."""

import importlib.util

from src.compiler.python.analyzer.analysis_context import AnalysisContext
from src.compiler.python.analyzer.declarations.policy import DeclarationPolicy
from src.compiler.python.analyzer.declarations.registry import DeclarationRegistry
from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def analyze(source: str, **options):
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    analyzer = SemanticAnalyzer(**options)
    return analyzer, analyzer.analyze(program)


def test_semantic_analyzer_owns_real_declaration_registry():
    analyzer, result = analyze("class Item {} int main() { return 0; }")

    assert isinstance(analyzer.declarations, DeclarationRegistry)
    assert set(analyzer.declarations.class_table) == {"Item"}
    assert set(analyzer.declarations.function_table) == {"main"}
    assert not hasattr(analyzer, "class_table")
    assert result.class_table is analyzer.declarations.class_table


def test_analysis_context_and_declaration_policy_own_their_state():
    analyzer, result = analyze("int main() { int __bad = 0; return __bad; }")

    assert isinstance(analyzer.context, AnalysisContext)
    assert isinstance(analyzer.declaration_policy, DeclarationPolicy)
    assert analyzer.declarations.context is analyzer.context
    assert analyzer.declarations.policy is analyzer.declaration_policy
    assert result.errors is analyzer.context.errors
    assert result.warnings is analyzer.context.warnings
    assert result.diags is analyzer.context.diagnostics
    assert not hasattr(analyzer, "errors")
    assert not hasattr(analyzer, "current_source_file")
    assert not hasattr(analyzer.declarations, "services")


def test_analysis_context_restores_nested_source_provenance():
    program = Parser(Lexer("int main() { return 0; }", "<test>").tokenize()).parse()
    program.declarations[0].source_file = "inner.btrc"
    context = AnalysisContext()

    with context.source("outer.btrc"):
        for _declaration in context.declarations(program):
            assert context.current_source_file == "inner.btrc"
        assert context.current_source_file == "outer.btrc"

    assert context.current_source_file is None


def test_registration_mixins_are_absent_from_semantic_analyzer_mro():
    owners = {owner.__name__ for owner in SemanticAnalyzer.__mro__}

    assert "RegistrationMixin" not in owners
    assert "DeclarationRegistrationMixin" not in owners
    assert "InheritanceRegistrationMixin" not in owners
    assert "DeclarationNamesMixin" not in owners
    assert "DeclarationContractsMixin" not in owners
    assert "FunctionParameterContractsMixin" not in owners
    assert "HostedAbiDeclarationContractsMixin" not in owners


def test_legacy_analyzer_module_is_removed():
    assert importlib.util.find_spec("src.compiler.python.analyzer.analyzer") is None
    for module in (
        "declaration_contracts",
        "declaration_names",
        "function_parameters",
        "hosted_abi_declarations",
    ):
        assert importlib.util.find_spec(f"src.compiler.python.analyzer.{module}") is None


def test_seeded_analyzer_uses_constructor_contract_and_records_occurrences():
    _, base = analyze("class Base { public int value; }")
    analyzer, result = analyze(
        "class Child extends Base {} int read(Child child) { return child.value; }",
        seed=base,
        record_occurrences=True,
    )

    assert not result.errors
    assert "Base" in analyzer.declarations.class_table
    assert "Child" in analyzer.declarations.class_table
    assert result.occurrences
