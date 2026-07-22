"""Callable identifiers are frozen before boundary-managed arguments."""

import re
from pathlib import Path

from src.tests.btrc.string_coercion_harness import assert_tracked_strict_pair
from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)
FIXTURES = Path(__file__).with_name("fixtures")


SOURCE = """
    #include <assert.h>

    typedef __fn_ptr<int, string, int> Callback;

    int trace = 0;

    int original(string value, int marker) {
        return 100 + value.len() * 10 + marker;
    }

    int replacement(string value, int marker) {
        return 200 + value.len() * 10 + marker;
    }

    Callback callback = original;

    string replaceCallback() {
        trace = trace * 10 + 1;
        callback = replacement;
        return "xx";
    }

    int observeArgument() {
        trace = trace * 10 + 2;
        return 3;
    }

    int main() {
        callback = original;
        int result = callback(replaceCallback(), observeArgument());
        assert(result == 123);
        assert(trace == 12);
        assert(callback("xx", 3) == 223);
        return 0;
    }
"""


def _assert_boundary_freezes_identifier(source: str) -> None:
    main = source.split("int main(void) {", 1)[1]
    frozen = re.search(
        r"(?P<callee>__btrc_(?:call_operand|operand)_\d+)\s*=\s*callback",
        main,
    )
    assert frozen is not None, main
    replacement = main.find("replaceCallback()", frozen.end())
    invocation = main.find(f"{frozen.group('callee')}(", frozen.end())
    assert frozen.end() < replacement < invocation, main


def test_callable_identifier_precedes_boundary_managed_arguments(
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

    for generated in (selfhost_source, reference_source):
        _assert_boundary_freezes_identifier(generated.read_text())

    _strict_build_and_run(
        selfhost_source,
        tmp_path / "selfhost-callable-identifier-boundary",
    )
    _strict_build_and_run(
        reference_source,
        tmp_path / "reference-callable-identifier-boundary",
    )


def test_env_backed_callable_is_not_materialized_as_plain_identifier(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    assert_tracked_strict_pair(
        semantic_btrcc,
        tmp_path,
        FIXTURES / "string_coercion_calls_runtime.btrc",
        expected_stdout="1015\n2015\n",
    )
