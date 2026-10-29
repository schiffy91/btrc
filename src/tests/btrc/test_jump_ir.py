"""Native IR jump contracts; the semantic check requires no native build."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "src/tests/btrc/fixtures/JumpIRDriver.btrc"


@pytest.fixture(scope="module")
def jump_ir_driver(selfhost_driver):
    return selfhost_driver(SOURCE, compile_flags=("-pedantic-errors", "-Wall", "-Wextra", "-Werror"))


def test_jump_ir_fixture_analyzes_without_building():
    from src.compiler.python.application.pipeline import CompilationPipeline
    from src.compiler.python.application.results import CompilerOptions

    pipeline = CompilationPipeline()
    options = CompilerOptions(use_cache=False, use_ast_cache=False)
    resolved = pipeline.resolve(SOURCE.read_text(), str(SOURCE), options)
    parsed = pipeline.parse(resolved, str(SOURCE), options)
    analyzed = pipeline.analyze(parsed.program, prune_stdlib=True)
    assert analyzed.errors == []


@pytest.mark.parametrize(
    "mode, diagnostic",
    [
        ("valid", None),
        ("missing", "has no label"),
        ("unused", "has no goto"),
        ("duplicate", "Duplicate IR label"),
        ("nested", "nested statement list"),
        ("sibling", "nested statement list"),
        ("setjmp", "exception or autorelease boundary"),
        ("realtime", "backward goto"),
    ],
)
def test_native_ir_jump_contract(jump_ir_driver, mode, diagnostic):
    result = subprocess.run([str(jump_ir_driver), mode], capture_output=True, text=True, timeout=60)
    if diagnostic is None:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "goto done;" in result.stdout
        assert "done: ;" in result.stdout
    else:
        assert result.returncode != 0
        assert diagnostic in result.stdout + result.stderr
