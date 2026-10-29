"""A replayed validation record must mark the replacement callable body."""

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_jump_body_fact_replays_and_rejects_nonbody_nodes(selfhost_driver):
    driver = selfhost_driver(
        ROOT / "src/tests/btrc/fixtures/JumpValidationDriver.btrc",
        compile_flags=("-pedantic-errors", "-Wall", "-Wextra", "-Werror"),
    )
    result = subprocess.run(
        [str(driver), str(ROOT / "src/language/grammar.ebnf")],
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
