"""Call arguments produce one structured IR value per source expression."""

import re
from pathlib import Path

from src.tests.btrc.production_readiness_harness import (
    compile_no_dce_pair,
    run_strict_pair,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

# One lifted body per lambda expression. Count definitions rather than every
# mention: a frontend may additionally forward-declare its static helpers, and
# that choice says nothing about how many times the argument was lowered.
_LAMBDA_DEFINITION = re.compile(r"^static int __btrc_lambda_\d+\([^)]*\) \{$", re.MULTILINE)


SINGLE_LOWERING_SOURCE = """
    int sequence = 0;

    int nextValue(int expected, int value) {
        if (sequence != expected) { return -100; }
        sequence += 1;
        return value;
    }

    int combine(int left, int right) {
        return left * 10 + right;
    }

    class CallbackBox {
        public __fn_ptr<int, int> callback;

        public CallbackBox(__fn_ptr<int, int> callback) {
            self.callback = callback;
        }

        public int invoke(int value) {
            return self.callback(value);
        }
    }

    int main() {
        print((int value) => value + 1);
        print(combine(nextValue(0, 4), nextValue(1, 2)));
        CallbackBox box = CallbackBox((int value) => value + 2);
        int result = box.invoke(40);
        delete box;
        return result == 42 && sequence == 2 ? 0 : 1;
    }
"""


def test_print_and_constructor_arguments_are_lowered_once_without_dce(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    compiled = compile_no_dce_pair(
        semantic_btrcc,
        tmp_path,
        SINGLE_LOWERING_SOURCE,
        "single-lowering",
    )
    for _frontend, generated in compiled:
        assert len(_LAMBDA_DEFINITION.findall(generated.read_text())) == 2
    run_strict_pair(compiled, tmp_path)


def test_function_pointer_reassignment_rhs_is_lowered_once_without_dce(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[3]
    source = (repository / "src/tests/functions/test_fnptr_variable_reassign.btrc").read_text()
    compiled = compile_no_dce_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "fnptr-reassignment-single-lowering",
    )
    for _frontend, generated in compiled:
        assert len(_LAMBDA_DEFINITION.findall(generated.read_text())) == 1
    run_strict_pair(compiled, tmp_path)
