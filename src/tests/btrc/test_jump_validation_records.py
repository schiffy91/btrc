"""A replayed validation record must mark the replacement callable body."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def jump_validation_driver(selfhost_driver):
    return selfhost_driver(
        ROOT / "src/tests/btrc/fixtures/JumpValidationDriver.btrc",
        compile_flags=("-pedantic-errors", "-Wall", "-Wextra", "-Werror"),
    )


def test_jump_body_fact_replays_and_rejects_nonbody_nodes(jump_validation_driver):
    result = subprocess.run(
        [str(jump_validation_driver), str(ROOT / "src/language/grammar.ebnf")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_jump_record_fixture_analyzes_without_building():
    from src.compiler.python.application.pipeline import CompilationPipeline
    from src.compiler.python.application.results import CompilerOptions

    source = ROOT / "src/tests/btrc/fixtures/JumpValidationDriver.btrc"
    pipeline = CompilationPipeline()
    options = CompilerOptions(use_cache=False, use_ast_cache=False)
    resolved = pipeline.resolve(source.read_text(), str(source), options)
    parsed = pipeline.parse(resolved, str(source), options)
    analyzed = pipeline.analyze(parsed.program, prune_stdlib=True)
    assert analyzed.errors == []


@pytest.mark.parametrize(
    "source, diagnostic",
    [
        ('void f(bool flag) { if (flag) { jump("done"); } bool value = true; label("done"); }', None),
        ('void f(bool flag) { if (flag) { jump("done"); } int values[2]; label("done"); }', None),
        ('void f(bool flag) { if (flag) { jump("done"); } static int value = 3; label("done"); value++; }', None),
        (
            'void f(bool flag) { if (flag) { jump("done"); } char* value = "owned"; label("done"); }',
            "not a plain C value",
        ),
        (
            'void f(bool flag) { if (flag) { jump("done"); } int value = 3; label("done"); value++; }',
            "used after the label",
        ),
        (
            'void f(bool flag, int count) { if (flag) { jump("done"); } try {} finally { int values[count]; } label("done"); }',
            "jumps into the scope of variable-length array",
        ),
        (
            'string original() { return "owned"; } void f(bool flag) { if (flag) { jump("done"); } char* value = original(); int original = 3; label("done"); }',
            "not a plain C value",
        ),
    ],
)
def test_native_jump_declaration_safety(jump_validation_driver, source, diagnostic):
    result = subprocess.run(
        [str(jump_validation_driver), str(ROOT / "src/language/grammar.ebnf"), source],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if diagnostic is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert diagnostic in result.stderr
