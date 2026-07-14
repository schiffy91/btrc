"""Parity and dependency contracts for non-string runtime helpers."""

import ast
import re
from pathlib import Path

from src.compiler.python.ir.gen.helpers import helper_decls_for_roots
from src.compiler.python.ir.helpers.alloc import ALLOC
from src.compiler.python.ir.helpers.collections import COLLECTIONS
from src.compiler.python.ir.helpers.cycles import CYCLES
from src.compiler.python.ir.helpers.divmod import DIVMOD
from src.compiler.python.ir.helpers.hash import HASH
from src.compiler.python.ir.helpers.math import MATH
from src.compiler.python.ir.helpers.registry import HELPERS
from src.compiler.python.ir.helpers.threads import THREADS
from src.compiler.python.ir.helpers.trycatch import TRYCATCH

AUDITED = {name: helper for name, helper in (ALLOC | DIVMOD | MATH | TRYCATCH | HASH | CYCLES | THREADS).items()}
MIRROR = Path("src/compiler/btrc/ir_nodes.btrc")
TRYCATCH_SOURCE_MIRRORS = tuple(
    Path(f"src/compiler/btrc/trycatch_runtime_{suffix}.btrc") for suffix in ("state", "cleanup", "control")
)
TRYCATCH_DEPENDENCY_MIRROR = Path("src/compiler/btrc/trycatch_runtime_dependencies.btrc")
CYCLE_SOURCE_MIRRORS = tuple(
    Path(f"src/compiler/btrc/cycle_runtime_{suffix}.btrc")
    for suffix in (
        "state",
        "lock",
        "snapshot",
        "incoming",
        "retain",
        "release",
        "lifecycle",
        "collector_prefix",
        "abandon",
        "abandon_queue",
        "collector_suffix",
        "drain",
        "boundaries",
    )
)
THREAD_SOURCE_MIRRORS = (
    Path("src/compiler/btrc/thread_runtime_threads.btrc"),
    Path("src/compiler/btrc/thread_runtime_mutex_core.btrc"),
    Path("src/compiler/btrc/thread_runtime_mutex_ops.btrc"),
    Path("src/compiler/btrc/thread_runtime_mutex_owner.btrc"),
)
CYCLE_DEPENDENCY_MIRRORS = (
    Path("src/compiler/btrc/cycle_runtime_dependencies_state.btrc"),
    Path("src/compiler/btrc/cycle_runtime_dependencies_lifecycle.btrc"),
)
THREAD_DEPENDENCY_MIRROR = Path("src/compiler/btrc/thread_runtime_helpers.btrc")


