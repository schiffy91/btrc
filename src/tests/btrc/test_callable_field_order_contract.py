"""Callable fields are selected before their call arguments run."""

import re
from pathlib import Path

from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


SOURCE = """
    #include <assert.h>

    typedef __fn_ptr<int, int, int> Binary;

    int trace = 0;
    int receiverReads = 0;

    int original(int left, int right) {
        return 100 + left * 10 + right;
    }

    int replacement(int left, int right) {
        return 200 + left * 10 + right;
    }

    class CallbackBox {
        public Binary callback;
        public CallbackBox(Binary callback) {
            self.callback = callback;
        }
    }

    keep CallbackBox selectBox(CallbackBox box) {
        receiverReads++;
        return box;
    }

    int mutateCallback(CallbackBox box) {
        trace = trace * 10 + 1;
        box.callback = replacement;
        return 2;
    }

    int observeArgument() {
        trace = trace * 10 + 2;
        return 3;
    }

    int main() {
        CallbackBox box = new CallbackBox(original);

        int direct = selectBox(box).callback(
            mutateCallback(box), observeArgument());
        assert(direct == 123);
        assert(trace == 12);
        assert(receiverReads == 1);
        assert(box.callback(2, 3) == 223);

        box.callback = original;
        trace = 0;
        int guarded = selectBox(box)?.callback(
            mutateCallback(box), observeArgument());
        assert(guarded == 123);
        assert(trace == 12);
        assert(receiverReads == 2);
        assert(box.callback(2, 3) == 223);

        box.callback = original;
        trace = 0;
        CallbackBox? missing = null;
        int absent = missing?.callback(
            mutateCallback(box), observeArgument());
        assert(absent == 0);
        assert(trace == 0);
        assert(box.callback(2, 3) == 123);
        return 0;
    }
"""


def _assert_callable_is_frozen(source: str) -> None:
    main = source.split("int main(void) {", 1)[1]
    frozen_call = re.compile(
        r"\((?P<callable>__btrc_(?:call_operand|operand)_\d+)\s*=\s*"
        r"[^;\n]*?->callback\).*?mutateCallback\(.*?observeArgument\(.*?"
        r"(?P=callable)\(",
        re.DOTALL,
    )
    matches = list(frozen_call.finditer(main))
    assert len(matches) >= 3, main
    assert not re.search(
        r"->callback\s*\([^;]*mutateCallback\(",
        main,
        re.DOTALL,
    )


def test_callable_field_selection_precedes_argument_side_effects(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        SOURCE,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        SOURCE,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    _assert_callable_is_frozen(selfhost_source.read_text())
    _assert_callable_is_frozen(reference_source.read_text())
    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-callable-field-order",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-callable-field-order",
    )
