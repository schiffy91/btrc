"""Strict runtime coverage for typed hashing in the real Map/Set stdlib."""

from __future__ import annotations

import functools
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.frontend import get_stdlib_source
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))

COLLECTION_SOURCE = r"""
#include <assert.h>
int main() {
    Vector<int> indexed = [1, 2];
    assert(indexed[0] == 1);
    indexed[1] = 5;
    indexed[0] += 4;
    assert(indexed[0] == 5 && indexed[1] == 5);
    int old = indexed[0]++;
    int current = ++indexed[0];
    assert(old == 5 && current == 7 && indexed[0] == 7);

    Map<float, int> values = {};
    values.put(1.5, 15);
    values.put(-0.0, 7);
    assert(values.get(1.5) == 15);
    assert(values.get(0.0) == 7);

    Set<double> numbers = {};
    numbers.add(-0.0);
    numbers.add(0.0);
    numbers.add(INFINITY);
    assert(numbers.len == 2);
    assert(numbers.contains(0.0));
    assert(numbers.contains(INFINITY));

    Map<string, int> high_hash = {};
    high_hash.put("zzzzzzzz", 9);
    assert(high_hash.get("zzzzzzzz") == 9);
    assert(high_hash.has("zzzzzzzz"));
    indexed.free();
    values.free();
    numbers.free();
    high_hash.free();
    return 0;
}
"""


@functools.lru_cache(maxsize=1)
def _emit_collection_runtime() -> str:
    source = get_stdlib_source(COLLECTION_SOURCE) + "\n" + COLLECTION_SOURCE
    program = Parser(Lexer(source, "<typed-collections>").tokenize()).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors
    return CEmitter().emit(optimize(IRGenerator(analyzed).generate()))


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_float_collections_and_high_unsigned_hash_are_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    c_path = tmp_path / "typed_collections.c"
    binary = tmp_path / "typed_collections"
    c_path.write_text(_emit_collection_runtime())
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(c_path),
            "-lm",
            "-lpthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, timeout=10)
