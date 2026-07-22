"""Durable API and ownership contracts for semantic analysis."""

import importlib.util

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


def test_registration_mixins_are_absent_from_semantic_analyzer_mro():
    owners = {owner.__name__ for owner in SemanticAnalyzer.__mro__}

    assert "RegistrationMixin" not in owners
    assert "DeclarationRegistrationMixin" not in owners
    assert "InheritanceRegistrationMixin" not in owners


def test_legacy_analyzer_module_is_removed():
    assert importlib.util.find_spec("src.compiler.python.analyzer.analyzer") is None


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
