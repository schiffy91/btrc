"""Strict left-to-right expression sequencing contracts."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from pathlib import Path

from src.compiler.python.analyzer.analyzer import Analyzer
from src.compiler.python.ir.gen.generator import IRGenerator
from src.compiler.python.ir.nodes import IRCommaExpr, IRStmtExpr
from src.compiler.python.lexer import Lexer
from src.compiler.python.parser.parser import Parser
from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _compile_both(semantic_btrcc: Path, tmp_path: Path, source: str):
    selfhost, selfhost_c = _compile_source(semantic_btrcc, tmp_path, source)
    reference, reference_c = _compile_reference_source(tmp_path, source)
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr
    return selfhost_c, reference_c


def _walk(value):
    yield value
    if is_dataclass(value):
        for field in fields(value):
            yield from _walk(getattr(value, field.name))
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)


def test_eager_operands_are_structurally_sequenced() -> None:
    source = """
        int pair(int first, int second) { return first * 10 + second; }
        int main() {
            int value = 0;
            return pair(value++, value++) + (value++ + value++);
        }
    """
    program = Parser(Lexer(source, "sequencing.btrc").tokenize()).parse()
    analyzed = Analyzer().analyze(program)
    assert not analyzed.errors
    module = IRGenerator(analyzed).generate()
    nodes = list(_walk(module))
    assert sum(isinstance(node, IRStmtExpr) for node in nodes) >= 2
    assert sum(isinstance(node, IRCommaExpr) for node in nodes) >= 2

    selfhost = Path("src/compiler/btrc/ownership_boundary.btrc").read_text()
    assert "boundary.addOperand(generator, expression.left" in selfhost
    assert "return boundary.finish(generator, lowered" in selfhost
    assert "irCommaExpr(sequence)" in selfhost


def test_calls_binary_constructors_and_generic_bodies_run_left_to_right(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int trace = 0;
        int mark(int expected) {
            assert(trace == expected);
            trace++;
            return expected;
        }
        int pair(int first, int second) {
            assert(first == 0 && second == 1);
            return first * 10 + second;
        }

        class Ordered {
            public int first;
            public int second;
            public Ordered(int first, int second) {
                self.first = first;
                self.second = second;
            }
            static int pair(int first, int second) {
                return first * 10 + second;
            }
        }

        class GenericRunner<T> {
            public int run() {
                int local = 0;
                int called = pair(local++, local++);
                int added = local++ + local++;
                return called * 100 + added;
            }
        }

        int main() {
            trace = 0;
            assert(pair(trace++, trace++) == 1);
            assert(trace == 2);

            trace = 0;
            assert(trace++ + trace++ == 1);
            assert(trace == 2);

            trace = 0;
            Ordered ordered = new Ordered(mark(0), mark(1));
            assert(ordered.first == 0 && ordered.second == 1);

            trace = 0;
            assert(Ordered.pair(mark(0), mark(1)) == 1);

            GenericRunner<int> runner = new GenericRunner<int>();
            assert(runner.run() == 105);
            return 0;
        }
    """
    for index, generated in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        assert "__btrc_call_operand" in emitted or "__btrc_operand" in emitted
        _strict_build_and_run(generated, tmp_path / f"sequencing-{index}")


def test_nested_user_call_preserves_opaque_hosted_result(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <sys/stat.h>
        #include <unistd.h>

        class UserClass {
            class int value(int mode) { return mode; }
        }

        int main() {
            int descriptor = -1;
            int mode = 384;
            bool nested = fchmod(
                descriptor, UserClass.value(mode)) == 0;
            int localValue = UserClass.value(mode);
            bool local = fchmod(descriptor, localValue) == 0;
            return nested || local ? 1 : 0;
        }
    """
    for index, generated in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        assert "fchmod" in emitted
        assert "((void)0)) == 0" not in emitted
        _strict_build_and_run(
            generated,
            tmp_path / f"opaque-hosted-result-{index}",
        )


def test_managed_receivers_survive_later_operands_and_unwind(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int alive = 0;
        class Item {
            public int id;
            public Item(int id) { self.id = id; alive++; }
            public void __del__() { alive--; }
            public int combine(int other) {
                assert(self.id == 1 || self.id == 3 || self.id == 5);
                return self.id * 10 + other;
            }
            public int ordered(int first, int second) {
                return self.id * 100 + first * 10 + second;
            }
            public int fail() { throw "boom"; }
            public Item __add__(Item other) {
                return new Item(self.id * 10 + other.id);
            }
            public bool __lt__(Item other) {
                return self.id < other.id;
            }
        }

        int trace = 0;
        int mark(int expected) {
            assert(trace == expected);
            trace++;
            return expected;
        }

        void exerciseCallReceiver() {
            Item value = new Item(1);
            Item rebound = new Item(2);
            assert(value.combine((value = rebound).id) == 12);
            assert(alive == 1);
        }

        void exerciseOperatorReceiver() {
            Item value = new Item(3);
            Item rebound = new Item(4);
            Item result = value + (value = rebound);
            assert(result.id == 34);
            assert(alive == 2);
        }

        void exerciseComparisonReceiver() {
            Item value = new Item(5);
            Item rebound = new Item(6);
            assert(value < (value = rebound));
            assert(alive == 1);
        }

        void exerciseOrderedAndOptional() {
            Item value = new Item(6);
            trace = 0;
            assert(value.ordered(mark(0), mark(1)) == 601);

            Item? optional = value;
            trace = 0;
            assert(optional?.ordered(mark(0), mark(1)) == 601);
            assert(trace == 2);
            optional = null;
            trace = 0;
            assert(optional?.ordered(mark(0), mark(1)) == 0);
            assert(trace == 0);
        }

        void exerciseUnwind() {
            Item value = new Item(1);
            Item rebound = new Item(7);
            try {
                value.combine((value = rebound).fail());
                assert(false);
            } catch (string error) {
                assert(error == "boom");
            }
            assert(alive == 1);
        }

        int main() {
            exerciseCallReceiver();
            assert(alive == 0);
            exerciseOperatorReceiver();
            assert(alive == 0);
            exerciseComparisonReceiver();
            assert(alive == 0);
            exerciseOrderedAndOptional();
            assert(alive == 0);
            exerciseUnwind();
            assert(alive == 0);
            return 0;
        }
    """
    for index, generated in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        emitted = generated.read_text()
        assert "__btrc_kept_operand" in emitted
        _strict_build_and_run(generated, tmp_path / f"receiver-pin-{index}")
