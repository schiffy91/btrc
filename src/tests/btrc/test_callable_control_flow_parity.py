"""Self-host parity for managed-return callback flow edges."""

from pathlib import Path

import pytest

from src.tests.btrc.test_callable_return_abi_contract import _compile_both
from src.tests.btrc.test_semantic_validation import _strict_build_and_run

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _instrument_live_strings(generated: Path, definition: str = "") -> None:
    emitted = generated.read_text()
    marker = "int main(void) {"
    observer = (
        definition
        + "static size_t callable_test_live_strings(void) {\n"
        + "    return __btrc_string_entry_count;\n"
        + "}\n\n"
    )
    generated.write_text(emitted.replace(marker, observer + marker, 1))


def test_source_static_method_callback_keeps_owned_return_abi(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        class Factory {
            static string make() { return f"owned={1}"; }
        }
        int main() {
            {
                __fn_ptr<string> callback = Factory.make;
                string value = callback();
                assert(value != null);
            }
            assert((int)callable_test_live_strings() == 0);
            return 0;
        }
    """

    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stdout + result.stderr
        main = generated.read_text().split("int main(void) {", 1)[1]
        assert "__btrc_string_retain(value)" not in main
        _instrument_live_strings(generated)
        _strict_build_and_run(generated, tmp_path / f"static-owned-{index}")


def test_bodyless_static_method_callback_keeps_borrowed_return_abi(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>
        abstract class Foreign {
            static abstract string make();
        }
        int main() {
            {
                __fn_ptr<string> callback = Foreign.make;
                string value = callback();
                assert(value != null);
            }
            assert((int)callable_test_live_strings() == 0);
            return 0;
        }
    """
    definition = 'char* Foreign_make(void) {\n    return (char*)"borrowed";\n}\n\n'

    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stdout + result.stderr
        emitted = generated.read_text()
        main = emitted.split("int main(void) {", 1)[1]
        assert "__btrc_string_retain(value)" in main
        assert emitted.count("Foreign_make(void) {") == 0
        _instrument_live_strings(generated, definition)
        _strict_build_and_run(generated, tmp_path / f"static-borrowed-{index}")


def test_abstract_override_does_not_restore_inherited_implementation(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        class Base {
            static string make() { return f"base={1}"; }
        }
        abstract class Child extends Base {
            static abstract string make();
        }
        int main() {
            __fn_ptr<string> callback = Child.make;
            return callback == null ? 1 : 0;
        }
    """

    for result, generated in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode == 0, result.stdout + result.stderr
        emitted = generated.read_text()
        assert "char* Child_make(void);" in emitted
        assert "char* Child_make(void) {" not in emitted


@pytest.mark.parametrize(
    "body",
    (
        """
            try {
                callback = () => f"owned={1}";
                fail();
                callback = foreignString;
            } catch (string error) {
                string value = callback();
            }
        """,
        """
            switch (1) {
                case 1:
                    callback = () => f"owned={1}";
                case 2:
                    string value = callback();
                    break;
                default:
                    break;
            }
        """,
    ),
    ids=("throw-from-intermediate-state", "switch-fallthrough"),
)
def test_reached_callback_states_are_conservatively_joined(
    semantic_btrcc: Path,
    tmp_path: Path,
    body: str,
) -> None:
    source = f"""
        extern string foreignString();
        void fail() {{ throw "stop"; }}
        int main() {{
            __fn_ptr<string> callback = foreignString;
            {body}
            return 0;
        }}
    """

    for result, _ in _compile_both(semantic_btrcc, tmp_path, source):
        assert result.returncode != 0
        assert "ambiguous ownership ABI" in result.stdout + result.stderr
