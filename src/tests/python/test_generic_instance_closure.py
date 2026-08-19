"""SemanticAnalyzer-level generic closure paths that do not require code emission."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<generic-closure>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _instance_arguments(analyzed, base: str) -> set[tuple[str, ...]]:
    return {tuple(argument.base for argument in arguments) for arguments in analyzed.generic_instances.get(base, ())}


def test_static_initializer_is_scanned_before_fail_closed_storage_error():
    analyzed = _analyze(
        """
        class StaticNested<T> { public StaticNested() {} }
        class StaticSeed<T> {
            class size_t nestedSize = sizeof(StaticNested<T>);
            public StaticSeed() {}
        }
        int main() {
            StaticSeed<int> seed = new StaticSeed<int>();
            delete seed;
            return 0;
        }
        """
    )

    assert any("not supported on a generic class" in error for error in analyzed.errors)
    assert ("int",) in _instance_arguments(analyzed, "StaticNested")


def test_nested_generic_inside_lambda_body_closes_under_class_substitution():
    analyzed = _analyze(
        """
        class LambdaNested<T> { public LambdaNested() {} }
        class LambdaSeed<T> {
            public void prepare() {
                var callback = () => {
                    LambdaNested<T> nested = new LambdaNested<T>();
                    delete nested;
                };
            }
        }
        int main() {
            LambdaSeed<int> seed = new LambdaSeed<int>();
            delete seed;
            return 0;
        }
        """
    )

    assert ("int",) in _instance_arguments(analyzed, "LambdaNested")


__all__ = []
