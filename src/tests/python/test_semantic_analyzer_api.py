"""Public behavior contracts for semantic analysis."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.program import AnalysisContext
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def analyze(source: str, **options):
    program = Parser(Lexer(source, "<test>").tokenize()).parse()
    analyzer = SemanticAnalyzer(**options)
    return analyzer, analyzer.analyze(program)


def test_semantic_analyzer_returns_registered_declarations():
    _, result = analyze("class Item {} int main() { return 0; }")

    assert set(result.class_table) == {"Item"}
    assert set(result.function_table) == {"main"}


def test_semantic_analyzer_returns_diagnostics_on_the_result():
    _, result = analyze("int main() { int __bad = 0; return __bad; }")

    assert result.errors
    assert result.diags


def test_callable_value_analysis_tracks_the_active_lexical_scope():
    program = Parser(
        Lexer(
            """
            void accept(__fn_ptr<int> callback) {}
            void run() {
                int offset = 1;
                var callback = () => offset;
                accept(callback);
            }
            """,
            "<test>",
        ).tokenize()
    ).parse()
    analyzer = SemanticAnalyzer()

    result = analyzer.analyze(program)

    assert any("environment-requiring callable value" in error for error in result.errors)


def test_analysis_context_restores_nested_source_provenance():
    program = Parser(Lexer("int main() { return 0; }", "<test>").tokenize()).parse()
    program.declarations[0].source_file = "inner.btrc"
    context = AnalysisContext()

    with context.source("outer.btrc"):
        for _declaration in context.declarations(program):
            assert context.current_source_file == "inner.btrc"
        assert context.current_source_file == "outer.btrc"

    assert context.current_source_file is None


def test_seeded_analyzer_uses_constructor_contract_and_records_occurrences():
    _, base = analyze("class Base { public int value; }")
    analyzer, result = analyze(
        "class Child extends Base {} int read(Child child) { return child.value; }",
        seed=base,
        record_occurrences=True,
    )

    assert not result.errors
    assert "Base" in analyzer.index.class_table
    assert "Child" in analyzer.index.class_table
    assert result.occurrences
