"""Strict runtime contracts for lazy optional method calls."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
FIXTURE = Path(__file__).parents[1] / "btrc" / "fixtures" / "optional_call_contracts_runtime.btrc"


def test_optional_reference_result_is_inferred_nullable():
    source = """
        class Box { public Box identity() { return self; } }
        Box? maybe(Box? value) { return value?.identity(); }
    """
    program = Parser(Lexer(source, "<optional-result>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    call = program.declarations[1].body.statements[0].value
    result_type = analyzed.node_types[id(call)]

    assert analyzed.errors == []
    assert result_type.base == "Box"
    assert result_type.is_nullable


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_optional_calls_are_lazy_typed_and_arc_balanced(
    tmp_path: Path,
    c_compiler: str,
):
    c_source = emit_c(FIXTURE.read_text())
    source = tmp_path / f"optional-{Path(c_compiler).name}.c"
    executable = source.with_suffix("")
    source.write_text(c_source)
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    subprocess.run([str(executable)], check=True, timeout=10)
