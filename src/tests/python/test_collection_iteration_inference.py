"""Focused collection inference and strict-C iteration regressions."""

from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.backend.c_emitter import CEmitter
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.optimizer import IROptimizer
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_strict_c_semantic_boundaries import (
    COMPILERS,
    _compile_and_run,
)


def _analyze(source: str):
    program = Parser(Lexer(source, "<collection-regression>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _emit(source: str) -> str:
    analyzed = _analyze(source)
    assert analyzed.errors == []
    return CEmitter().emit(IROptimizer(IRLowerer(analyzed).lower()).optimize())


def test_string_array_index_preserves_string_element_shape() -> None:
    analyzed = _analyze(
        """
        #include <string.h>
        int main() {
            string words[] = {"hello", "world"};
            return strcmp(words[1], "world");
        }
        """
    )

    assert analyzed.errors == []


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_ignored_string_iteration_binding_is_strict_c11(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    generated = _emit(
        """
        int main() {
            int count = 0;
            for ignored in "abc" { count += 1; }
            return count == 3 ? 0 : 1;
        }
        """
    )

    assert "(void)(ignored);" in generated
    _compile_and_run(generated, tmp_path, c_compiler)
