"""Adversarial pointer-effect parity for the self-hosted compiler."""

from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import (
    _compile_reference_source,
    _compile_source,
    _strict_build_and_run,
)

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)


def _compile_both(compiler: Path, tmp_path: Path, source: str):
    return (
        _compile_source(compiler, tmp_path, source),
        _compile_reference_source(tmp_path, source),
    )


def _assert_both_fail(
    compiler: Path,
    tmp_path: Path,
    source: str,
    diagnostic: str,
) -> None:
    for result, _ in _compile_both(compiler, tmp_path, source):
        assert result.returncode == 1
        assert diagnostic in result.stderr


@pytest.mark.parametrize(
    "setup, mutation",
    (
        ("", "mutate(&x + 0);"),
        ("int* p = &x; int** pp = &p;", "**pp = 7;"),
        ("int* p = identity(&x);", "*p = 7;"),
    ),
)
def test_unrepresentable_pointer_writes_fail_closed(
    semantic_btrcc: Path,
    tmp_path: Path,
    setup: str,
    mutation: str,
) -> None:
    identity = "int* identity(int* p) { return p; }" if "identity" in setup else ""
    _assert_both_fail(
        semantic_btrcc,
        tmp_path,
        f"""
        void mutate(int* p) {{ *p = 7; }}
        {identity}
        int main() {{
            int x = 0; {setup}
            try {{ {mutation} throw "boom"; }}
            catch (string error) {{}}
            return x;
        }}
        """,
        "unsupported layered pointer qualifiers",
    )


def test_parameter_effect_depth_is_not_clamped_at_eight(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    source = """
        void mutate9(int********* p) { *********p = 7; }
        int main() {
            int x = 0;
            int* p1 = &x; int** p2 = &p1; int*** p3 = &p2;
            int**** p4 = &p3; int***** p5 = &p4;
            int****** p6 = &p5; int******* p7 = &p6;
            int******** p8 = &p7;
            try { mutate9(&p8); throw "boom"; }
            catch (string error) {}
            return x;
        }
    """
    _assert_both_fail(
        semantic_btrcc,
        tmp_path,
        source,
        "unsupported layered pointer qualifiers",
    )


@pytest.mark.parametrize(
    "declarations, setup, mutation",
    (
        ("int* saved;", "saved = &x;", "mutate(saved);"),
        (
            "struct Holder { int* p; };",
            "struct Holder h; h.p = &x;",
            "mutate(h.p);",
        ),
        ("", "int* slots[1]; slots[0] = &x;", "*slots[0] = 7;"),
        (
            "int* saved; void mutate_saved() { *saved = 7; }",
            "saved = &x;",
            "mutate_saved();",
        ),
    ),
)
def test_memory_carried_addresses_fail_at_setjmp_boundary(
    semantic_btrcc: Path,
    tmp_path: Path,
    declarations: str,
    setup: str,
    mutation: str,
) -> None:
    _assert_both_fail(
        semantic_btrcc,
        tmp_path,
        f"""
        {declarations}
        void mutate(int* p) {{ *p = 7; }}
        int main() {{
            int x = 0; {setup}
            try {{ {mutation} throw "boom"; }}
            catch (string error) {{}}
            return x;
        }}
        """,
        "escapes into unmodelled storage",
    )


@pytest.mark.parametrize(
    "declaration",
    (
        "intptr_t bits = (intptr_t)(&value);",
        "struct Holder holder = {&value};",
    ),
)
def test_declaration_initializers_cannot_hide_addresses(
    semantic_btrcc: Path,
    tmp_path: Path,
    declaration: str,
) -> None:
    _assert_both_fail(
        semantic_btrcc,
        tmp_path,
        f"""
        struct Holder {{ int* pointer; }};
        int main() {{
            int value = 0; {declaration}
            try {{ throw "boom"; }} catch (string error) {{}}
            return value;
        }}
        """,
        "escapes into unmodelled storage",
    )


def test_custom_const_extern_is_a_write_and_capture_boundary(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    _assert_both_fail(
        semantic_btrcc,
        tmp_path,
        """
        void sneaky(const int* value);
        int main() {
            int value = 0;
            try { sneaky(&value); throw "boom"; }
            catch (string error) {}
            return value;
        }
        """,
        "escapes into unmodelled storage",
    )


def test_out_pointer_write_invalidates_known_alias_state(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    _assert_both_fail(
        semantic_btrcc,
        tmp_path,
        """
        long strtol(const char* text, char** end, int base);
        int main() {
            char buffer[8]; char* end = null;
            strtol(buffer, &end, 10);
            try { *end = 'x'; throw "boom"; }
            catch (string error) {}
            return buffer[0];
        }
        """,
        "unmodelled pointer value",
    )


@pytest.mark.parametrize(
    "source",
    (
        """
        int* identity(int* value) { return value; }
        int main() {
            int value = 0;
            try { identity(&value); throw "boom"; }
            catch (string error) {}
            return value;
        }
        """,
        """
        int main() {
            int value = 0; int* pointer = &value;
            bool is_null = !pointer;
            try { throw "boom"; } catch (string error) {}
            return is_null ? 1 : value;
        }
        """,
        """
        int main() {
            int value = 0; int* pointer = &value;
            (const void)pointer;
            try { throw "boom"; } catch (string error) {}
            return value;
        }
        """,
        """
        int global_value = 0;
        void mutate(int* value) { *value = 7; }
        int main() {
            int value = 0; int* pointer = &value;
            pointer = &global_value;
            try { mutate(pointer); throw "boom"; }
            catch (string error) {}
            return value;
        }
        """,
        """
        void run(int* pointer) {
            int** pointer_slot = &pointer;
            try { *pointer = 7; throw "boom"; }
            catch (string error) {}
            if (pointer_slot == null) { return; }
        }
        int main() { int value = 0; run(&value); return value == 7 ? 0 : 1; }
        """,
        """
        int value = 0;
        void mutate(int* pointer) { *pointer = 7; }
        int main() {
            int* global_pointer = &value;
            {
                int value = 1; int* local_pointer = &value;
                try { mutate(global_pointer); throw "boom"; }
                catch (string error) {}
                if (*local_pointer != 1) { return 10; }
            }
            return value == 7 ? 0 : 1;
        }
        """,
    ),
)
def test_non_writing_alias_paths_remain_precise(
    semantic_btrcc: Path,
    tmp_path: Path,
    source: str,
) -> None:
    for index, (result, generated) in enumerate(_compile_both(semantic_btrcc, tmp_path, source)):
        assert result.returncode == 0, result.stderr
        assert "volatile int value" not in generated.read_text()
        _strict_build_and_run(
            generated,
            tmp_path / f"setjmp-precise-{index}",
            optimization="-O3",
        )


def test_short_circuit_rebind_joins_unexecuted_path(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    _assert_both_fail(
        semantic_btrcc,
        tmp_path,
        """
        int global_value = 0;
        void mutate(int* value) { *value = 7; }
        int main() {
            int value = 0; int* pointer = &value; bool condition = false;
            condition && ((pointer = &global_value) != null);
            try { mutate(pointer); throw "boom"; }
            catch (string error) {}
            return value;
        }
        """,
        "unsupported layered pointer qualifiers",
    )
