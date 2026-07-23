"""Semantic-owner tests for Mutex payloads before frontend visibility."""

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser


def _semantic_errors(source: str) -> list[str]:
    program = Parser(Lexer(source, "<mutex-payload-unit>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program).errors


@pytest.mark.parametrize("collection", ["Array", "List", "Map", "Set", "Vector"])
def test_unregistered_runtime_collection_payload_fails_closed(
    collection: str,
) -> None:
    arguments = "int, int" if collection == "Map" else "int"
    errors = _semantic_errors(f"int main() {{ Mutex<{collection}<{arguments}>> value; return 0; }}")

    assert any(
        "Mutex<T> payload type cannot contain runtime-owned collection storage" in error
        and f"('{collection}')" in error
        for error in errors
    )


def test_registered_collection_named_class_is_a_managed_payload() -> None:
    errors = _semantic_errors(
        "class Vector<T> { public int marker; } int main() { Mutex<Vector<int>> value; return 0; }"
    )

    assert errors == []
