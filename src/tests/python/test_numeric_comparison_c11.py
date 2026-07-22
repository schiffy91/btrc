"""Strict-C contracts for mixed signed/unsigned comparison lowering."""

from __future__ import annotations

import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.nodes import IRBinOp, IRCast
from src.compiler.python.ir.optimizer_walk import iter_ir_nodes
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
COMPARISON_OPERATORS = {"==", "!=", "<", ">", "<=", ">="}

RUNTIME_SOURCE = r"""
#include <assert.h>

enum Rank { Low, High };

bool compareUnsignedInt(unsigned int value, int same, int lower) {
    return value == 42 && 42 == value
        && value != 41 && 41 != value
        && value == same && same == value
        && value != lower && lower != value
        && value > 41 && 41 < value
        && value >= 42 && 42 <= value
        && value > lower && lower < value
        && value >= same && same <= value;
}

bool compareUnsignedLongLong(
        unsigned long long value, long long same, long long lower) {
    return value == 42 && 42 == value
        && value != 41 && 41 != value
        && value == same && same == value
        && value != lower && lower != value
        && value > 41 && 41 < value
        && value >= 42 && 42 <= value
        && value > lower && lower < value
        && value >= same && same <= value;
}

bool compareSameTypes(size_t left, size_t right, Rank low, Rank high) {
    return left == right && low < high;
}

int main() {
    assert(compareUnsignedInt(42u, 42, 41));
    assert(compareUnsignedLongLong(42ULL, 42LL, 41LL));
    size_t amount = 7;
    assert(compareSameTypes(amount, amount, Low, High));
    print("PASS: numeric comparison C11");
    return 0;
}
"""


def _analyze(source: str):
    program = Parser(Lexer(source, "<numeric-comparison>").tokenize()).parse()
    return SemanticAnalyzer().analyze(program)


def _generate(source: str):
    analyzed = _analyze(source)
    assert analyzed.errors == []
    return IRGenerator(analyzed).generate()


def _comparisons(module):
    return [node for node in iter_ir_nodes(module) if isinstance(node, IRBinOp) and node.op in COMPARISON_OPERATORS]


def test_mixed_comparisons_normalize_both_operands_in_structured_ir():
    module = _generate("""
        bool compare(uint value, int signedValue,
                     unsigned long long wide, long long signedWide) {
            return value == 1 && 1 != value
                && value < signedValue && signedValue >= value
                && wide == 1 && 1 <= wide
                && wide > signedWide && signedWide != wide;
        }
    """)
    comparisons = _comparisons(module)

    assert Counter(node.op for node in comparisons) == Counter({"==": 2, "!=": 2, "<": 1, ">=": 1, "<=": 1, ">": 1})
    assert all(isinstance(node.left, IRCast) for node in comparisons)
    assert all(isinstance(node.right, IRCast) for node in comparisons)
    targets = Counter(node.left.target_type.text for node in comparisons)
    assert targets == Counter({"unsigned int": 4, "unsigned long long": 4})
    assert all(node.left.target_type == node.right.target_type for node in comparisons)


def test_same_type_comparisons_and_arithmetic_remain_direct():
    module = _generate("""
        enum Rank { Low, High };
        bool same(uint left, uint right, size_t a, size_t b,
                  Rank low, Rank high) {
            return left == right && a == b && low < high;
        }
        uint add(uint value, int delta) { return value + delta; }
    """)

    comparisons = _comparisons(module)
    addition = next(node for node in iter_ir_nodes(module) if isinstance(node, IRBinOp) and node.op == "+")
    assert len(comparisons) == 3
    assert all(not isinstance(node.left, IRCast) for node in comparisons)
    assert all(not isinstance(node.right, IRCast) for node in comparisons)
    assert not isinstance(addition.left, IRCast)
    assert not isinstance(addition.right, IRCast)


def test_abi_dependent_mixed_comparison_still_fails_closed():
    analyzed = _analyze("int main() { size_t value = 1; return value < 2; }")

    assert any("mixes ABI-dependent integer type" in error for error in analyzed.errors)


@pytest.mark.skipif(not COMPILERS, reason="requires a strict C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_mixed_comparison_runtime_is_warning_free_c11(
    tmp_path: Path,
    c_compiler: str,
):
    source = tmp_path / f"comparison-{Path(c_compiler).name}.c"
    executable = source.with_suffix("")
    source.write_text(emit_c(RUNTIME_SOURCE))
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-lm",
            "-lpthread",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
    assert run.returncode == 0, run.stderr
    assert run.stdout == "PASS: numeric comparison C11\n"
