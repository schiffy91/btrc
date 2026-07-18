"""Cross-TU ownership contracts for mutable stdlib-archive helper state."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.compiler.python import stdlib_archive as archive
from src.compiler.python.cli_archive import build_stdlib_archive
from src.compiler.python.ir.gen.helpers import helper_decls_for_roots
from src.compiler.python.ir.helpers.cycles import CYCLES
from src.compiler.python.ir.helpers.string_ownership import STRING_OWNERSHIP
from src.compiler.python.ir.helpers.trycatch import TRYCATCH
from src.compiler.python.ir.nodes import IRModule
from src.compiler.python.stdlib_archive_helpers import (
    ARCHIVE_HELPER_API_GROUPS,
    ARCHIVE_HELPER_API_NAMES,
)
from src.compiler.python.stdlib_shared_state import (
    SHARED_STATE_API_ROOTS,
    SHARED_STATE_HELPER_GROUPS,
    SHARED_STATE_HELPER_NAMES,
    _function_definition_prototype,
    _split_toplevel_units,
    derive_shared_decls,
    derive_shared_impl,
    inline_toplevel_functions,
)
from src.tests.python.stdlib_archive_state_fixture import PROGRAM_SOURCE

COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
AR = shutil.which("ar")

ARCHIVE_PROBE_SOURCE = r"""
#include "btrc_stdlib.h"

