"""Recursive aggregate contracts for managed-result callback storage."""

from pathlib import Path

import pytest

from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _tracked_strict_matrix,
)
from src.tests.btrc.test_callable_return_abi_contract import _compile_both

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


FOREIGN_CALLBACK_DEFINITION = """
static char *aggregate_foreign_value;
void aggregateForeignSet(char *value) { aggregate_foreign_value = value; }
char *aggregateForeignString(void) { return aggregate_foreign_value; }
"""


def test_nested_borrowed_callback_literals_are_proved_safe(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        import std.vector;
        import std.map;
        extern void aggregateForeignSet(string value);
        extern string aggregateForeignString();
        struct Slot { __fn_ptr<string> callback; };
        struct Branch { struct Branch* next; Slot leaf; };

        int main() {
            Branch branch = {NULL, {aggregateForeignString}};
            (int, __fn_ptr<string>) pair = (1, aggregateForeignString);
            Vector<__fn_ptr<string>> vector = [aggregateForeignString];
            Map<string, __fn_ptr<string>> map = {
                "one": aggregateForeignString
            };
            return branch.leaf.callback == aggregateForeignString
                && pair._1 == aggregateForeignString
                && vector.len == 1
                && map.len == 1 ? 0 : 1;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stdout + result.stderr
        generated.write_text(generated.read_text() + FOREIGN_CALLBACK_DEFINITION)
        _tracked_strict_matrix(
            (f"nested-borrowed-callback-literals-{index}", generated),
            tmp_path,
        )


def test_recursive_struct_borrowed_callback_balances_promoted_result(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        extern void aggregateForeignSet(string value);
        extern string aggregateForeignString();
        struct Slot { __fn_ptr<string> callback; };
        struct Branch { struct Branch* next; Slot leaf; };
        int main() {
            string owner = f"borrowed={17}";
            aggregateForeignSet(owner);
            Branch branch = {NULL, {aggregateForeignString}};
            string copy = branch.leaf.callback();
            return copy[0] == 'b' ? 0 : 1;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stdout + result.stderr
        generated.write_text(generated.read_text() + FOREIGN_CALLBACK_DEFINITION)
        _tracked_strict_matrix(
            (f"recursive-struct-borrowed-callback-{index}", generated),
            tmp_path,
        )


UNKNOWN_AGGREGATE_CASES = (
    pytest.param(
        """
        int main() {
            Branch original = {NULL, {aggregateForeignString}};
            Branch copy = original;
            return 0;
        }
        """,
        "aggregate storage",
        id="local-copy",
    ),
    pytest.param(
        """
        Branch exportBranch(Branch value) { return value; }
        int main() { return 0; }
        """,
        "a function return",
        id="return",
    ),
    pytest.param(
        """
        class Holder {
            public Branch value;
            public void store(Branch incoming) { self.value = incoming; }
        }
        int main() { return 0; }
        """,
        "field storage",
        id="field-assignment",
    ),
    pytest.param(
        """
        Branch globalValue;
        void storeGlobal(Branch incoming) { globalValue = incoming; }
        int main() { return 0; }
        """,
        "global storage",
        id="global-assignment",
    ),
    pytest.param(
        """
        void consume(Branch value) {}
        int main() {
            Branch value = {NULL, {aggregateForeignString}};
            consume(value);
            return 0;
        }
        """,
        "an erased or opaque value cannot preserve its return ownership ABI",
        id="call-parameter",
    ),
)


@pytest.mark.parametrize(("body", "diagnostic"), UNKNOWN_AGGREGATE_CASES)
def test_unknown_callback_aggregate_fails_closed_at_escape_boundaries(
    semantic_btrcc: Path,
    tmp_path: Path,
    body: str,
    diagnostic: str,
) -> None:
    source = f"""
        extern string aggregateForeignString();
        struct Slot {{ __fn_ptr<string> callback; }};
        struct Branch {{ struct Branch* next; Slot leaf; }};
        {body}
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert diagnostic in result.stdout + result.stderr


@pytest.mark.parametrize(
    ("parameter", "diagnostic"),
    (
        (
            "__fn_ptr<string> callback = sourceString",
            "bare __fn_ptr parameters accept only borrowed C callbacks",
        ),
        (
            "Branch value = {NULL, {sourceString}}",
            "an erased or opaque value cannot preserve its return ownership ABI",
        ),
    ),
    ids=("direct", "aggregate"),
)
def test_omitted_owned_callback_defaults_are_validated(
    semantic_btrcc: Path,
    tmp_path: Path,
    parameter: str,
    diagnostic: str,
) -> None:
    source = f"""
        struct Slot {{ __fn_ptr<string> callback; }};
        struct Branch {{ struct Branch* next; Slot leaf; }};
        string sourceString() {{ return f"owned={{1}}"; }}
        void consume({parameter}) {{}}
        int main() {{ consume(); return 0; }}
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert diagnostic in result.stdout + result.stderr


def test_lexical_function_pointer_signature_enforces_callback_boundary(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        extern void foreignConsume(__fn_ptr<string> callback);
        string sourceString() { return f"owned={1}"; }
        int main() {
            __fn_ptr<void, __fn_ptr<string>> consume = foreignConsume;
            consume(sourceString);
            return 0;
        }
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "bare __fn_ptr parameters accept only borrowed C callbacks" in (result.stdout + result.stderr)
