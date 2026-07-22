"""Tuple fields are typed, bounded, and valid strict-C update targets."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _analyze(source: str):
    program = Parser(Lexer(source, "<tuple-fields>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def test_tuple_field_indices_are_typed_and_validated():
    valid = _analyze("""
        int main() {
            (int, string) value = (7, "seven");
            int number = value._0;
            string text = value._1;
            return number - text.len();
        }
    """)
    invalid = _analyze("""
        void run() {
            (int, int) value = (1, 2);
            int tooFar = value._2;
            int named = value.other;
            int nonCanonical = value._00;
        }
    """)

    assert valid.errors == []
    messages = "\n".join(invalid.errors)
    assert "Tuple field '_2' is out of range for 2 element(s)" in messages
    assert "Tuple has no field 'other'" in messages
    assert "Tuple has no field '_00'" in messages


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_tuple_field_compound_updates_compile_and_run_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    c_source = emit_c("""
        int main() {
            (int, int) value = (10, 20);
            value._0 += 5;
            value._1 *= 2;
            value._0 -= 3;
            return value._0 == 12 && value._1 == 40 ? 0 : 1;
        }
    """)
    source_path = tmp_path / "tuple_updates.c"
    executable = tmp_path / "tuple_updates"
    source_path.write_text(c_source)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source_path),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable)], check=True, timeout=10)
