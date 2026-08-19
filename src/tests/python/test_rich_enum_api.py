"""Public rich-enum method API and generated-symbol boundary."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _errors(source: str) -> list[str]:
    tokens = Lexer(source, "<rich-enum-api>").tokenize()
    program = Parser(tokens).parse()
    return SemanticAnalyzer().analyze(program).errors


def test_rich_enum_to_string_is_a_public_zero_argument_method() -> None:
    source = """
        enum class Shape { Circle(double radius), Point }
        int main() {
            Shape shape = Shape.Circle(5.0);
            string name = shape.toString();
            return name == "Circle" ? 0 : 1;
        }
    """

    assert _errors(source) == []


def test_rich_enum_to_string_rejects_arguments() -> None:
    errors = _errors(
        'enum class Shape { Point } int main() { Shape shape = Shape.Point(); shape.toString("extra"); return 0; }',
    )

    assert any("Shape.toString()' expects 0 argument(s) but got 1" in error for error in errors)


def test_rich_enum_generated_formatter_is_not_a_source_api() -> None:
    errors = _errors(
        "enum class Shape { Point } int main() { Shape shape = Shape.Point(); Shape_toString(shape); return 0; }",
    )

    assert any("compiler-generated C symbol 'Shape_toString'" in error for error in errors)
