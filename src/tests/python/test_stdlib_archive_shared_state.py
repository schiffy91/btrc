"""Cross-TU ownership contracts for mutable stdlib-archive helper state."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python import stdlib_archive as archive
from src.compiler.python.cli_archive import build_stdlib_archive
from src.compiler.python.ir.helpers.cycles import CYCLES
from src.compiler.python.ir.helpers.string_ownership import STRING_OWNERSHIP
from src.compiler.python.ir.helpers.trycatch import TRYCATCH
from src.compiler.python.stdlib_shared_state import (
    SHARED_STATE_HELPER_GROUPS,
    SHARED_STATE_HELPER_NAMES,
    derive_shared_decls,
    derive_shared_impl,
)
from src.tests.python.stdlib_archive_state_fixture import PROGRAM_SOURCE

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
AR = shutil.which("ar")

ARCHIVE_PROBE_SOURCE = r"""
#include "btrc_stdlib.h"

static unsigned char destroyed_tokens[300];
static unsigned char cleanup_tokens[130];
static void* cleanup_slots[130];

static void noop_destroy(void* object) {
    (void)object;
}

static void no_children(
        void* object, __btrc_field_visit_fn visit_slot, void* context) {
    (void)object;
    (void)visit_slot;
    (void)context;
}

static const __btrc_arc_type suspect_type = {
    no_children,
    noop_destroy,
};
static __btrc_arc_header suspect_node = {
    1,
    1,
    NULL,
    &suspect_type,
    NULL,
};

char* archive_make_managed_string(void) {
    return __btrc_strcat("archive", "-owned");
}

size_t archive_observed_string_live_count(void) {
    return __btrc_string_live_count();
}

void archive_retain_managed_string(char* value) {
    (void)__btrc_string_retain(value);
}

void archive_release_managed_string(char* value) {
    __btrc_string_release(value);
}

static void register_cleanup_slot(void** ptr_ref, __btrc_cleanup_fn fn) {
    if (__btrc_cleanup_cap < 1) __btrc_cleanup_cap = 64;
    if (!__btrc_cleanup_stack) {
        __btrc_cleanup_stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(
            NULL, sizeof(__btrc_cleanup_entry) * (size_t)__btrc_cleanup_cap);
    }
    if (__btrc_cleanup_top + 1 >= __btrc_cleanup_cap) {
        __btrc_cleanup_cap *= 2;
        __btrc_cleanup_stack = (__btrc_cleanup_entry*)__btrc_safe_realloc(
            __btrc_cleanup_stack,
            sizeof(__btrc_cleanup_entry) * (size_t)__btrc_cleanup_cap);
    }
    __btrc_cleanup_top++;
    __btrc_cleanup_stack[__btrc_cleanup_top].ptr_ref = ptr_ref;
    __btrc_cleanup_stack[__btrc_cleanup_top].fn = fn;
    __btrc_cleanup_stack[__btrc_cleanup_top].visit = NULL;
    __btrc_cleanup_stack[__btrc_cleanup_top].try_level = __btrc_try_top;
}

int archive_grow_shared_state(void) {
    (void)&__btrc_thread_spawn;
    (void)&__btrc_throw;
    if (__btrc_destroyed != NULL || __btrc_destroyed_count != 0
            || __btrc_destroyed_cap != 0) return 1;
    if (__btrc_cleanup_stack != NULL || __btrc_cleanup_top != -1
            || __btrc_cleanup_cap != 64) return 2;
    if (__btrc_suspects != NULL || __btrc_suspect_count != 0
            || __btrc_suspect_cap != 0) return 3;

    __btrc_tracking = 1;
    for (int i = 0; i < 300; i++) {
        __btrc_mark_destroyed(&destroyed_tokens[i]);
    }
    for (int i = 0; i < 130; i++) {
        cleanup_slots[i] = &cleanup_tokens[i];
        register_cleanup_slot(&cleanup_slots[i], noop_destroy);
    }
    __btrc_suspect(&suspect_node, no_children, noop_destroy);
    if (__btrc_destroyed_count != 300 || __btrc_destroyed_cap < 300) return 4;
    if (__btrc_cleanup_top != 129 || __btrc_cleanup_cap < 130) return 5;
    if (__btrc_suspect_count != 1 || __btrc_suspect_cap < 1) return 6;
    return 0;
}

