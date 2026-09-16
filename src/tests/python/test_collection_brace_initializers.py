"""Only the empty brace initializer builds a managed collection."""

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _analyze(source: str):
    program = Parser(Lexer(source, "<brace-collection>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def test_set_with_elements_in_braces_is_rejected_before_invalid_c_lowering() -> None:
    analyzed = _analyze("import Library.Set;\nint main() { Set<int> seen = {1, 2, 3}; return seen.size(); }")

    assert any(
        "cannot use a non-empty brace initializer for 'Set'; '{}' creates an empty Set and add() inserts elements"
        in error
        for error in analyzed.errors
    )


def test_vector_with_elements_in_braces_is_rejected() -> None:
    vector = _analyze("import Library.Vector;\nint main() { Vector<int> xs = {1, 2}; return xs.size(); }")

    assert any(
        "cannot use a non-empty brace initializer for 'Vector'; use a list literal [...]" in error
        for error in vector.errors
    )


def test_empty_braces_and_arrays_keep_working() -> None:
    analyzed = _analyze(
        "import Library.Set;\nimport Library.Map;\n"
        "int main() { Set<int> seen = {}; Map<string, int> m = {}; int[] values = {1, 2}; "
        "seen.add(values[0]); return seen.size() + m.size(); }"
    )

    assert analyzed.errors == []
