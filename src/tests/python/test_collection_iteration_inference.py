"""Focused collection inference and strict-C iteration regressions."""

from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
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
    pipeline = CompilationPipeline()
    module = pipeline.optimize(IRLowerer(analyzed).lower(), CompilerOptions())
    return pipeline.emit(module)


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
def test_inferred_vector_literal_import_materializes_live_specialization(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    source = """
        import std.vector;

        int main() {
            var nums = [10, 20, 30];
            int sum = 0;
            for value in nums { sum += value; }
            nums.free();
            return sum == 60 ? 0 : 1;
        }
    """
    source_path = tmp_path / "inferred_vector.btrc"
    source_path.write_text(source)
    result = Compiler().compile(
        source,
        str(source_path),
        CompilerOptions(use_cache=False),
    )

    assert result.successful, result.failure or result.diagnostics
    assert result.c_source is not None
    assert "btrc_Vector_int* nums" in result.c_source
    assert "struct btrc_Vector_int {" in result.c_source
    for function in (
        "btrc_Vector_int_new",
        "btrc_Vector_int_push",
        "btrc_Vector_int_iterLen",
        "btrc_Vector_int_iterGet",
        "btrc_Vector_int_free",
    ):
        assert function in result.c_source
    _compile_and_run(result.c_source, tmp_path, c_compiler)


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
