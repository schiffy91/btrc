"""Managed-return ABI provenance for plain ``__fn_ptr`` values."""

from pathlib import Path

import pytest

from src.tests.btrc.test_ownership_semantics_contract import (
    _compile_reference_source,
)
from src.tests.btrc.test_semantic_validation import (
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


_PRELUDE = """
    extern string foreignString();
"""


def _compile_both(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
):
    selfhost, selfhost_source = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
    )
    reference, reference_source = _compile_reference_source(
        tmp_path,
        source,
    )
    return (selfhost, selfhost_source), (reference, reference_source)


@pytest.mark.parametrize(
    "control_flow",
    (
        'if (true) { callback = () => f"managed={1}"; }',
        'while (choose) { callback = () => f"managed={1}"; break; }',
        'do { if (choose) { callback = () => f"managed={1}"; break; } } while (false);',
        'switch (1) { case 1: callback = () => f"managed={1}"; break; default: break; }',
        'try { callback = () => f"managed={1}"; } catch (string error) {}',
    ),
    ids=("if", "while", "do-while-conditional", "switch", "try-catch"),
)
def test_mixed_callback_abis_are_rejected_after_control_flow(
    semantic_btrcc: Path,
    tmp_path: Path,
    control_flow: str,
) -> None:
    source = (
        _PRELUDE
        + f"""
        int main() {{
            __fn_ptr<string> callback = foreignString;
            bool choose = false;
            {control_flow}
            string value = callback();
            return 0;
        }}
        """
    )
    for result, _ in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode != 0
        assert "ambiguous ownership ABI" in result.stdout + result.stderr


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_literal_false_while_does_not_join_unreachable_callback_mutation(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    body = """
        __fn_ptr<string> callback = foreignString;
        while (false) { callback = sourceString; }
        string value = callback();
        return len(value);
    """
    if generic:
        source = (
            _PRELUDE
            + f"""
            string sourceString() {{ return f"managed={{1}}"; }}
            class CallbackFlow<T> {{
                public CallbackFlow() {{}}
                public int invoke() {{ {body} }}
            }}
            int main() {{
                CallbackFlow<int> flow = new CallbackFlow<int>();
                return flow.invoke();
            }}
            """
        )
    else:
        source = (
            _PRELUDE
            + f"""
            string sourceString() {{ return f"managed={{1}}"; }}
            int invoke() {{ {body} }}
            int main() {{ return invoke(); }}
            """
        )

    for result, generated in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode == 0, result.stdout + result.stderr
        assert "__btrc_string_retain(value)" in generated.read_text()


@pytest.mark.parametrize("generic", (False, True), ids=("ordinary", "generic"))
def test_literal_true_while_keeps_repeated_callback_invariant(
    semantic_btrcc: Path,
    tmp_path: Path,
    generic: bool,
) -> None:
    body = """
        __fn_ptr<string> callback = foreignString;
        while (true) { callback = sourceString; }
        return 0;
    """
    if generic:
        source = (
            _PRELUDE
            + f"""
            string sourceString() {{ return f"managed={{1}}"; }}
            class CallbackFlow<T> {{
                public CallbackFlow() {{}}
                public int invoke() {{ {body} }}
            }}
            int main() {{
                CallbackFlow<int> flow = new CallbackFlow<int>();
                return flow.invoke();
            }}
            """
        )
    else:
        source = (
            _PRELUDE
            + f"""
            string sourceString() {{ return f"managed={{1}}"; }}
            int invoke() {{ {body} }}
            int main() {{ return invoke(); }}
            """
        )

    for result, _ in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode != 0
        assert "invariant across a repeated loop back-edge" in result.stdout + result.stderr


def test_source_owned_managed_callback_cannot_cross_borrowed_parameter(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        string apply(__fn_ptr<string> callback) { return callback(); }

        int main() {
            __fn_ptr<string> callback = () => f"managed={1}";
            string value = apply(callback);
            return 0;
        }
    """
    for result, _ in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode != 0
        assert "bare __fn_ptr parameters accept only borrowed C callbacks" in result.stdout + result.stderr


def test_throw_edge_preserves_callback_mutation_provenance(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        _PRELUDE
        + """
        int main() {
            __fn_ptr<string> callback = foreignString;
            try {
                callback = () => f"managed={1}";
                throw "stop";
            } catch (string error) {
                string value = callback();
            }
            return 0;
        }
        """
    )
    for result, _ in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode != 0
        assert "ambiguous ownership ABI" in result.stdout + result.stderr


@pytest.mark.parametrize(
    "boundary_source",
    (
        """
        __fn_ptr<string> exported() {
            __fn_ptr<string> callback = () => f"managed={1}";
            return callback;
        }
        int main() { return 0; }
        """,
        _PRELUDE
        + """
        __fn_ptr<string> callback = foreignString;
        int main() {
            callback = () => f"managed={1}";
            return 0;
        }
        """,
        """
        class Holder {
            public __fn_ptr<string> callback;
            public Holder() {}
        }
        int main() {
            Holder holder = new Holder();
            holder.callback = () => f"managed={1}";
            return 0;
        }
        """,
    ),
    ids=("return", "global", "field"),
)
def test_persistent_storage_rejects_owned_return_callback_abi(
    semantic_btrcc: Path,
    tmp_path: Path,
    boundary_source: str,
) -> None:
    for result, _ in _compile_both(
        semantic_btrcc,
        tmp_path,
        boundary_source,
    ):
        assert result.returncode != 0
        assert "bare __fn_ptr storage erases its return ABI" in result.stdout + result.stderr


def test_borrowed_foreign_callbacks_may_cross_persistent_storage(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = (
        _PRELUDE
        + """
        __fn_ptr<string> globalCallback = foreignString;
        class Holder {
            public __fn_ptr<string> callback;
            public Holder() {}
        }
        __fn_ptr<string> exported() { return foreignString; }
        int main() {
            Holder holder = new Holder();
            holder.callback = foreignString;
            globalCallback = foreignString;
            return 0;
        }
        """
    )
    for result, _ in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode == 0, result.stdout + result.stderr


def test_borrowed_managed_callback_shadow_stays_borrowed_in_branch_scope(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        extern string foreignString();
        string callback() { return f"owned={1}"; }
        struct Slot { string value; };

        int main() {
            bool valid = false;
            __fn_ptr<string> callback = foreignString;
            if (true) {
                Slot slot = {callback()};
                valid = slot.value[0] == 'b';
            }
            return valid ? 0 : 1;
        }
    """
    foreign_definition = """
        char *foreignString(void) {
            static char value[] = "borrowed";
            return value;
        }
    """
    for result, generated in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode == 0, result.stdout + result.stderr
        generated.write_text(generated.read_text() + foreign_definition)
        _strict_build_and_run(
            generated,
            tmp_path / f"borrowed-shadow-{generated.stem}",
        )


def test_same_owned_abi_joins_remain_valid(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        #include <assert.h>

        void exercise(bool choose) {
            __fn_ptr<string> callback = () => f"first={1}";
            if (choose) { callback = () => f"second={2}"; }
            string value = callback();
        }

        int main() {
            exercise(false);
            exercise(true);
            assert((int)callable_test_live_strings() == 0);
            return 0;
        }
    """
    for result, generated in _compile_both(
        semantic_btrcc,
        tmp_path,
        source,
    ):
        assert result.returncode == 0, result.stderr
        emitted = generated.read_text()
        marker = "int main(void) {"
        observer = "static size_t callable_test_live_strings(void) {\n    return __btrc_string_entry_count;\n}\n\n"
        generated.write_text(emitted.replace(marker, observer + marker, 1))
        _strict_build_and_run(
            generated,
            tmp_path / f"same-abi-{generated.stem}",
        )
