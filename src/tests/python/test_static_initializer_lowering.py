"""Typed IR and strict-C contracts for static-storage initializers."""

from __future__ import annotations

import dataclasses
import functools
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import SemanticAnalyzer
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.ir.lowering.lowerer import IRLowerer
from src.compiler.python.ir.nodes import (
    IRAddressOf,
    IRBinOp,
    IRCall,
    IRCast,
    IRIndex,
    IRNode,
    IRTernary,
    IRVarDecl,
)
from src.compiler.python.lexer.lexer import Lexer
from src.compiler.python.parser.parser import Parser

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

STATIC_INITIALIZER_SOURCE = """
int values[5] = {20 + 1, 7 * 6, 126 / 3, 85 % 43, (9 > 3) ? 42 : 0};
bool flags[6] = {1 < 2, 2 <= 2, 3 > 2, 3 >= 3, 4 == 4, 4 != 5};
int globalValue = (int)(42.0 / 2.0) + (24 - 3);
int* globalPointer = values + (84 / 42);
int* indexedPointer = &values[9 - 7];
int* castPointer = (int*)(values + (126 / 63));

class Constants {
    class int classValue = (9 >= 3) ? 84 / 2 : 0;
    class int* classPointer = &values[84 / 42];
}

int main() {
    static int localValue = (7 <= 8) ? 84 / 2 : 0;
    static int* localPointer = values + ((int)(6.0 / 3.0));
    return values[0] == 21 && values[1] == 42 && values[2] == 42 &&
        values[3] == 42 && values[4] == 42 && globalValue == 42 &&
        *globalPointer == 42 && *indexedPointer == 42 && *castPointer == 42 &&
        Constants.classValue == 42 && *Constants.classPointer == 42 &&
        localValue == 42 && *localPointer == 42 && flags[0] && flags[1] &&
        flags[2] && flags[3] && flags[4] && flags[5] ? 0 : 1;
}
"""


def _analyze(source: str):
    program = Parser(Lexer(source, "<static-initializer>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _lower(source: str):
    analyzed = _analyze(source)
    assert analyzed.errors == []
    return IRLowerer(analyzed).lower()


@functools.cache
def _generated_static_initializers() -> str:
    module = _lower(STATIC_INITIALIZER_SOURCE)
    pipeline = CompilationPipeline()
    module = pipeline.optimize(module, CompilerOptions())
    return pipeline.emit(module)


def _ir_nodes(root: object):
    if isinstance(root, IRNode):
        yield root
        for field in dataclasses.fields(root):
            yield from _ir_nodes(getattr(root, field.name))
    elif isinstance(root, (list, tuple)):
        for item in root:
            yield from _ir_nodes(item)


def test_static_initializers_are_structured_constant_ir_without_runtime_calls() -> None:
    module = _lower(STATIC_INITIALIZER_SOURCE)
    initializers = [declaration.init for declaration in module.global_decls if declaration.init is not None]
    initializers.extend(
        node.init
        for function in module.function_defs
        for node in _ir_nodes(function.body)
        if isinstance(node, IRVarDecl) and node.is_static and node.init is not None
    )
    nodes = [node for initializer in initializers for node in _ir_nodes(initializer)]

    assert not any(isinstance(node, IRCall) for node in nodes)
    assert {node.op for node in nodes if isinstance(node, IRBinOp)} >= {
        "+",
        "-",
        "*",
        "/",
        "%",
        "<",
        "<=",
        ">",
        ">=",
        "==",
        "!=",
    }
    assert any(isinstance(node, IRCast) for node in nodes)
    assert any(isinstance(node, IRTernary) for node in nodes)
    assert any(isinstance(node, IRAddressOf) for node in nodes)
    assert any(isinstance(node, IRIndex) for node in nodes)
    assert not any(helper.name in {"__btrc_div", "__btrc_mod"} for helper in module.helper_decls)


def test_runtime_division_and_modulo_keep_checked_helper_lowering() -> None:
    module = _lower(
        "int calculate(int value) { "
        "int results[2] = {84 / value, 85 % value}; "
        "return results[0] + results[1]; "
        "} int main() { return calculate(43) == 43 ? 0 : 1; }"
    )
    helper_calls = {
        node.helper_ref
        for function in module.function_defs
        for node in _ir_nodes(function.body)
        if isinstance(node, IRCall) and node.helper_ref
    }

    assert {"__btrc_div", "__btrc_mod"} <= helper_calls


@pytest.mark.parametrize(
    "source",
    (
        "int run() { return 1; } int value = run(); int main() { return value; }",
        "int run() { return 1; } class Values { class int value = run(); } int main() { return 0; }",
        "int run() { return 1; } int main() { static int value = run(); return value; }",
        "int value = 1 / 0; int main() { return value; }",
        "class Values { class int value = 1 / 0; } int main() { return 0; }",
        "int main() { static int value = 1 / 0; return value; }",
    ),
    ids=("global-call", "class-call", "local-call", "global-zero", "class-zero", "local-zero"),
)
def test_dynamic_or_zero_static_initializers_remain_rejected(source: str) -> None:
    analyzed = _analyze(source)

    assert any("requires a C constant/address initializer" in error for error in analyzed.errors)


@pytest.mark.skipif(not COMPILERS, reason="requires GCC or Clang")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_static_initializer_operators_are_strict_c11_and_runtime_correct(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    generated = _generated_static_initializers()
    assert "__btrc_div(" not in generated
    assert "__btrc_mod(" not in generated
    assert "static int globalValue" in generated
    assert "static int Constants_classValue" in generated
    assert "static int localValue" in generated

    source_path = tmp_path / "static-initializers.c"
    executable = tmp_path / "static-initializers"
    source_path.write_text(generated, encoding="utf-8")
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source_path),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr

    executed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr
