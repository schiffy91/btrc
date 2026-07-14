"""Strict-C execution tests for the non-string runtime helper boundary cases."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python.ir.gen.helpers import helper_decls_for_roots
from src.compiler.python.ir.helpers.alloc import ALLOC
from src.compiler.python.ir.helpers.cycles import CYCLES
from src.compiler.python.ir.helpers.divmod import DIVMOD
from src.compiler.python.ir.helpers.hash import HASH
from src.compiler.python.ir.helpers.math import MATH
from src.compiler.python.ir.helpers.threads import THREADS
from src.compiler.python.ir.helpers.trycatch import TRYCATCH

HEADERS = """\
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <math.h>
#include <setjmp.h>
#include <pthread.h>
"""

HELPER_ORDER = (
    *((ALLOC, name) for name in ALLOC),
    *((DIVMOD, name) for name in DIVMOD),
    *((MATH, name) for name in MATH),
    *((HASH, name) for name in HASH),
    (TRYCATCH, "__btrc_try_level"),
    (TRYCATCH, "__btrc_trycatch_globals"),
    (TRYCATCH, "__btrc_try_capacity"),
    (TRYCATCH, "__btrc_launder_state"),
    (TRYCATCH, "__btrc_launder"),
    (TRYCATCH, "__btrc_push_try"),
    *((CYCLES, name) for name in CYCLES),
    (TRYCATCH, "__btrc_cleanup_types"),
    (TRYCATCH, "__btrc_cleanup_capacity"),
    (TRYCATCH, "__btrc_register_cleanup"),
    (TRYCATCH, "__btrc_discard_cleanups"),
    (TRYCATCH, "__btrc_run_cleanups"),
    (TRYCATCH, "__btrc_throw"),
    (TRYCATCH, "__btrc_try_state_cleanup"),
    *(
        (THREADS, name)
        for name in THREADS
        if name
        not in {
            "__btrc_mutex_string_retain",
            "__btrc_mutex_string_release",
            "__btrc_thread_string_dispose",
        }
    ),
)

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
CLANG = shutil.which("clang")
NO_C11_RUNTIME = not COMPILERS or sys.platform == "win32"


def _source(main: str) -> str:
    roots = {name for _registry, name in HELPER_ORDER}
    helpers = "\n\n".join(helper.c_source for helper in helper_decls_for_roots(roots))
    return f"{HEADERS}\n{helpers}\n\n{main}\n"


def _compile(tmp_path: Path, compiler: str, main: str, *, ubsan=False) -> Path:
    source = tmp_path / "runtime_helpers.c"
    binary = tmp_path / ("runtime_helpers_ubsan" if ubsan else "runtime_helpers")
    source.write_text(_source(main))
    command = [
        compiler,
        "-std=c11",
        "-pedantic-errors",
        "-O1",
        "-Werror=implicit-function-declaration",
        str(source),
        "-pthread",
        "-lm",
        "-o",
        str(binary),
    ]
    if ubsan:
        command[1:1] = ["-fsanitize=undefined", "-fno-sanitize-recover=all"]
    subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return binary


@pytest.mark.skipif(not CLANG or sys.platform == "win32", reason="requires Clang")
def test_direct_cleanup_helper_is_warning_clean_without_indirect_wrapper(tmp_path: Path):
    helpers = helper_decls_for_roots({"__btrc_register_direct_cleanup"})
    names = [helper.name for helper in helpers]
    assert "__btrc_register_cleanup_kind" in names
    assert "__btrc_register_direct_cleanup" in names
    assert "__btrc_register_cleanup" not in names

    runtime = "\n\n".join(helper.c_source for helper in helpers)
    source = tmp_path / "direct_cleanup.c"
    binary = tmp_path / "direct_cleanup"
    source.write_text(
        f"{HEADERS}\n{runtime}\n"
        "static void cleanup(void* value) { (void)value; }\n"
        "static void* take(void* raw) {\n"
        "    void* volatile* slot = (void* volatile*)raw;\n"
        "    void* value = *slot; *slot = NULL; return value;\n"
        "}\n"
        "int main(void) {\n"
        "    void* volatile value = NULL;\n"
        "    __btrc_register_direct_cleanup((void*)&value, take, cleanup);\n"
        "    return __btrc_cleanup_top == 0 ? 0 : 1;\n"
        "}\n"
    )
    compiled = subprocess.run(
        [
            CLANG,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(source),
            "-o",
            str(binary),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([str(binary)], capture_output=True, text=True, timeout=15)
    assert executed.returncode == 0, executed.stderr


@pytest.mark.skipif(NO_C11_RUNTIME, reason="requires a pthread C11 compiler")
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_runtime_helpers_execute_boundary_cases_under_strict_c11(tmp_path: Path, c_compiler: str):
    main = r"""
