"""Immediate lambda calls use one typed capture/argument transaction."""

from __future__ import annotations

import re
from pathlib import Path

from src.tests.btrc.runtime_ownership_harness import (
    require_sanitizers,
    sanitized_build_and_run,
)
from src.tests.btrc.test_mutex_value_contract import _compile_pair, _strict_matrix

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc/ir/lowering"


def test_immediate_lambda_transaction_has_typed_domain_owners() -> None:
    calls = (SELFHOST / "calls.btrc").read_text()
    callables = (SELFHOST / "callables.btrc").read_text()
    expressions = (SELFHOST / "expressions.btrc").read_text()
    ownership = (SELFHOST / "ownership/calls.btrc").read_text()

    assert "CALL_TARGET_IMMEDIATE_LAMBDA" in calls
    callable_target = calls.split("private CallTarget callableTarget(", 1)[1].split(
        "private CallSignature builtinSignature(", 1
    )[0]
    assert "target.kind = callee.kind == NK_LAMBDA_EXPR" in callable_target
    assert "if (callee.kind != NK_LAMBDA_EXPR)" in callable_target

    assert "class CallableInvocationEnvironment {" in callables
    assert "prepareInvocationEnvironment(" in callables
    assert "return IRNode.call(lambda.functionName, arguments);" in callables
    assert "return IRNode.indirectCall(lambda.value, arguments);" not in callables

    assert "public IRNode stageValue(" in ownership
    assert "self.rememberOverride(expression, value);" in ownership
    immediate = expressions.split("private IRNode lowerImmediateLambdaCallWithOwnership(", 1)[1].split(
        "public IRNode lowerCallWithOwnership(", 1
    )[0]
    assert immediate.index("boundary.stageValue(") < immediate.index("prepareInvocationEnvironment(")
    assert immediate.index("prepareInvocationEnvironment(") < immediate.index("self.addCallOperand(")
    assert immediate.index("self.addCallOperand(") < immediate.index("materializeInvocation(")
    dispatch = expressions.split("public IRNode lowerCallWithOwnership(", 1)[1]
    assert dispatch.index("self.lowerImmediateLambdaCallWithOwnership(") < dispatch.index("self.callOwnership.plan(")


def test_captured_immediate_lambda_lifts_once_and_is_strict_c11(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        int run(int outer) {
            return ((int value) => value + outer)(3);
        }

        int main() {
            assert(run(4) == 7);
            return 0;
        }
    """
    compiled = _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "immediate-lambda-single-lift",
    )
    selfhost = compiled[0][1].read_text()
    assert len(set(re.findall(r"__btrc_lambda_\d+", selfhost))) == 1
    assert not re.search(r"__btrc_fn_[A-Za-z0-9_]+\s+__btrc_operand_\d+", selfhost)
    for artifact in compiled:
        _strict_matrix(artifact, tmp_path)


RUNTIME_SOURCE = r"""
    #include <assert.h>

    int alive = 0;

    class Item {
        public int value;
        public Item(int value) { self.value = value; alive++; }
        public void __del__() { alive--; }
    }

    int throwingArgument() {
        throw "argument failed";
    }

    void exerciseCaptureOrder() {
        int capturedScalar = 3;
        int scalarResult =
            ((int first, int second) => capturedScalar)(
                (int)(capturedScalar = 9),
                capturedScalar
            );
        assert(scalarResult == 3);

        string capturedString = f"old={1}";
        string stringResult =
            ((string ignored) => capturedString)(
                (string)(capturedString = f"new={2}")
            );
        assert(stringResult == "old=1");

        Item capturedItem = new Item(4);
        int itemResult =
            ((Item ignored) => capturedItem.value)(
                (Item)(capturedItem = new Item(9))
            );
        assert(itemResult == 4);
        assert(capturedItem.value == 9);
        capturedItem = null;
        assert(alive == 0);
    }

    void exerciseManagedReturns() {
        Item source = new Item(11);
        Item borrowed = (() => source)();
        source = null;
        assert(alive == 1 && borrowed.value == 11);
        borrowed = null;
        assert(alive == 0);

        Item owned = (() => new Item(12))();
        assert(alive == 1 && owned.value == 12);
        owned = null;
        assert(alive == 0);
    }

    void exerciseUnwind() {
        Item captured = new Item(20);
        try {
            ((int argument) => captured.value)(
                throwingArgument()
            );
        } catch (string error) {
            assert(error == "argument failed");
            assert(captured.value == 20);
        }
        captured = null;
        assert(alive == 0);
    }

    int main() {
        exerciseCaptureOrder();
        exerciseManagedReturns();
        exerciseUnwind();
        assert(alive == 0);
        return 0;
    }
"""


def _compile_runtime(semantic_btrcc: Path, tmp_path: Path):
    return _compile_pair(
        semantic_btrcc,
        tmp_path,
        RUNTIME_SOURCE,
        "immediate-lambda-capture-ownership",
    )


def test_immediate_lambda_capture_order_and_result_abi_are_strict(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    for artifact in _compile_runtime(semantic_btrcc, tmp_path):
        _strict_matrix(artifact, tmp_path)


def test_immediate_lambda_capture_transaction_is_sanitizer_clean(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    toolchain = require_sanitizers(tmp_path)
    for frontend, generated in _compile_runtime(semantic_btrcc, tmp_path):
        sanitized_build_and_run(
            generated,
            tmp_path / f"{frontend}-immediate-lambda-san",
            toolchain,
        )
