"""Strict-C execution checks for generated exception cleanup slots."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog

TRYCATCH = {helper.name: helper for helper in RuntimeHelperCatalog().definitions_in_category("trycatch")}
from src.tests.python.test_codegen import emit_c

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))


def _strict_build_and_run(
    generated: str,
    tmp_path: Path,
    c_compiler: str,
    optimization: str,
    name: str,
) -> None:
    source = tmp_path / f"{name}.c"
    binary = tmp_path / name
    source.write_text(generated)
    compiled = subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            optimization,
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr


def test_all_exception_message_captures_use_shared_bounded_copy() -> None:
    copy_helper = TRYCATCH["__btrc_copy_error_message"]
    throw_helper = TRYCATCH["__btrc_throw"]
    guard_helper = TRYCATCH["__btrc_arc_guard_hook"]

    assert "memmove(destination, source, length);" in copy_helper.c_source
    assert "destination[length] = '\\0';" in copy_helper.c_source
    assert "strncpy" not in throw_helper.c_source
    assert "strncpy" not in guard_helper.c_source
    assert "__btrc_copy_error_message" in throw_helper.depends_on
    assert "__btrc_copy_error_message" in guard_helper.depends_on

    generated = emit_c("""
        int main() {
            try { throw "primary"; }
            finally { print("cleanup"); }
            return 0;
        }
    """)
    assert "strncpy(" not in generated
    assert generated.count("__btrc_copy_error_message(") >= 3


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_error_message_copy_is_overlap_safe_and_strict_c11_o3(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    helper = TRYCATCH["__btrc_copy_error_message"].c_source
    source = f"""
        #include <stddef.h>
        #include <string.h>
        {helper}

        int main(void) {{
            char long_source[2049];
            memset(long_source, 'x', sizeof long_source - 1);
            long_source[sizeof long_source - 1] = '\\0';
            char truncated[1024];
            __btrc_copy_error_message(truncated, sizeof truncated, long_source);
            if (strlen(truncated) != 1023 || truncated[1023] != '\\0') return 1;

            char forward[16] = "abcdef";
            __btrc_copy_error_message(forward + 1, sizeof forward - 1, forward);
            if (strcmp(forward, "aabcdef") != 0) return 2;

            char backward[16] = "abcdef";
            __btrc_copy_error_message(backward, sizeof backward, backward + 1);
            if (strcmp(backward, "bcdef") != 0) return 3;

            char one[2] = {{'x', 'y'}};
            __btrc_copy_error_message(one, 1, "value");
            if (one[0] != '\\0' || one[1] != 'y') return 4;

            char empty[2] = {{'x', '\\0'}};
            __btrc_copy_error_message(empty, sizeof empty, NULL);
            if (empty[0] != '\\0') return 5;
            __btrc_copy_error_message(NULL, 8, "ignored");
            return 0;
        }}
    """
    _strict_build_and_run(source, tmp_path, c_compiler, "-O3", "error_message_copy")


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("optimization", ("-O0", "-O2", "-O3"))
def test_generated_cleanup_slots_survive_strict_optimized_longjmp(
    tmp_path: Path,
    c_compiler: str,
    optimization: str,
):
    generated = emit_c("""
        class Item {
            public int value;
            public Item(int value) { self.value = value; }
        }
        int read(keep Item item) { return item.value; }
        int main() {
            int observed = 0;
            try {
                observed = read(new Item(7));
                throw "boom";
            } catch (string message) {
                if (!message.equals("boom")) { return 2; }
            }
            return observed == 7 ? 0 : 3;
        }
    """)
    _strict_build_and_run(generated, tmp_path, c_compiler, optimization, "generated_cleanup")


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize(
    ("name", "source"),
    (
        (
            "ordinary_finally_return",
            """
            int cleaned = 0;
            int run() {
                try { return 7; }
                finally { cleaned++; }
            }
            int main() { return run() == 7 && cleaned == 0 ? 0 : 1; }
            """,
        ),
        (
            "generic_finally_return",
            """
            int cleaned = 0;
            class Box<T> {
                public T value;
                public Box(T value) { self.value = value; }
                public int run() {
                    try { return 7; }
                    finally { cleaned++; }
                }
            }
            int main() {
                Box<int> box = new Box<int>(1);
                return box.run() == 7 && cleaned == 0 ? 0 : 1;
            }
            """,
        ),
    ),
)
def test_terminal_finally_paths_are_strict_c11(
    tmp_path: Path,
    c_compiler: str,
    name: str,
    source: str,
) -> None:
    generated = emit_c(source)
    assert "__btrc_finally_pending" not in generated
    _strict_build_and_run(generated, tmp_path, c_compiler, "-O0", name)


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_finally_keeps_one_static_storage_object(tmp_path: Path, c_compiler: str) -> None:
    generated = emit_c("""
        int run(bool fail) {
            try {
                if (fail) { throw "boom"; }
            } finally {
                static int calls = 0;
                calls++;
                return calls;
            }
        }
        int main() {
            if (run(false) != 1) { return 1; }
            return run(true) == 2 ? 0 : 2;
        }
    """)
    assert generated.count("static int calls = 0;") == 1
    _strict_build_and_run(generated, tmp_path, c_compiler, "-O0", "finally_static_storage")


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("optimization", ("-O0", "-O3"))
def test_aggregate_mutations_survive_optimized_longjmp(
    tmp_path: Path,
    c_compiler: str,
    optimization: str,
) -> None:
    generated = emit_c("""
        struct Probe { int value; };
        int main() {
            int values[1] = {0};
            struct Probe probe = {0};
            try {
                values[0] = 7;
                probe.value = 9;
                throw "done";
            } catch (string message) {}
            return values[0] == 7 && probe.value == 9 ? 0 : 1;
        }
    """)
    assert "volatile int values[1]" in generated
    assert "volatile struct Probe probe" in generated
    _strict_build_and_run(
        generated,
        tmp_path,
        c_compiler,
        optimization,
        f"aggregate_longjmp_{optimization[2:]}",
    )


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
@pytest.mark.parametrize("optimization", ("-O0", "-O3"))
def test_read_only_pointer_calls_do_not_force_aggregate_volatile(
    tmp_path: Path,
    c_compiler: str,
    optimization: str,
) -> None:
    generated = emit_c("""
        struct Probe { int value; };
        int readValue(int* value) { return *value; }
        int readProbe(struct Probe* probe) { return readValue(&probe->value); }
        int run(struct Probe probe) {
            int result = 0;
            int* alias = &probe.value;
            try {
                result = readProbe(&probe) + readValue(alias);
                throw "done";
            } catch (string message) {}
            return result;
        }
        int main() {
            struct Probe probe = {21};
            return run(probe) == 42 ? 0 : 1;
        }
    """)
    assert "volatile struct Probe" not in generated
    _strict_build_and_run(
        generated,
        tmp_path,
        c_compiler,
        optimization,
        f"read_only_pointer_{optimization[2:]}",
    )