static unsigned char destroyed_tokens[300];
static unsigned char cleanup_tokens[130];
static void* volatile cleanup_slots[130];

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
    .visit = no_children,
    .destroy = noop_destroy,
    .hook = NULL,
    .guard = NULL,
    .raise = NULL,
};
static __btrc_arc_header suspect_node = {
    .rc = 1,
    .edge_rc = 1,
    .live_witness = NULL,
    .type = &suspect_type,
    .incoming = NULL,
    .deferred_next = NULL,
    .suppress_hook = 0,
    .state = __BTRC_ARC_LIVE,
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

static void* take_cleanup_slot(void* raw) {
    void* volatile* slot = (void* volatile*)raw;
    void* value = *slot;
    *slot = NULL;
    return value;
}

static void register_cleanup_slot(
        void* volatile* slot, __btrc_cleanup_fn fn) {
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
    __btrc_cleanup_stack[__btrc_cleanup_top].slot = (void*)slot;
    __btrc_cleanup_stack[__btrc_cleanup_top].take = take_cleanup_slot;
    __btrc_cleanup_stack[__btrc_cleanup_top].fn = fn;
    __btrc_cleanup_stack[__btrc_cleanup_top].visit = NULL;
    __btrc_cleanup_stack[__btrc_cleanup_top].try_level = __btrc_try_top;
    __btrc_cleanup_stack[__btrc_cleanup_top].direct = 1;
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
    __btrc_tracking = 0;
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
                "__btrc_try_capacity",
                "__btrc_launder_state",
            }
        ),
        "cleanup_stack": frozenset(
            {
                "__btrc_cleanup_types",
                "__btrc_cleanup_capacity",
            }
        ),
        "arc_runtime": frozenset(
            {
                "__btrc_arc_lock_state",
                "__btrc_arc_shutdown_state",
                "__btrc_arc_active_drains_state",
                "__btrc_arc_active_unwinds_state",
                "__btrc_arc_snapshot_state",
                "__btrc_arc_snapshot_gate_state",
                "__btrc_arc_abandon_callback_state",
                "__btrc_arc_abandon_queue_state",
                "__btrc_arc_topology_state",
                "__btrc_arc_topology_depth_state",
                "__btrc_arc_deferred_state",
                "__btrc_destroyed_tracking",
                "__btrc_destroyed_capacity",
                "__btrc_suspect_state",
                "__btrc_suspect_capacity",
                "__btrc_arc_reverse_state",
                "__btrc_cycle_collector_state",
            }
        ),
        "string_registry": frozenset(
            {
                "__btrc_string_registry",
                "__btrc_string_registry_lock_state",
                "__btrc_string_registry_lock",
                "__btrc_string_registry_hash",
                "__btrc_string_registry_slot",
                "__btrc_string_registry_count",
                "__btrc_string_registry_resize",
                "__btrc_string_live_count",
            }
        ),
    }
    expected_names = frozenset().union(*SHARED_STATE_HELPER_GROUPS.values())
    assert expected_groups == SHARED_STATE_HELPER_GROUPS
    assert expected_names == SHARED_STATE_HELPER_NAMES
    assert set(SHARED_STATE_API_ROOTS) == set(expected_groups)
    assert "__btrc_suspect" in SHARED_STATE_API_ROOTS["arc_runtime"]
    assert "__btrc_cycle_state_cleanup" in SHARED_STATE_API_ROOTS["arc_runtime"]
    assert "__btrc_arc_thread_state_cleanup" in SHARED_STATE_API_ROOTS["arc_runtime"]
    assert "__btrc_try_state_cleanup" in SHARED_STATE_API_ROOTS["try_stack"]

    state_contracts = (
        (
            TRYCATCH["__btrc_try_level"].c_source
            + TRYCATCH["__btrc_trycatch_globals"].c_source
            + TRYCATCH["__btrc_try_capacity"].c_source
            + TRYCATCH["__btrc_launder_state"].c_source,
            (
                "__btrc_try_stack",
                "__btrc_try_top",
                "__btrc_try_cap",
                "__btrc_launder_slot",
            ),
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
            STRING_OWNERSHIP["__btrc_string_registry"].c_source
            + STRING_OWNERSHIP["__btrc_string_registry_lock_state"].c_source
            + STRING_OWNERSHIP["__btrc_string_registry_count"].c_source,
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


def test_all_cross_tu_runtime_storage_has_one_explicit_owner_group():
    runtime_families = (CYCLES, TRYCATCH, STRING_OWNERSHIP)
    mutable_helpers = set()
    for helpers in runtime_families:
        for name, helper in helpers.items():
            for unit in _split_toplevel_units(helper.c_source):
                declaration = unit.lstrip()
                if declaration.startswith("typedef"):
                    continue
                if _function_definition_prototype(unit) is not None:
                    continue
                if declaration.startswith("static ") and not declaration.startswith("static const "):
                    mutable_helpers.add(name)

    assert mutable_helpers <= SHARED_STATE_HELPER_NAMES
    assert {
        name
        for name, helper in CYCLES.items()
        if any(
            unit.lstrip().startswith("static ")
            and not unit.lstrip().startswith("static const ")
            and _function_definition_prototype(unit) is None
            for unit in _split_toplevel_units(helper.c_source)
        )
    } == SHARED_STATE_HELPER_GROUPS["arc_runtime"]


@pytest.mark.parametrize(
    ("root", "expected_groups"),
    [
        ("__btrc_try_level", {"try_stack", "cleanup_stack"}),
        ("__btrc_destroyed_tracking", {"arc_runtime"}),
    ],
)
def test_shared_api_completion_reaches_fixed_point_and_externalizes(root, expected_groups):
    module = IRModule(helper_decls=helper_decls_for_roots({root}))

    archive_owned, declarations = archive.transform_archive_module(module)
    expected = set()
    for group_name in expected_groups:
        expected.update(SHARED_STATE_HELPER_GROUPS[group_name])
        expected.update(SHARED_STATE_API_ROOTS[group_name])

    assert expected <= set(archive_owned)
    assert expected <= {helper.name for helper in module.helper_decls}
    for name in expected:
        assert "static " not in declarations[name]
        helper = next(helper for helper in module.helper_decls if helper.name == name)
        assert "static " not in helper.c_source


def test_worker_arc_state_finalizer_has_cross_tu_linkage():
    module = IRModule(helper_decls=helper_decls_for_roots({"__btrc_thread_spawn"}))

    archive_owned, declarations = archive.transform_archive_module(module)
    cleanup_name = "__btrc_arc_thread_state_cleanup"
    assert cleanup_name in archive_owned
    assert "void __btrc_arc_thread_state_finalize(void);" in declarations[cleanup_name]
    cleanup = next(helper for helper in module.helper_decls if helper.name == cleanup_name)
    assert cleanup.c_source.startswith("void __btrc_arc_thread_state_finalize(void)")
    assert "\nvoid __btrc_arc_thread_state_cleanup(void)" in cleanup.c_source
    spawn = next(helper for helper in module.helper_decls if helper.name == "__btrc_thread_spawn")
    assert "__btrc_arc_thread_state_finalize();" in spawn.c_source


def test_archive_completes_the_thread_handle_lifecycle_api():
    module = IRModule(helper_decls=helper_decls_for_roots({"__btrc_thread_spawn"}))

    archive_owned, declarations = archive.transform_archive_module(module)
    helpers = {helper.name for helper in module.helper_decls}
    lifecycle = ARCHIVE_HELPER_API_GROUPS["thread_handle"]

    assert lifecycle <= helpers
    assert lifecycle == ARCHIVE_HELPER_API_NAMES
    assert lifecycle <= set(archive_owned)
    assert "__btrc_thread_t* __btrc_thread_spawn(" in declarations["__btrc_thread_spawn"]
    assert "void* __btrc_thread_join(" in declarations["__btrc_thread_join"]
    assert "void __btrc_thread_free(" in declarations["__btrc_thread_free"]
    assert "static " not in declarations["__btrc_thread_spawn"]
    assert "__btrc_thread_guard" not in declarations["__btrc_thread_spawn"]
    spawn = next(helper for helper in module.helper_decls if helper.name == "__btrc_thread_spawn")
    assert spawn.c_source.startswith("static int __btrc_thread_guard(")
    assert "\n__btrc_thread_t* __btrc_thread_spawn(" in spawn.c_source
    assert {"__btrc_thread_finish", "__btrc_thread_destroy_handle"} <= helpers
    assert {"__btrc_thread_finish", "__btrc_thread_destroy_handle"}.isdisjoint(archive_owned)
    assert "__btrc_thread_finish" not in lifecycle
    assert "__btrc_thread_destroy_handle" not in lifecycle


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


def test_archive_header_inlines_private_noninline_helpers():
    source = "\n".join(
        (
            "static int state = 0;",
            "static void cleanup(void) { state = 0; }",
            "static inline int current(void) { return state; }",
        )
    )

    header_source = inline_toplevel_functions(source)

    assert "static int state = 0;" in header_source
    assert "static inline void cleanup(void)" in header_source
    assert header_source.count("static inline int current(void)") == 1


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
        timeout=120,
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
        timeout=60,
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
        timeout=120,
    )
    subprocess.run([binary], check=True, capture_output=True, text=True, timeout=30)
