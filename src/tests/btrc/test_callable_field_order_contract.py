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

IDENTIFIER_SOURCE = """
    #include <assert.h>

    typedef __fn_ptr<int, int> Unary;

    int original(int value) { return 100 + value; }
    int replacement(int value) { return 200 + value; }

    extern Unary callback;
    Unary callback = original;
    static const volatile Unary qualifiedCallback = original;
    const volatile Unary externalCallback = original;

    int replaceCallback() {
        callback = replacement;
        return 2;
    }

    int replaceSlot(Unary* slot) {
        *slot = replacement;
        return 2;
    }

    class GenericCaller<T> {
        public Unary field;

        public int mutateField() {
            self.field = replacement;
            return 2;
        }

        public int invokeField() {
            self.field = original;
            int result = self.field(self.mutateField());
            assert(self.field(3) == 203);
            return result;
        }

        public int invokeLocal() {
            Unary local = original;
            int result = local(replaceSlot(&local));
            assert(local(3) == 203);
            return result;
        }

        public int invokeGlobal() {
            callback = original;
            int result = callback(replaceCallback());
            assert(callback(3) == 203);
            return result;
        }

        public int invokeSource() {
            return original(2);
        }
    }

    int main() {
        extern const volatile Unary externalCallback;
        callback = original;
        int result = callback(replaceCallback());
        assert(result == 102);
        assert(callback(3) == 203);
        assert(qualifiedCallback(4) == 104);
        assert(externalCallback(5) == 105);

        GenericCaller<int> caller = new GenericCaller<int>();
        assert(caller.invokeField() == 102);
        assert(caller.invokeLocal() == 102);
        assert(caller.invokeGlobal() == 102);
        assert(caller.invokeSource() == 102);
        delete caller;
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


def _assert_generic_identifier_is_frozen(
    source: str,
    method: str,
    callee: str,
    side_effect: str,
) -> None:
    match = re.search(
        rf"{method}\([^)]*\)\s*\{{(?P<body>.*?)return result;",
        source,
        re.DOTALL,
    )
    assert match is not None, source
    body = match.group("body")
    frozen = re.search(
        rf"(?P<temp>__btrc_(?:callable|call_operand|operand)_\d+)"
        rf"\s*=\s*{callee}",
        body,
    )
    assert frozen is not None, body
    suffix = body[frozen.end() :]
    assert side_effect in suffix
    assert f"{frozen.group('temp')}(" in suffix


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


def test_callable_identifier_selection_precedes_argument_side_effects(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        IDENTIFIER_SOURCE,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        IDENTIFIER_SOURCE,
    )
    assert selfhost.returncode == 0, selfhost.stderr
    assert reference.returncode == 0, reference.stderr

    for generated in (selfhost_source, reference_source):
        main = generated.read_text().split("int main(void) {", 1)[1]
        frozen = re.search(
            r"(?P<callable>__btrc_(?:callable|call_operand|operand)_\d+)"
            r"\s*=\s*callback",
            main,
        )
        assert frozen is not None, main
        side_effect = main.find("replaceCallback()", frozen.end())
        invocation = main.find(f"{frozen.group('callable')}(", frozen.end())
        assert frozen.end() < side_effect < invocation, main

        source = generated.read_text()
        _assert_generic_identifier_is_frozen(
            source,
            "invokeLocal",
            "local",
            "replaceSlot(",
        )
        _assert_generic_identifier_is_frozen(
            source,
            "invokeGlobal",
            "callback",
            "replaceCallback(",
        )
        assert not re.search(
            r"const\s+\w+\s+__btrc_callable_\d+",
            source,
        )
        assert not re.search(
            r"__btrc_callable_\d+\s*=\s*original",
            source,
        )

    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-callable-identifier-order",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-callable-identifier-order",
    )