int archive_verify_program_growth_and_reset(void) {
    if (__btrc_destroyed_count != 3 || __btrc_destroyed_cap < 3) return 20;
    if (__btrc_cleanup_top != 2 || __btrc_cleanup_cap < 3) return 21;
    if (__btrc_suspect_count != 1 || __btrc_suspect_cap < 1) return 22;
    __btrc_cycle_state_cleanup();
    __btrc_try_state_cleanup();
    if (__btrc_destroyed != NULL || __btrc_destroyed_count != 0
            || __btrc_destroyed_cap != 0 || __btrc_tracking != 0) return 23;
    if (__btrc_cleanup_stack != NULL || __btrc_cleanup_top != -1
            || __btrc_cleanup_cap != 64) return 24;
    if (__btrc_suspects != NULL || __btrc_suspect_count != 0
            || __btrc_suspect_cap != 0 || __btrc_visit_table != NULL
            || __btrc_destroy_table != NULL) return 25;
    return 0;
}
"""


def test_mutable_helper_groups_have_complete_ownership():
    expected_groups = {
        "try_stack": frozenset(
            {
                "__btrc_try_level",
                "__btrc_trycatch_globals",
            }
        ),
        "cleanup_stack": frozenset(
            {
                "__btrc_cleanup_types",
                "__btrc_cleanup_capacity",
            }
        ),
        "destroyed_log": frozenset(
            {
                "__btrc_destroyed_tracking",
                "__btrc_destroyed_capacity",
            }
        ),
        "cycle_suspects": frozenset(
            {
                "__btrc_suspect_state",
                "__btrc_suspect_capacity",
            }
        ),
        "string_registry": frozenset(
            {
                "__btrc_string_registry",
                "__btrc_string_registry_resize",
                "__btrc_string_live_count",
            }
        ),
    }
    expected_names = frozenset().union(*SHARED_STATE_HELPER_GROUPS.values())
    assert expected_groups == SHARED_STATE_HELPER_GROUPS
    assert expected_names == SHARED_STATE_HELPER_NAMES

    state_contracts = (
        (
            TRYCATCH["__btrc_try_level"].c_source + TRYCATCH["__btrc_trycatch_globals"].c_source,
            ("__btrc_try_stack", "__btrc_try_top", "__btrc_try_cap"),
        ),
        (
            TRYCATCH["__btrc_cleanup_types"].c_source + TRYCATCH["__btrc_cleanup_capacity"].c_source,
            ("__btrc_cleanup_stack", "__btrc_cleanup_top", "__btrc_cleanup_cap"),
        ),
        (
            CYCLES["__btrc_destroyed_tracking"].c_source + CYCLES["__btrc_destroyed_capacity"].c_source,
            ("__btrc_destroyed", "__btrc_destroyed_count", "__btrc_destroyed_cap"),
        ),
        (
            CYCLES["__btrc_suspect_state"].c_source + CYCLES["__btrc_suspect_capacity"].c_source,
            (
                "__btrc_suspects",
                "__btrc_suspect_count",
                "__btrc_suspect_cap",
                "__btrc_visit_table",
                "__btrc_destroy_table",
            ),
        ),
        (
            STRING_OWNERSHIP["__btrc_string_registry"].c_source,
            (
                "__btrc_string_lock",
                "__btrc_string_inline_buckets",
                "__btrc_string_buckets",
                "__btrc_string_bucket_count",
                "__btrc_string_entry_count",
            ),
        ),
    )
    for source, symbols in state_contracts:
        assert all(symbol in source for symbol in symbols)


def test_string_registry_declarations_are_derived_without_initializers():
    source = "\n".join(STRING_OWNERSHIP[name].c_source for name in SHARED_STATE_HELPER_GROUPS["string_registry"])
    declarations = derive_shared_decls(source)
    implementation = derive_shared_impl(source)

    assert "typedef struct __btrc_string_entry {" in declarations
    assert "extern atomic_flag __btrc_string_lock;" in declarations
    assert ("extern __btrc_string_entry* __btrc_string_inline_buckets[64];") in declarations
    assert "extern __btrc_string_entry** __btrc_string_buckets;" in declarations
    assert "extern size_t __btrc_string_entry_count;" in declarations
    assert "void __btrc_string_registry_lock(void);" in declarations
    assert "size_t __btrc_string_live_count(void);" in declarations
    assert "ATOMIC_FLAG_INIT" not in declarations
    assert "typedef struct __btrc_string_entry" not in implementation
    assert "atomic_flag __btrc_string_lock = ATOMIC_FLAG_INIT;" in implementation
    assert "size_t __btrc_string_live_count(void) {" in implementation


def _compile_object(
    compiler: str,
    include_dir: Path,
    source: Path,
    output: Path,
) -> None:
    subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O1",
            f"-I{include_dir}",
            "-c",
            str(source),
            "-o",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.skipif(
    not COMPILERS or AR is None or sys.platform == "win32",
    reason="requires a hosted C11 compiler and archiver",
)
@pytest.mark.parametrize("c_compiler", COMPILERS, ids=lambda path: Path(path).name)
def test_shared_capacity_growth_and_reset_cross_archive_boundary(
    tmp_path: Path,
    c_compiler: str,
):
    output = tmp_path / "stdlib"
    build_stdlib_archive(str(output))

    archive_probe = output / "archive_probe.c"
    program = output / "program.c"
    archive_probe.write_text(ARCHIVE_PROBE_SOURCE)
    program.write_text(PROGRAM_SOURCE)

    stdlib_object = output / "btrc_stdlib.o"
    archive_probe_object = output / "archive_probe.o"
    program_object = output / "program.o"
    _compile_object(
        c_compiler,
        output,
        output / archive.IMPL_NAME,
        stdlib_object,
    )
    _compile_object(
        c_compiler,
        output,
        archive_probe,
        archive_probe_object,
    )
    _compile_object(
        c_compiler,
        output,
        program,
        program_object,
    )

    library = output / "libbtrc.a"
    subprocess.run(
        [AR, "rcs", str(library), str(stdlib_object), str(archive_probe_object)],
        check=True,
        capture_output=True,
        text=True,
    )
    binary = output / "shared_state"
    subprocess.run(
        [
            c_compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(program_object),
            str(library),
            "-lm",
            "-pthread",
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([binary], check=True, capture_output=True, text=True)