def _self_hosted_sources(source: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    pattern = re.compile(
        r'^    if \(name == "([^"]+)"\) \{\n(.*?)^    \}',
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(source):
        literals = re.findall(r'"(?:\\.|[^"\\])*"', match.group(2))
        blocks[match.group(1)] = "".join(ast.literal_eval(item) for item in literals)
    return blocks


def _mirrored_sources() -> dict[str, str]:
    mirrored = _self_hosted_sources(MIRROR.read_text())
    for path in (
        *TRYCATCH_SOURCE_MIRRORS,
        *CYCLE_SOURCE_MIRRORS,
        *THREAD_SOURCE_MIRRORS,
    ):
        mirrored.update(_self_hosted_sources(path.read_text()))
    return mirrored


def test_self_hosted_non_string_sources_exactly_match_python_registry():
    mirrored = _mirrored_sources()

    assert set(AUDITED) <= set(mirrored)
    for name, helper in AUDITED.items():
        assert mirrored[name] == helper.c_source, name


def test_split_runtime_families_have_no_legacy_helper_branches():
    source = MIRROR.read_text()
    helper_sources = source[source.index("string helperSource") : source.index("Vector<string> helperDeps")]
    helper_dependencies = source[
        source.index("Vector<string> helperDeps") : source.index("Vector<string> helperHeaders")
    ]

    for name in set(CYCLES) | set(TRYCATCH) | set(THREADS):
        marker = f'if (name == "{name}")'
        assert marker not in helper_sources, name
        assert marker not in helper_dependencies, name


def test_self_hosted_dependency_edges_cover_checked_runtime_roots():
    source = MIRROR.read_text()
    cycle_source = "\n".join(path.read_text() for path in CYCLE_DEPENDENCY_MIRRORS)
    trycatch_source = TRYCATCH_DEPENDENCY_MIRROR.read_text()
    thread_source = THREAD_DEPENDENCY_MIRROR.read_text()
    required_edges = {
        "__btrc_math_lcm": "__btrc_math_gcd",
        "__btrc_push_try": "__btrc_safe_realloc",
        "__btrc_register_cleanup_kind": "__btrc_safe_realloc",
        "__btrc_register_cleanup": "__btrc_register_cleanup_kind",
        "__btrc_register_direct_cleanup": "__btrc_register_cleanup_kind",
        "__btrc_run_cleanup_guarded": "__btrc_arc_release",
        "__btrc_flush_cycles_guarded": "__btrc_flush_cycles",
        "__btrc_run_cleanups": "__btrc_is_destroyed",
        "__btrc_is_destroyed": "__btrc_destroyed_tracking",
        "__btrc_collect_cycles": "__btrc_arc_drain",
        "__btrc_collect_cycles_once": "__btrc_suspect_state",
        "__btrc_arc_header_of": "__btrc_arc_callback_types",
        "__btrc_arc_type_of": "__btrc_arc_header_of",
        "__btrc_arc_validate": "__btrc_arc_header_of",
        "__btrc_arc_deferred_state": "__btrc_arc_header_of",
        "__btrc_arc_mutation_lock": "__btrc_arc_snapshot_state",
        "__btrc_arc_exclusive_snapshot": "__btrc_arc_snapshot_gate_state",
        "__btrc_arc_topology_begin": "__btrc_arc_topology_state",
        "__btrc_arc_topology_leave": "__btrc_arc_topology_depth_state",
        "__btrc_arc_topology_cleanup": "__btrc_arc_topology_leave",
        "__btrc_arc_topology_complete": "__btrc_flush_cycles",
        "__btrc_arc_register_incoming": "__btrc_arc_header_of",
        "__btrc_arc_unregister_incoming": "__btrc_arc_header_of",
        "__btrc_arc_reverse_proves_live": "__btrc_arc_reverse_state",
        "__btrc_arc_retain_edge": "__btrc_arc_register_incoming",
        "__btrc_arc_adopt_edge": "__btrc_arc_register_incoming",
        "__btrc_forget_suspect": "__btrc_suspect_state",
        "__btrc_suspect": "__btrc_suspect_locked",
        "__btrc_arc_release": "__btrc_arc_release_impl",
        "__btrc_arc_release_edge": "__btrc_arc_release_impl",
        "__btrc_arc_replace_edge": "__btrc_arc_release_impl",
        "__btrc_arc_release_acyclic": "__btrc_arc_validate",
        "__btrc_cycle_state_cleanup": "__btrc_flush_cycles",
        "__btrc_arc_thread_state_cleanup": "__btrc_arc_abandon_queue_drain",
        "__btrc_thread_spawn": "__btrc_try_state_cleanup",
        "__btrc_thread_finish": "__btrc_thread_spawn",
        "__btrc_thread_destroy_handle": "__btrc_thread_spawn",
        "__btrc_thread_box_dispose": "__btrc_thread_spawn",
        "__btrc_thread_arc_dispose": "__btrc_arc_release",
        "__btrc_thread_string_dispose": "__btrc_string_release",
        "__btrc_thread_join": "__btrc_thread_finish",
        "__btrc_thread_free": "__btrc_thread_finish",
        "__btrc_mutex_val_create": "__btrc_safe_realloc",
        "__btrc_mutex_arc_retain": "__btrc_arc_retain",
        "__btrc_mutex_arc_release": "__btrc_arc_release",
        "__btrc_mutex_string_retain": "__btrc_string_retain",
        "__btrc_mutex_string_release": "__btrc_string_release",
    }

    for helper, dependency in required_edges.items():
        if helper in CYCLES:
            dependency_source = cycle_source
        elif helper in TRYCATCH:
            dependency_source = trycatch_source
        elif helper in THREADS:
            dependency_source = thread_source[thread_source.index("threadRuntimeHelperDependencies") :]
        else:
            dependency_source = source[source.index("helperDeps") :]
        marker = f'if (name == "{helper}")'
        start = dependency_source.index(marker)
        next_if = dependency_source.find("if (name ==", start + len(marker))
        branch = dependency_source[start : next_if if next_if >= 0 else None]
        assert f'out.push("{dependency}")' in branch, helper

    begin_marker = 'if (name == "__btrc_arc_topology_begin")'
    begin_start = cycle_source.index(begin_marker)
    begin_end = cycle_source.index("if (name ==", begin_start + len(begin_marker))
    assert 'out.push("__btrc_arc_topology_depth_state")' in cycle_source[begin_start:begin_end]

    known_helpers = {name for category in HELPERS.values() for name in category}
    for name, helper in AUDITED.items():
        assert set(helper.depends_on) <= known_helpers, name


def test_generic_helpers_are_not_rooted_by_generic_instantiation_alone():
    source = Path("src/compiler/btrc/irgen.btrc").read_text()

    assert "genericMacrosText" not in source
    assert source.count('useHelper("__btrc_hash_str")') == 1
    intrinsic = source[source.index("lowerGenericIntrinsic") : source.index("public IRNode lowerCall")]
    assert 'useHelper("__btrc_hash_str")' in intrinsic


def test_python_generic_intrinsics_are_not_macro_helpers():
    assert set(HASH) == {"__btrc_hash_real", "__btrc_hash_str"}
    for obsolete in ("__btrc_eq", "__btrc_lt", "__btrc_gt", "__btrc_hash"):
        assert obsolete not in HASH


def test_throw_roots_the_internal_cleanup_guard_stack():
    throw_helpers = {declaration.name for declaration in helper_decls_for_roots({"__btrc_throw"})}
    push_helpers = {declaration.name for declaration in helper_decls_for_roots({"__btrc_push_try"})}

    assert "__btrc_trycatch_globals" in throw_helpers
    assert "__btrc_push_try" in throw_helpers
    assert "__btrc_try_capacity" in throw_helpers
    assert "__btrc_try_capacity" in push_helpers


def test_topology_cleanup_drain_omits_unused_abandon_queue_storage():
    helpers = {declaration.name for declaration in helper_decls_for_roots({"__btrc_arc_topology_cleanup"})}

    assert "__btrc_arc_abandon_queue_drain" in helpers
    assert "__btrc_arc_abandon_callback_state" in helpers
    assert "__btrc_arc_abandon_queue_state" not in helpers


def test_cleanup_setjmp_is_confined_to_non_inline_guards():
    cleanup_guard = TRYCATCH["__btrc_run_cleanup_guarded"]
    flush_guard = TRYCATCH["__btrc_flush_cycles_guarded"]
    run_cleanups = TRYCATCH["__btrc_run_cleanups"]

    assert cleanup_guard.c_source.startswith("static void __btrc_run_cleanup_guarded(")
    assert flush_guard.c_source.startswith("static void __btrc_flush_cycles_guarded(")
    assert cleanup_guard.c_source.count("setjmp(") == 1
    assert flush_guard.c_source.count("setjmp(") == 1
    assert "setjmp(" not in run_cleanups.c_source
    assert "__btrc_run_cleanup_guarded(entry, object);" in run_cleanups.c_source
    assert "__btrc_flush_cycles_guarded();" in run_cleanups.c_source
    assert "__btrc_run_cleanup_guarded" in run_cleanups.depends_on
    assert "__btrc_flush_cycles_guarded" in run_cleanups.depends_on


def test_self_hosted_order_keeps_tls_cleanup_before_thread_wrappers():
    source = MIRROR.read_text()
    ordered = (
        "__btrc_math_gcd",
        "__btrc_math_lcm",
        "__btrc_trycatch_globals",
        "__btrc_try_capacity",
        "__btrc_push_try",
        "__btrc_arc_callback_types",
        "__btrc_arc_header_of",
        "__btrc_arc_type_of",
        "__btrc_arc_validate",
        "__btrc_destroyed_tracking",
        "__btrc_arc_lock_state",
        "__btrc_arc_snapshot_state",
        "__btrc_arc_snapshot_gate_state",
        "__btrc_arc_mutation_lock",
        "__btrc_is_destroyed",
        "__btrc_arc_topology_state",
        "__btrc_arc_topology_depth_state",
        "__btrc_arc_topology_begin",
        "__btrc_arc_topology_leave",
        "__btrc_arc_deferred_state",
        "__btrc_arc_unregister_incoming",
        "__btrc_flush_cycles",
        "__btrc_arc_topology_cleanup",
        "__btrc_arc_topology_complete",
        "__btrc_arc_reverse_state",
        "__btrc_arc_register_incoming",
        "__btrc_arc_reverse_proves_live",
        "__btrc_collect_cycles",
        "__btrc_cycle_state_cleanup",
        "__btrc_cleanup_types",
        "__btrc_run_cleanup_guarded",
        "__btrc_flush_cycles_guarded",
        "__btrc_run_cleanups",
        "__btrc_try_state_cleanup",
    )
    positions = [source.index(f'order.push("{name}")') for name in ordered]

    assert positions == sorted(positions)
    thread_source = THREAD_DEPENDENCY_MIRROR.read_text()
    thread_order = ("__btrc_thread_spawn", "__btrc_thread_join")
    thread_positions = [thread_source.index(f'order.push("{name}")') for name in thread_order]
    assert thread_positions == sorted(thread_positions)
    assert source.index('order.push("__btrc_try_state_cleanup")') < source.index(
        "appendThreadRuntimeHelperOrder(order)"
    )


def test_collection_templates_guard_null_containers_and_callbacks():
    callback_helpers = {name: helper for name, helper in COLLECTIONS.items() if "(*fn)" in helper.c_source}

    assert callback_helpers
    for name, helper in callback_helpers.items():
        assert "!fn" in helper.c_source, name
        assert re.search(r"if \(![lms] \|\| !fn\)", helper.c_source), name
    assert "if (!m) return false;" in COLLECTIONS["Map_containsValue"].c_source
