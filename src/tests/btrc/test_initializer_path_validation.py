"""C2 typed initializer paths retain storage identity before parser activation."""

import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.analyzer.types import TypeSystem
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.compiler.python.syntax.ast.generated import (
    Designation,
    FieldAccessExpr,
    FieldDesignator,
    IndexDesignator,
    IndexExpr,
)

REPO = Path(__file__).resolve().parents[3]
PAIR = "struct Pair { int x; int y; };"
FRAME = PAIR + "struct Frame { struct Pair point; int tail; };"
ANONYMOUS = "struct Frame { union { struct { int x; int y; }; double real; }; int tail; };"
CASES = [
    (PAIR, "Pair", (".missing",), "1", "Struct 'Pair' has no field 'missing'"),
    (FRAME, "Frame", (".point.missing",), "1", "Struct 'Pair' has no field 'missing'"),
    (
        FRAME,
        "Frame",
        (".tail", ".point.y", "pos"),
        "3, 1, 4",
        "Field 'tail' of struct 'Frame' is initialized more than once",
    ),
    (ANONYMOUS, "Frame", ("pos", ".x"), "{{1, 2}}, 3", "Field 'x' of struct 'Frame' is initialized more than once"),
    (PAIR, "Pair", (".x", ".x"), "1, 2", "Field 'x' of struct 'Pair' is initialized more than once"),
    (
        FRAME,
        "Frame",
        (".point", ".point.x"),
        "{1, 2}, 3",
        "Field 'point' of struct 'Frame' is initialized more than once",
    ),
    (
        FRAME,
        "Frame",
        (".point.x", ".point"),
        "1, {2, 3}",
        "Field 'point' of struct 'Frame' is initialized more than once",
    ),
    (FRAME, "Frame", (".point.y", ".tail", ".point.x"), "2, 3, 1", None),
    (FRAME, "Frame", (".point.x", "pos"), "1, 3", None),
    (ANONYMOUS, "Frame", (".x", ".y"), "1, 2", None),
    (ANONYMOUS, "Frame", (".x", ".real"), "1, 2.0", "Union 'Frame' initializer sets both"),
    (
        ANONYMOUS,
        "Frame",
        (".x", "pos"),
        "1, 2",
        "A positional initializer cannot follow a designator into an anonymous member",
    ),
    (
        "union Value { int integer; double real; };",
        "Value",
        (".integer", ".real"),
        "1, 2.0",
        "Union 'Value' initializer sets both 'integer' and 'real'",
    ),
    ("struct Frame { int values[3]; };", "Frame", (".values[0]", ".values[2]"), "1, 2", None),
    (
        "struct Frame { int values[3]; };",
        "Frame",
        (".values[1 + 1]", ".values[2]"),
        "1, 2",
        "Field 'values' of struct 'Frame' is initialized more than once",
    ),
    ("typedef int Number; struct Frame { Number values[3]; };", "Frame", (".values[0]",), "1", None),
    (
        "struct Frame { int values[4]; };",
        "Frame",
        (".values[-1]",),
        "1",
        "Array designator index -1 is outside 'int[4]'",
    ),
    ("struct Frame { int values[4]; };", "Frame", (".values[4]",), "1", "Array designator index 4 is outside 'int[4]'"),
    (
        "struct Frame { int values[2 + 2]; };",
        "Frame",
        (".values[5]",),
        "1",
        "Array designator index 5 is outside 'int[4]'",
    ),
    ("struct Frame { int values[2 + 2]; };", "Frame", (".values[3]",), "1", None),
    ("struct Frame { int values[(1LL << 40) + 7]; };", "Frame", (".values[(1LL << 40) + 6]",), "1", None),
    (
        "struct Frame { int values[(1LL << 40) + 7]; };",
        "Frame",
        (".values[(1LL << 40) + 7]",),
        "1",
        "Array designator index 1099511627783 is outside 'int[1099511627783]'",
    ),
    (
        "typedef int Number; struct Frame { Number values[2 + 2]; };",
        "Frame",
        (".values[4]",),
        "1",
        "Array designator index 4 is outside 'int[4]'",
    ),
    (FRAME, "Frame", (".point[2]",), "1", "Designator '[2]' needs an array, but the initialized type is 'Pair'"),
    (PAIR, "Pair", ("[2]",), "1", "Designator '[2]' needs an array, but the initialized type is 'Pair'"),
    (
        "struct Frame { int values[4]; };",
        "Frame",
        (".values.x",),
        "1",
        "Designator '.x' needs a struct or union, but the initialized type is 'int[4]'",
    ),
]


