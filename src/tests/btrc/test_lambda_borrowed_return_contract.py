"""Owned-return contracts for lambdas that return borrowed managed values."""

from pathlib import Path

import pytest

from src.tests.btrc.allocation_tracking_harness import tracked_strict_matrix
from src.tests.btrc.dual_frontend_harness import compile_snippet_pair, strict_c11_matrix
from src.tests.c_toolchains import HOST_C_COMPILERS

pytestmark = pytest.mark.skipif(
    not HOST_C_COMPILERS,
    reason="requires a pthread C11 compiler",
)


def test_lambda_borrowed_class_returns_transfer_one_reference(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int alive = 0;

        class Item {
            public Item() { alive++; }
            public void __del__() { alive--; }
        }

        void exercise() {
            Item source = new Item();
            var capturedExpression = () => source;
            Item first = capturedExpression();
            var capturedBlock = () => { return source; };
            Item second = capturedBlock();
            var parameterExpression = (Item value) => value;
            Item third = parameterExpression(source);
            var parameterBlock = (Item value) => { return value; };
            Item fourth = parameterBlock(source);
            assert(alive == 1);
        }

        int main() {
            exercise();
            assert(alive == 0);
            return 0;
        }
    """
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "lambda-borrowed-class-return",
    )
    for artifact in compiled:
        strict_c11_matrix(artifact, tmp_path)


def test_lambda_borrowed_mutex_returns_transfer_one_reference(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        extern void arc_test_allocation_checkpoint();
        extern long arc_test_allocation_delta();

        void exerciseMutexReturns(int expected) {
            Mutex<int> source = Mutex(expected);
            var capturedExpression = () => source;
            Mutex<int> first = capturedExpression();
            var capturedBlock = () => { return source; };
            Mutex<int> second = capturedBlock();
            var parameterExpression = (Mutex<int> value) => value;
            Mutex<int> third = parameterExpression(source);
            var parameterBlock = (Mutex<int> value) => { return value; };
            Mutex<int> fourth = parameterBlock(source);

            source.destroy();
            assert(first.get() == expected);
            first.destroy();
            assert(second.get() == expected);
            second.destroy();
            assert(third.get() == expected);
            third.destroy();
            assert(fourth.get() == expected);
            fourth.destroy();
        }

        int main() {
            exerciseMutexReturns(9);
            arc_test_allocation_checkpoint();
            exerciseMutexReturns(10);
            assert(arc_test_allocation_delta() == 0);
            return 0;
        }
    """
    compiled = compile_snippet_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "lambda-borrowed-mutex-return",
    )
    for artifact in compiled:
        tracked_strict_matrix(artifact, tmp_path)
