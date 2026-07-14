"""Strict-C simulations for exception cleanup reentrancy."""

import shutil
import subprocess
from pathlib import Path

import pytest

from src.compiler.python.ir.gen.helpers import helper_decls_for_roots
from src.tests.python.test_runtime_helpers_c11 import HEADERS

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
ROOTS = {
    "__btrc_register_direct_cleanup",
    "__btrc_throw",
    "__btrc_try_state_cleanup",
}

RUNTIME = r"""
typedef struct { int id; } Token;

static int cleanup_calls[4];
static int cleanup_order;
static void* volatile nested_slot;

static void* take_slot(void* raw) {
    void* volatile* slot = (void* volatile*)raw;
    void* value = *slot;
    *slot = NULL;
    return value;
}

static void record_cleanup(void* raw) {
    Token* token = (Token*)raw;
    cleanup_calls[token->id]++;
    cleanup_order = cleanup_order * 10 + token->id;
    fprintf(stderr, "cleanup:%d\n", token->id);
}

static void nested_throwing_cleanup(void* raw) {
    record_cleanup(raw);
    __btrc_throw("nested cleanup failure");
}

static void throwing_cleanup(void* raw) {
    static Token nested = {3};
    record_cleanup(raw);
    nested_slot = &nested;
    __btrc_register_direct_cleanup(
        (void*)&nested_slot, take_slot, nested_throwing_cleanup);
    __btrc_throw("cleanup failure");
}

static void reset_state(void) {
    memset(cleanup_calls, 0, sizeof cleanup_calls);
    cleanup_order = 0;
    nested_slot = NULL;
}

static int handled_case(void) {
    Token first = {1};
    Token second = {2};
    void* volatile first_slot = &first;
    void* volatile second_slot = &second;
    reset_state();

    __btrc_push_try();
    int handler_level = __btrc_try_top;
    if (setjmp(__btrc_try_stack[handler_level]->env) == 0) {
        __btrc_register_direct_cleanup(
            (void*)&first_slot, take_slot, record_cleanup);
        __btrc_register_direct_cleanup(
            (void*)&second_slot, take_slot, throwing_cleanup);
        __btrc_throw("primary failure");
    }

    int ok = strcmp(__btrc_error_msg, "primary failure") == 0
        && __btrc_try_top == -1
        && __btrc_cleanup_top == -1
        && first_slot == NULL
        && second_slot == NULL
        && nested_slot == NULL
        && cleanup_calls[1] == 1
        && cleanup_calls[2] == 1
        && cleanup_calls[3] == 1
        && cleanup_order == 231;
    __btrc_try_state_cleanup();
    return ok ? 0 : 1;
}

static _Noreturn void unhandled_case(void) {
    Token first = {1};
    Token second = {2};
    static void* volatile first_slot;
    static void* volatile second_slot;
    reset_state();
    first_slot = &first;
    second_slot = &second;
    __btrc_register_direct_cleanup(
        (void*)&first_slot, take_slot, record_cleanup);
    __btrc_register_direct_cleanup(
        (void*)&second_slot, take_slot, throwing_cleanup);
    __btrc_throw("unhandled primary");
}

int main(int argc, char** argv) {
    if (argc != 2) return 2;
    if (strcmp(argv[1], "handled") == 0) return handled_case();
    if (strcmp(argv[1], "unhandled") == 0) unhandled_case();
    return 3;
}
"""


def _compile(tmp_path: Path, compiler: str) -> Path:
    helpers = "\n\n".join(declaration.c_source for declaration in helper_decls_for_roots(ROOTS))
    source = tmp_path / "cleanup_reentrancy.c"
    executable = tmp_path / "cleanup_reentrancy"
    source.write_text(f"{HEADERS}\n{helpers}\n\n{RUNTIME}")
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            str(source),
            "-pthread",
            "-lm",
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    return executable


@pytest.mark.skipif(not COMPILERS, reason="requires a hosted C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_cleanup_throw_preserves_primary_and_continues_once(
    tmp_path: Path,
    c_compiler: str,
) -> None:
    executable = _compile(tmp_path, c_compiler)

    handled = subprocess.run(
        [str(executable), "handled"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert handled.returncode == 0, handled.stderr
    assert handled.stderr == "cleanup:2\ncleanup:3\ncleanup:1\n"

    unhandled = subprocess.run(
        [str(executable), "unhandled"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert unhandled.returncode == 1
    assert unhandled.stderr == ("cleanup:2\ncleanup:3\ncleanup:1\nUnhandled exception: unhandled primary\n")