typedef struct TestNode {
    __btrc_arc_header arc;
    struct TestNode* child;
} TestNode;
static const __btrc_arc_type test_type;
static void test_visit(void* raw, __btrc_field_visit_fn fn, void* context) {
    TestNode* node = (TestNode*)raw;
    fn((void**)&node->child, &test_type, context);
}
static void test_destroy(void* raw) { free(raw); }
static const __btrc_arc_type test_type = {test_visit, test_destroy};
static void test_cleanup(void* raw) { (void)raw; }
static void* test_take(void* raw) {
    void* volatile* slot = (void* volatile*)raw;
    void* value = *slot;
    *slot = NULL;
    return value;
}
static void* return_arg(void* arg) { return arg; }

int main(void) {
    if (__btrc_mod_int(INT_MIN, -1) != 0) return 1;
    if (__btrc_div(9000000000L, 2L) != 4500000000L) return 18;
    if (__btrc_div(4000000000U, 2U) != 2000000000U) return 19;
    if (__btrc_mod(3889019093U, 4U) != 1U) return 20;
    if (__btrc_mod(7.9, 2.0) != 1) return 21;
    if (__btrc_hash_real(0.0L) != __btrc_hash_real(-0.0L)) return 22;
    if (__btrc_hash_real(INFINITY) != __btrc_hash_real(INFINITY)) return 23;
    if (__btrc_math_gcd(-42, 56) != 14) return 2;
    if (__btrc_math_lcm(-21, 6) != 42) return 3;
    if (__btrc_math_fibonacci(46) != 1836311903) return 4;
    if (!__btrc_math_isPrime(INT_MAX)) return 5;
    int ints[] = {INT_MAX, -INT_MAX, 7};
    float floats[] = {1.0f, 2.5f};
    if (__btrc_math_sum_int(ints, 3) != 7) return 6;
    if (__btrc_math_fsum(floats, 2) != 3.5f) return 7;
    if (__btrc_hash_str(NULL) != 0) return 8;

    void* zero = __btrc_safe_calloc(0, SIZE_MAX);
    free(zero);
    void* resized = __btrc_safe_realloc(NULL, 8);
    if (__btrc_safe_realloc(resized, 0) != NULL) return 9;

    TestNode* node = (TestNode*)__btrc_safe_calloc(1, sizeof(TestNode));
    node->arc.rc = 2;
    node->arc.edge_rc = 2;
    node->arc.type = &test_type;
    __btrc_suspect(node, test_visit, test_destroy);
    __btrc_suspect(node, test_visit, test_destroy);
    if (__btrc_suspect_count != 1) return 10;
    __btrc_collect_cycles();
    if (__btrc_suspect_count != 0 || node->arc.rc != 2
            || node->arc.edge_rc != 2
            || node->arc.live_witness != node) return 11;
    __btrc_cycle_state_cleanup();
    free(node);

    for (int i = 0; i < 80; i++) __btrc_push_try();
    if (__btrc_try_top != 79 || __btrc_try_cap < 80) return 12;
    __btrc_try_top = -1;
    void* volatile cleanup_ptrs[80];
    for (int i = 0; i < 80; i++) {
        cleanup_ptrs[i] = (void*)(intptr_t)(i + 1);
        __btrc_register_cleanup(
            (void*)&cleanup_ptrs[i], test_take, test_cleanup, NULL);
    }
    if (__btrc_cleanup_top != 79 || __btrc_cleanup_cap < 80) return 13;
    __btrc_register_cleanup(
        (void*)&cleanup_ptrs[79], test_take, test_cleanup, NULL);
    if (__btrc_cleanup_top != 79) return 24;
    __btrc_try_state_cleanup();

    void* token = (void*)(intptr_t)41;
    __btrc_thread_t* thread = __btrc_thread_spawn(
        return_arg, token, NULL, 0, NULL);
    if (__btrc_thread_join(thread) != token) return 14;

    int* initial = (int*)malloc(sizeof *initial);
    if (!initial) return 15;
    *initial = 41;
    __btrc_mutex_val_t* mutex = __btrc_mutex_val_create(
        initial, sizeof *initial, NULL, 0, NULL, NULL);
    int* snapshot = (int*)__btrc_mutex_val_get(mutex);
    if (!snapshot || *snapshot != 41 || snapshot == initial) return 16;
    free(snapshot);
    int* replacement = (int*)malloc(sizeof *replacement);
    if (!replacement) return 17;
    *replacement = 73;
    __btrc_mutex_val_set(mutex, replacement);
    snapshot = (int*)__btrc_mutex_val_get(mutex);
    if (!snapshot || *snapshot != 73 || snapshot == replacement) return 25;
    free(snapshot);
    __btrc_mutex_val_destroy(mutex);
    __btrc_mutex_val_destroy(NULL);
    return 0;
}
"""
    binary = _compile(tmp_path, c_compiler, main)
    subprocess.run([binary], check=True, timeout=15)


@pytest.mark.skipif(NO_C11_RUNTIME, reason="requires a pthread C11 compiler")
def test_overflow_guards_fail_before_undefined_behavior(tmp_path: Path):
    main = r"""
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    if (strcmp(argv[1], "div") == 0) return __btrc_div_int(INT_MIN, -1);
    if (strcmp(argv[1], "div_long") == 0)
        return (int)__btrc_div(LONG_MIN, -1L);
    if (strcmp(argv[1], "div_zero") == 0)
        return (int)__btrc_div(1ULL, 0ULL);
    if (strcmp(argv[1], "mod_zero") == 0)
        return __btrc_mod(1U, 0U);
    if (strcmp(argv[1], "mod_real") == 0)
        return __btrc_mod(INFINITY, 2.0);
    if (strcmp(argv[1], "calloc") == 0) {
        (void)__btrc_safe_calloc(SIZE_MAX, 2); return 0;
    }
    if (strcmp(argv[1], "fib") == 0) return __btrc_math_fibonacci(47);
    if (strcmp(argv[1], "lcm") == 0) return __btrc_math_lcm(INT_MAX, 2);
    int values[] = {INT_MAX, 1};
    return __btrc_math_sum_int(values, 2);
}
"""
    binary = None
    for c_compiler in reversed(COMPILERS):
        try:
            binary = _compile(tmp_path, c_compiler, main, ubsan=True)
            break
        except subprocess.CalledProcessError:
            continue
    if binary is None:
        pytest.skip("installed C compilers do not provide a UBSan runtime")
    expected = {
        "div": "Integer division overflow",
        "div_long": "Integer division overflow",
        "div_zero": "Division by zero",
        "mod_zero": "Modulo by zero",
        "mod_real": "Floating modulo conversion out of range",
        "calloc": "calloc size overflow",
        "fib": "fibonacci result overflow",
        "lcm": "lcm result overflow",
        "sum": "sum result overflow",
    }
    for case, message in expected.items():
        result = subprocess.run([binary, case], capture_output=True, text=True, timeout=15)
        assert result.returncode != 0, case
        assert message in result.stderr, case
        assert "runtime error:" not in result.stderr, case
