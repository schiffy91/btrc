"""Dual-frontend source macro semantic boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tests.btrc.production_readiness_harness import compile_diagnostic_pair
from src.tests.btrc.test_mutex_value_contract import _compile_pair, _strict_matrix

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


@pytest.mark.parametrize(
    ("source", "diagnostic"),
    (
        (
            "#define CALL(fn,value) fn(value)\n"
            "class Item {} void consume(Item value) {} "
            "int main(){ Item owner=new Item(); CALL(consume,owner); return 0; }",
            "cannot accept callable argument 1",
        ),
        (
            "#define CALL(fn,value) (fn)(value)\n"
            "void consumeInt(int value) {} "
            "int main(){ __fn_ptr<void, int> fn=consumeInt; "
            "CALL((__fn_ptr<void, int>)fn,1); return 0; }",
            "cannot accept callable argument 1",
        ),
        (
            "#define CALL(fn,value) ((void (*)(int))(fn))(value)\n"
            "void consumeInt(int value) {} "
            "int main(){ __fn_ptr<void, int> fn=consumeInt; "
            "CALL((void*)fn,1); return 0; }",
            "cannot accept callable argument 1",
        ),
        (
            "#define PASS(value) inspect(value)\nextern void inspect(void* value); "
            "class Item {} int main(){ Item owner=new Item(); "
            "PASS((void*)owner); return 0; }",
            "managed or opaque-borrow argument 1",
        ),
        (
            "#define INNER() owner\n#define OUTER() INNER()\n"
            "class Item {} int main(){ Item owner=new Item(); OUTER(); return 0; }",
            "cannot capture managed or callable value 'owner'",
        ),
        (
            "#define TAKE(value) consume(value)\nclass Item {} void consume(Item value) {} int main(){ return 0; }",
            "Language callable 'consume' requires semantic call analysis",
        ),
        (
            "#define APPLY(value) value.take()\nclass Item { public void take() {} } int main(){ return 0; }",
            "Language method 'take'",
        ),
        (
            "#define CREATE() Item()\nclass Item {} int main(){ return 0; }",
            "Language type 'Item'",
        ),
        (
            "#define PASS(value) (value)\n"
            "class Box { public void forward<T>(T value) { PASS(value); } } "
            "int main(){ return 0; }",
            "managed or opaque-borrow argument 1",
        ),
    ),
)
def test_macro_semantic_bypasses_fail_with_frontend_parity(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert diagnostic in result.stderr


def test_scalar_and_exact_read_only_hosted_macros_run_strictly(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #define SQUARE(value) ((value) * (value))
        #define LENGTH(value) strlen(value)
        #define FREE_IDENTITY(free) free
        int main() {
            string text = "abc";
            return SQUARE(3) == 9 && LENGTH(text) == 3 ? 0 : 1;
        }
    """
    for artifact in _compile_pair(
        semantic_btrcc,
        tmp_path,
        source,
        "source-macro-read-only",
    ):
        _strict_matrix(artifact, tmp_path)


@pytest.mark.parametrize(
    ("definitions", "should_fail"),
    (
        (
            "#define WRAP(value) (value)\n#define WRAP(value) strlen(value)",
            False,
        ),
        (
            "#define WRAP(value) strlen(value)\n#define WRAP(value) (value)",
            True,
        ),
    ),
)
def test_latest_macro_redefinition_is_deterministic(
    semantic_btrcc: Path,
    tmp_path: Path,
    definitions: str,
    should_fail: bool,
) -> None:
    source = definitions + '\nint main(){ string text="abc"; return WRAP(text) == 3 ? 0 : 1; }'
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert (result.returncode != 0) is should_fail
        if should_fail:
            assert "managed or opaque-borrow argument 1" in result.stderr


def test_undef_remains_a_deterministic_fail_closed_codegen_boundary(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #define WRAP(value) strlen(value)
        #undef WRAP
        int main() { string text = "abc"; return WRAP(text); }
    """
    for result in compile_diagnostic_pair(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "unsupported preprocessor directive '#undef'" in result.stderr
