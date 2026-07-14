"""Aggregate completeness, contextual initialization, and C ordering."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.emitter import CEmitter
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.optimizer import optimize
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _analyze(source: str):
    program = Parser(Lexer(source, "<aggregate-order>").tokenize()).parse()
    return Analyzer().analyze(program)


def _errors(source: str) -> list[str]:
    return _analyze(source).errors


def _has(errors: list[str], fragment: str) -> bool:
    return any(fragment.lower() in error.lower() for error in errors)


def _emit(source: str) -> str:
    analyzed = _analyze(source)
    assert analyzed.errors == []
    return CEmitter().emit(optimize(IRGenerator(analyzed).generate()))


def _strict_build_and_run(source: str, tmp_path: Path, compiler: str) -> None:
    c_path = tmp_path / f"program-{Path(compiler).name}.c"
    executable = c_path.with_suffix("")
    c_path.write_text(_emit(source))
    built = subprocess.run(
        [
            compiler,
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
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    subprocess.run([str(executable)], check=True, timeout=10)


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "struct Item { Item child; }; int main() { return 0; }",
            "dependency cycle",
        ),
        (
            "struct Left { Right right; }; struct Right { Left left; }; int main() { return 0; }",
            "dependency cycle",
        ),
        (
            "typedef Item Alias; struct Item { Alias child; }; int main() { return 0; }",
            "dependency cycle",
        ),
        (
            "struct Item { (Item, int) child; }; int main() { return 0; }",
            "dependency cycle",
        ),
        (
            "enum class Loop { Next(Loop value), Empty } int main() { return 0; }",
            "dependency cycle",
        ),
        (
            "struct Item; Item value; int main() { return 0; }",
            "incomplete struct 'Item'",
        ),
        (
            "struct Item; struct Box { Item value; }; int main() { return 0; }",
            "incomplete struct 'Item'",
        ),
        (
            "typedef B A; typedef A B; int main() { return 0; }",
            "cyclic typedef",
        ),
        (
            "struct Item; int main() { return sizeof(Item); }",
            "incomplete type 'Item'",
        ),
        (
            "int main() { return sizeof(void); }",
            "sizeof cannot be applied to void",
        ),
        (
            "struct Pair { int left; int right; }; int main() { Pair pair = {1, 2, 3}; return 0; }",
            "initializer elements but struct 'Pair' has 2 fields",
        ),
        (
            'struct Pair { int left; int right; }; int main() { Pair pair = {1, "bad"}; return 0; }',
            "field 'right' expects 'int' but got 'string'",
        ),
        (
            "struct Pair { int left; int right; }; struct Box { Pair pair; }; "
            'int main() { Box box = {{1, "bad"}}; return 0; }',
            "field 'right' expects 'int' but got 'string'",
        ),
    ),
)
def test_invalid_aggregate_contracts_are_rejected(source: str, diagnostic: str):
    assert _has(_errors(source), diagnostic)


@pytest.mark.parametrize(
    ("source", "symbol"),
    (
        ("class Box {} int Box_init() { return 0; }", "Box_init"),
        ("class Box {} int Box_new() { return 0; }", "Box_new"),
        ("class Box {} int Box_destroy() { return 0; }", "Box_destroy"),
        (
            "class Box { class int get_value; public int value { get { return 1; } } }",
            "Box_get_value",
        ),
        (
            "class Box { public int value { get { return 1; } } public int get_value() { return 2; } }",
            "Box_get_value",
        ),
        (
            "class Box { public int _prop_value; public int value { get; } }",
            "_prop_value",
        ),
        (
            "class Base { public int ping() { return 1; } } class Child extends Base {} int Child_ping() { return 2; }",
            "Child_ping",
        ),
        (
            "class Base { public int value { get { return 1; } } } "
            "class Child extends Base {} int Child_get_value() { return 2; }",
            "Child_get_value",
        ),
        ("enum E { A }; int E_A() { return 0; }", "E_A"),
        ("enum E { A }; int E_toString() { return 0; }", "E_toString"),
        (
            "enum class Result { Ok(int value), Empty } int Result_Ok() { return 0; }",
            "Result_Ok",
        ),
        (
            "enum class Result { Ok(int value), Empty } int Result_Ok_Data() { return 0; }",
            "Result_Ok_Data",
        ),
        (
            "enum class Result { Ok(int value), Empty } int Result_Tag() { return 0; }",
            "Result_Tag",
        ),
        ("#define Box_new 1\nclass Box {}", "Box_new"),
        (
            "#define __btrc_arc_visit_Box 1\nclass Leaf {} class Box { public Leaf value; }",
            "__btrc_arc_visit_Box",
        ),
    ),
)
def test_generated_c_symbol_collisions_are_rejected(source: str, symbol: str):
    errors = _errors(f"{source} int main() {{ return 0; }}")
    assert _has(errors, symbol) and _has(errors, "collid")


ORDERING_SOURCE = """
    enum class Payload { PairValue(Pair pair), Empty }
    typedef Pair PairAlias;
    struct Left { Right right; };
    struct Right { int value; };
    struct Pair { int left; int right; };
    typedef Later Alias;
    typedef int Later;

    int main() {
        Left left = {{42}};
        Pair pair = {20, 22};
        PairAlias alias_pair = {20, 22};
        Payload payload = Payload.PairValue(pair);
        (Pair, int) tuple = (pair, 0);
        (int, (int, int)) nested = (0, (20, 22));
        Alias answer = left.right.value;
        return answer == 42
            && payload.data.PairValue.pair.right == 22
            && alias_pair.left + alias_pair.right == 42
            && tuple._0.left == 20
            && nested._1._0 + nested._1._1 == 42 ? 0 : 1;
    }
"""


INITIALIZER_SOURCE = """
    struct Pair { int left; int right; };
    struct Box { Pair pair; int tail; };
    Pair global_pair = {};
    Box global_box = {{20, 22}};
    Pair global_pairs[2] = {{20, 22}, {}};

    Pair makePair() { return {20, 22}; }
    int sum(Pair pair) { return pair.left + pair.right; }

    int main() {
        Pair empty = {};
        Pair assigned = {1};
        assigned = {20, 22};
        Box nested = {{20, 22}};
        Pair made = makePair();
        return global_pair.left == 0 && global_pair.right == 0
            && global_box.pair.left + global_box.pair.right == 42
            && global_box.tail == 0
            && global_pairs[0].left + global_pairs[0].right == 42
            && global_pairs[1].left == 0 && global_pairs[1].right == 0
            && empty.left == 0 && empty.right == 0
            && assigned.left + assigned.right == 42
            && nested.pair.left + nested.pair.right == 42
            && nested.tail == 0 && made.right == 22
            && sum({20, 22}) == 42 ? 0 : 1;
    }
"""


POINTER_SOURCE = """
    struct Left;
    struct Right { Left* left; };
    struct Left { Right* right; };
    int main() {
        Left left = {NULL};
        Right right = {&left};
        left.right = &right;
        return left.right->left == &left
            && sizeof(Left*) == sizeof(void*) ? 0 : 1;
    }
"""


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    "source",
    (ORDERING_SOURCE, INITIALIZER_SOURCE, POINTER_SOURCE),
    ids=("dependency-order", "contextual-initializers", "pointer-cycles"),
)
def test_valid_aggregate_contracts_compile_strict_c11(
    source: str,
    c_compiler: str,
    tmp_path: Path,
):
    _strict_build_and_run(source, tmp_path, c_compiler)
