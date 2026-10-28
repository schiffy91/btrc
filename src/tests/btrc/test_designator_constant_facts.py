"""Known designated indexes survive analysis and relocated validation records."""

import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import Designation, IndexDesignator

REPO = Path(__file__).resolve().parents[3]

CASES = [
    ("0", 0),
    ("(1 << 40) + 7", 1099511627783),
    ("9223372036854775807", 9223372036854775807),
    ("-9223372036854775807 - 1", -9223372036854775808),
    ("(unsigned char)300", 44),
]
REFUSALS = [
    ("index", "Array designator index must be an integer constant expression"),
    ("1.5", "Array designator index must be an integer constant expression"),
    ("sizeof(int)", "Array designator index is a constant expression btrc cannot evaluate; write its integer value"),
    (
        "18446744073709551615ULL",
        "Array designator index is a constant expression btrc cannot evaluate; write its integer value",
    ),
    ("9223372036854775807 + 1", "Array designator index must be an integer constant expression"),
]


def program_with_index(expression):
    # r10 parsing is a separate increment. Feed its existing ASDL shape to the
    # real analyzer now, so facts and cache replay are tested before lowering.
    program = Parser(
        Lexer("int main() { int index = 0; int values[(1LL << 40) + 7] = {0}; return 0; }").tokenize()
    ).parse()
    brace = program.declarations[0].body.statements[1].initializer
    index = IndexDesignator(index=Parser(Lexer(expression).tokenize())._parse_expr(), line=4, col=9)
    brace.entries = [Designation(parts=[index])]
    return program, index


@pytest.mark.parametrize(("expression", "expected"), CASES)
def test_reference_records_full_width_index_values(expression, expected):
    program, index = program_with_index(expression)
    analyzer = SemanticAnalyzer()
    result = analyzer.analyze(program)
    assert result.errors == []
    assert result.designator_index_values == {id(index): expected}
    bound = program.declarations[0].body.statements[1].type.array_size
    assert result.array_bound_values == {id(bound): 1099511627783}
    # Facts are compilation-local, including when the analyzer is reused.
    empty = Parser(Lexer("int main() { return 0; }").tokenize()).parse()
    next_result = analyzer.analyze(empty)
    assert next_result.designator_index_values == {}
    assert next_result.array_bound_values == {}
    assert result.array_bound_values == {id(bound): 1099511627783}
    assert result.designator_index_values == {id(index): expected}


@pytest.mark.parametrize(("expression", "diagnostic"), REFUSALS)
def test_reference_refuses_nonconstant_or_unknown_index_values(expression, diagnostic):
    program, index = program_with_index(expression)
    result = SemanticAnalyzer().analyze(program)
    assert any(diagnostic in error for error in result.errors), result.errors
    assert id(index) not in result.designator_index_values


@pytest.fixture(scope="module")
def designator_driver(selfhost_driver):
    return selfhost_driver(
        REPO / "src/tests/btrc/fixtures/DesignatorFactsDriver.btrc",
        compile_flags=("-pedantic-errors", "-Wall", "-Wextra", "-Werror"),
    )


@pytest.mark.parametrize(("expression", "expected"), CASES)
def test_selfhost_records_and_replays_full_width_index_values(designator_driver, expression, expected):
    result = subprocess.run(
        [str(designator_driver), str(REPO / "src/language/grammar.ebnf"), expression],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"{expected}\n"


@pytest.mark.parametrize(("expression", "diagnostic"), REFUSALS)
def test_selfhost_refuses_nonconstant_or_unknown_index_values(designator_driver, expression, diagnostic):
    result = subprocess.run(
        [str(designator_driver), str(REPO / "src/language/grammar.ebnf"), expression],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert diagnostic in result.stderr, result.stderr
