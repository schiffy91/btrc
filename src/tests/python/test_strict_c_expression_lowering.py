"""Focused strict-C11 contracts for expression lowering."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.semantic_analyzer import SemanticAnalyzer
from src.compiler.python.ast_nodes import IntLiteral
from src.compiler.python.ir.gen.generics.user_emitter import _UserGenericEmitter
from src.compiler.python.ir.gen.literal_text import format_c_integer_literal
from src.compiler.python.ir.gen.lowerer import IRLowerer
from src.compiler.python.ir.gen.types import CTypeRenderer
from src.compiler.python.ir.nodes import IRBinOp, IRCall, IRLiteral, IRVar
from src.compiler.python.ir.optimizer_walk import IRTree
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.python.test_codegen import emit_c
from src.tests.python.test_typed_operator_contract import COMPILERS

CLANG = shutil.which("clang")


def _generate(source: str):
    program = Parser(Lexer(source, "<strict-c-expression>").tokenize()).parse()
    analyzed = SemanticAnalyzer().analyze(program)
    assert not analyzed.errors
    return IRLowerer(analyzed).lower()


@pytest.mark.parametrize(
    ("raw", "value", "expected"),
    [
        ("0b0", 0, "0x0"),
        ("0B1010", 10, "0xa"),
        ("0b101U", 5, "0x5U"),
        ("0B1111ull", 15, "0xfull"),
        ("0b1001LLU", 9, "0x9LLU"),
        ("0o17", 15, "017"),
        ("0O20UL", 16, "020UL"),
        ("0x2aLL", 42, "0x2aLL"),
        ("42u", 42, "42u"),
        ("", 7, "7"),
    ],
)
def test_integer_literal_formatter_produces_c11_text(
    raw: str,
    value: int,
    expected: str,
):
    assert format_c_integer_literal(raw, value) == expected


def test_binary_literal_never_leaks_into_emitted_c():
    c = emit_c("""
        unsigned long long mask() { return 0B101010ULL; }
        int main() { return (int)(mask() & 0b1111u); }
    """)

    assert not re.search(r"\b0[bB]", c)
    assert "0x2aULL" in c
    assert "0xfu" in c


def test_generic_integer_literal_uses_the_same_c11_formatter():
    emitter = _UserGenericEmitter({}, "Box_int", CTypeRenderer())
    literal = IntLiteral(value=10, raw="0B1010ULL")

    lowered = emitter._expr(literal)

    assert isinstance(lowered, IRLiteral)
    assert lowered.text == "0xaULL"


def test_all_string_comparisons_are_structured_strcmp_operations():
    source = """
        int main() {
            string a = "abc";
            string b = "def";
            bool eq = a == b;
            bool ne = a != b;
            bool lt = a < b;
            bool gt = a > b;
            bool le = a <= b;
            bool ge = a >= b;
            return (int)(eq || ne || lt || gt || le || ge);
        }
    """
    module = _generate(source)
    comparisons = [
        node
        for node in IRTree(module)
        if (
            isinstance(node, IRBinOp)
            and node.op in {"==", "!=", "<", ">", "<=", ">="}
            and isinstance(node.right, IRLiteral)
            and node.right.text == "0"
            and any(isinstance(inner, IRCall) and inner.callee == "strcmp" for inner in IRTree(node.left))
        )
    ]

    assert {comparison.op for comparison in comparisons} == {
        "==",
        "!=",
        "<",
        ">",
        "<=",
        ">=",
    }
    assert len(comparisons) == 6
    assert all(isinstance(comparison.right, IRLiteral) and comparison.right.text == "0" for comparison in comparisons)

    c = emit_c(source)
    assert c.count("strcmp(") == 6


def test_string_comparison_evaluates_each_operand_once():
    source = """
        string left_value() { return "abc"; }
        string right_value() { return "def"; }
        int main() { return (int)(left_value() < right_value()); }
    """
    module = _generate(source)
    strcmp_call = next(node for node in IRTree(module) if isinstance(node, IRCall) and node.callee == "strcmp")

    assert all(isinstance(argument, IRVar) for argument in strcmp_call.args)
    calls = [
        node.callee
        for node in IRTree(module)
        if isinstance(node, IRCall) and node.callee in {"left_value", "right_value"}
    ]
    assert calls.count("left_value") == calls.count("right_value") == 1

    main_c = emit_c(source).split("int main(void)", 1)[1]
    assert main_c.count("left_value()") == 1
    assert main_c.count("right_value()") == 1


@pytest.mark.skipif(not CLANG, reason="requires Clang's default depth limit")
def test_long_string_concat_has_bounded_c_expression_depth(tmp_path: Path):
    expression = " + ".join('"x"' for _ in range(500))
    emitted = emit_c(
        "string joined() { return "
        + expression
        + "; }\n"
        + "int main() { string value = joined(); "
        + "return value.length() == 500 ? 0 : 1; }\n"
    )
    source = tmp_path / "long_string_concat.c"
    executable = tmp_path / "long_string_concat"
    source.write_text(emitted)
    compiled = subprocess.run(
        [
            CLANG,
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
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    subprocess.run([str(executable)], check=True, timeout=15)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_optional_scalar_coalesce_is_single_evaluation_and_strict_c11(
    tmp_path: Path,
    c_compiler: str,
):
    source = """
        int calls = 0;
        class Box {
            public int value;
            public Box(int value) { self.value = value; }
        }
        Box? make(int value) {
            calls += 1;
            if (value == 0) { return null; }
            return new Box(value);
        }
        int main() {
            int present = make(7)?.value ?? 5;
            int absent = make(0)?.value ?? 5;
            return present == 7 && absent == 5 && calls == 2 ? 0 : 1;
        }
    """
    emitted = emit_c(source)
    main_c = emitted.split("int main(void)", 1)[1]
    assert main_c.count("make(7)") == 1
    assert main_c.count("make(0)") == 1
    assert "__nc" not in main_c

    c_path = tmp_path / "optional_coalesce.c"
    executable = tmp_path / "optional_coalesce"
    c_path.write_text(emitted)
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(c_path),
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
