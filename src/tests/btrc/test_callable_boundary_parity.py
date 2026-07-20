"""Dual-frontend contracts for managed-result callback ABI boundaries."""

from pathlib import Path

import pytest

from src.tests.btrc.test_arc_hidden_lifecycle_boundaries import (
    _tracked_strict_matrix,
)
from src.tests.btrc.test_callable_return_abi_contract import _compile_both

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


DO_WHILE_FOREIGN_DEFINITION = """
char *genericCallableForeignString(void) { return (char *)"unused"; }
"""


def test_do_while_callable_flow_uses_only_reachable_body_exits(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        extern string genericCallableForeignString();
        string genericCallableSourceString() { return f"source={17}"; }

        string ordinaryDoWhile(int mode) {
            __fn_ptr<string> callback = genericCallableForeignString;
            do {
                callback = genericCallableSourceString;
                if (mode == 1) { break; }
                if (mode == 2) { continue; }
            } while (false);
            return callback();
        }

        class GenericDoWhile<T> {
            public string invoke(int mode) {
                __fn_ptr<string> callback = genericCallableForeignString;
                do {
                    callback = genericCallableSourceString;
                    if (mode == 1) { break; }
                    if (mode == 2) { continue; }
                } while (false);
                return callback();
            }
        }

        int main() {
            GenericDoWhile<int> generic = new GenericDoWhile<int>();
            int mode = 0;
            while (mode < 3) {
                string ordinary = ordinaryDoWhile(mode);
                string specialized = generic.invoke(mode);
                if (ordinary[0] != 's' || specialized[0] != 's') {
                    return 1;
                }
                mode++;
            }
            return 0;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stdout + result.stderr
        generated.write_text(generated.read_text() + DO_WHILE_FOREIGN_DEFINITION)
        _tracked_strict_matrix(
            (f"do-while-callable-flow-{index}", generated),
            tmp_path,
        )


GENERIC_BOUNDARY_CASES = (
    pytest.param(
        """
        string consume(__fn_ptr<string> callback) { return callback(); }
        class GenericCaller<T> {
            public string invoke() {
                __fn_ptr<string> callback = sourceString;
                return consume(callback);
            }
        }
        int main() {
            GenericCaller<int> caller = new GenericCaller<int>();
            caller.invoke();
            return 0;
        }
        """,
        "bare __fn_ptr parameters accept only borrowed C callbacks",
        id="call-inside-generic",
    ),
    pytest.param(
        """
        class Box<T> {
            public __fn_ptr<string> callback;
            public void store() { self.callback = sourceString; }
        }
        int main() { Box<int> box = new Box<int>(); box.store(); return 0; }
        """,
        "field storage",
        id="field-assignment",
    ),
    pytest.param(
        """
        __fn_ptr<string> globalCallback = foreignString;
        class Box<T> { public void store() { globalCallback = sourceString; } }
        int main() { Box<int> box = new Box<int>(); box.store(); return 0; }
        """,
        "global storage",
        id="global-assignment",
    ),
    pytest.param(
        """
        class Box<T> {
            public void store() {
                __fn_ptr<string> values[1] = [foreignString];
                values[0] = sourceString;
            }
        }
        int main() { Box<int> box = new Box<int>(); box.store(); return 0; }
        """,
        "indexed storage",
        id="indexed-assignment",
    ),
    pytest.param(
        """
        class Box<T> {
            public __fn_ptr<string> exportCallback() { return sourceString; }
        }
        int main() { Box<int> box = new Box<int>(); box.exportCallback(); return 0; }
        """,
        "a function return",
        id="return",
    ),
    pytest.param(
        """
        class Box<T> { public __fn_ptr<string> callback = sourceString; }
        int main() {
            Box<int> box = new Box<int>();
            return box == null ? 1 : 0;
        }
        """,
        "field storage",
        id="field-initializer",
    ),
)


@pytest.mark.parametrize(("body", "diagnostic"), GENERIC_BOUNDARY_CASES)
def test_generic_persistent_boundaries_reject_owned_callback_abi(
    semantic_btrcc: Path,
    tmp_path: Path,
    body: str,
    diagnostic: str,
) -> None:
    source = f"""
        extern string foreignString();
        string sourceString() {{ return f"owned={{1}}"; }}
        {body}
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert diagnostic in result.stdout + result.stderr


@pytest.mark.parametrize(
    "declaration",
    (
        "Slot slot = {sourceString};",
        "(int, __fn_ptr<string>) slot = (1, sourceString);",
        "Vector<__fn_ptr<string>> slot = [sourceString];",
        "__fn_ptr<string> slot[1] = [sourceString];",
        'Map<string, __fn_ptr<string>> slot = {"one": sourceString};',
        "Vector<Slot> slot = [{sourceString}];",
    ),
    ids=("struct", "tuple", "sequence", "array", "map", "nested"),
)
def test_aggregate_storage_recursively_rejects_owned_callback_abi(
    semantic_btrcc: Path,
    tmp_path: Path,
    declaration: str,
) -> None:
    source = f"""
        struct Slot {{ __fn_ptr<string> callback; }};
        string sourceString() {{ return f"owned={{1}}"; }}
        int main() {{ {declaration} return 0; }}
    """
    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "bare __fn_ptr storage erases its return ABI" in (result.stdout + result.stderr)


AGGREGATE_FOREIGN_DEFINITION = """
static char *aggregate_foreign_value;
void aggregateForeignSet(char *value) { aggregate_foreign_value = value; }
char *aggregateForeignString(void) { return aggregate_foreign_value; }
"""


def test_borrowed_callback_aggregate_balances_promoted_result(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        extern void aggregateForeignSet(string value);
        extern string aggregateForeignString();
        struct Slot { __fn_ptr<string> callback; };
        int main() {
            string owner = f"borrowed={1}";
            aggregateForeignSet(owner);
            Slot slot = {aggregateForeignString};
            string copy = slot.callback();
            return copy[0] == 'b' ? 0 : 1;
        }
    """
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stdout + result.stderr
        generated.write_text(generated.read_text() + AGGREGATE_FOREIGN_DEFINITION)
        _tracked_strict_matrix(
            (f"borrowed-callback-aggregate-{index}", generated),
            tmp_path,
        )