def parse(source):
    return Parser(Lexer(source).tokenize()).parse()


def install_paths(program, paths):
    brace = program.declarations[-1].body.statements[0].initializer
    for offset, path in enumerate(paths):
        parts = []
        if path != "pos":
            expression = Parser(Lexer("value" + path).tokenize())._parse_expr()
            while isinstance(expression, (FieldAccessExpr, IndexExpr)):
                part = (
                    FieldDesignator(field=expression.field)
                    if isinstance(expression, FieldAccessExpr)
                    else IndexDesignator(index=expression.index)
                )
                part.line, part.col = 4, 10 + offset * 10
                parts.insert(0, part)
                expression = expression.obj
        brace.entries.append(Designation(parts=parts))
    return brace


@pytest.mark.parametrize(("declarations", "target", "paths", "values", "diagnostic"), CASES)
def test_reference_validates_initializer_storage_paths(declarations, target, paths, values, diagnostic):
    keyword = "union" if target == "Value" else "struct"
    program = parse(f"{declarations} int main() {{ {keyword} {target} value = {{{values}}}; return 0; }}")
    install_paths(program, paths)
    result = SemanticAnalyzer().analyze(program)
    if diagnostic is None:
        assert result.errors == []
    else:
        assert any(diagnostic in error for error in result.errors), result.errors


def test_cached_initializer_plan_is_bound_to_its_concrete_record():
    program = parse("struct A { int x; }; struct B { double y; }; int main() { struct A value = {0}; return 0; }")
    analyzed = SemanticAnalyzer().analyze(program)
    assert analyzed.errors == []
    brace = program.declarations[-1].body.statements[0].initializer
    record = analyzed.struct_table["B"]
    plan = TypeSystem.initializer_slots(analyzed.initializer_slot_plans, analyzed, record, brace)
    assert plan.slots[0].member.name == "y"
    assert plan.slots[0].type.base == "double"


def test_reconstructed_initializer_plan_uses_exported_array_bounds():
    program = parse("struct Frame { int values[2 + 2]; }; int main() { struct Frame value = {1}; return 0; }")
    brace = install_paths(program, (".values[4]",))
    analyzed = SemanticAnalyzer().analyze(program)
    assert any("Array designator index 4 is outside 'int[4]'" in error for error in analyzed.errors)
    plan = TypeSystem.initializer_slots({}, analyzed, analyzed.struct_table["Frame"], brace)
    assert [message for message, _ in plan.problems] == ["Array designator index 4 is outside 'int[4]'"]
    assert plan.slots == ()


@pytest.fixture(scope="module")
def path_driver(selfhost_driver):
    return selfhost_driver(
        REPO / "src/tests/btrc/fixtures/InitializerPathsDriver.btrc",
        compile_flags=("-pedantic-errors", "-Wall", "-Wextra", "-Werror"),
    )


@pytest.mark.parametrize(("declarations", "target", "paths", "values", "diagnostic"), CASES)
def test_selfhost_validates_initializer_storage_paths(
    path_driver, tmp_path, declarations, target, paths, values, diagnostic
):
    keyword = "union" if target == "Value" else "struct"
    source = tmp_path / "Paths.btrc"
    source.write_text(f"{declarations} int main() {{ {keyword} {target} value = {{{values}}}; return 0; }}")
    result = subprocess.run(
        [str(path_driver), str(REPO / "src/language/grammar.ebnf"), str(source), "\n".join(paths)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if diagnostic is None:
        assert result.returncode == 0, result.stderr
        assert result.stdout == "ok\n"
    else:
        assert result.returncode != 0
        assert diagnostic in result.stderr, result.stderr


def test_selfhost_cached_plan_is_bound_to_its_concrete_record(path_driver, tmp_path):
    source = tmp_path / "Records.btrc"
    source.write_text("struct A { int x; }; struct B { double y; }; int main() { struct A value = {0}; return 0; }")
    result = subprocess.run(
        [str(path_driver), str(REPO / "src/language/grammar.ebnf"), str(source), "pos"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "ok\n"
