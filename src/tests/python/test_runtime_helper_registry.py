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
from src.compiler.python.ir.helpers.process import PROCESS
from src.compiler.python.ir.helpers.registry import HELPERS
from src.compiler.python.ir.helpers.threads import THREADS
from src.compiler.python.ir.helpers.trycatch import TRYCATCH

AUDITED = {name: helper for name, helper in (ALLOC | DIVMOD | MATH | TRYCATCH | HASH | CYCLES | THREADS).items()}
RUNTIME_REGISTRY = Path("src/compiler/btrc/ir/runtime/registry.btrc")
CORE_CATALOG = Path("src/compiler/btrc/ir/runtime/core_catalog.btrc")
TRYCATCH_CATALOG = Path("src/compiler/btrc/ir/runtime/trycatch/catalog.btrc")
CYCLE_CATALOG = Path("src/compiler/btrc/cycle_runtime_helpers.btrc")
CYCLE_SOURCE_CATALOG = Path("src/compiler/btrc/cycle_runtime_sources.btrc")
CYCLE_DEPENDENCY_CATALOG = Path("src/compiler/btrc/cycle_runtime_dependencies.btrc")
STRING_OWNERSHIP_CATALOG = Path("src/compiler/btrc/string_runtime_helpers.btrc")
PROCESS_CATALOG = Path("src/compiler/btrc/process_runtime_helpers.btrc")
PROCESS_SOURCE_CATALOG = Path("src/compiler/btrc/process_runtime.btrc")
THREAD_CATALOG = Path("src/compiler/btrc/thread_runtime_helpers.btrc")
THREAD_SOURCE_CATALOG = Path("src/compiler/btrc/thread_runtime.btrc")
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
    Path("src/compiler/btrc/thread_runtime_mutex_arc.btrc"),
    Path("src/compiler/btrc/thread_runtime_mutex_ops.btrc"),
)
CYCLE_DEPENDENCY_MIRRORS = (
    Path("src/compiler/btrc/cycle_runtime_dependencies_state.btrc"),
    Path("src/compiler/btrc/cycle_runtime_dependencies_lifecycle.btrc"),
)
THREAD_DEPENDENCY_MIRROR = Path("src/compiler/btrc/thread_runtime_helpers.btrc")

_BRANCH_START_PATTERN = re.compile(
    r"^[ \t]+(?:\} )?(?:else )?if \((.*?)\) \{",
    re.MULTILINE | re.DOTALL,
)


def _catalog_emission_order(path: Path) -> list[str]:
    source = path.read_text().split("self.emissionOrder = [", 1)[1].split("];", 1)[0]
    return re.findall(r'"([^"]+)"', source)


def _method_push_order(path: Path, method: str, next_method: str | None = None) -> list[str]:
    source = path.read_text().split(f"public void {method}", 1)[1]
    if next_method is not None:
        source = source.split(f"public void {next_method}", 1)[0]
    return re.findall(r'order\.push\("([^"]+)"\)', source)


def _self_hosted_canonical_order() -> list[str]:
    expansions = {
        "core.appendFoundationOrder": _method_push_order(
            CORE_CATALOG, "appendFoundationOrder", "appendStringAndMathOrder"
        ),
        "stringOwnership.appendOrder": _catalog_emission_order(STRING_OWNERSHIP_CATALOG),
        "core.appendStringAndMathOrder": _method_push_order(
            CORE_CATALOG, "appendStringAndMathOrder", "appendHashOrder"
        ),
        "tryCatch.appendPreludeOrder": _method_push_order(
            TRYCATCH_CATALOG, "appendPreludeOrder", "appendCleanupOrder"
        ),
        "core.appendHashOrder": _method_push_order(CORE_CATALOG, "appendHashOrder"),
        "cycles.appendOrder": _catalog_emission_order(CYCLE_CATALOG),
        "tryCatch.appendCleanupOrder": _method_push_order(TRYCATCH_CATALOG, "appendCleanupOrder"),
        "process.appendOrder": _catalog_emission_order(PROCESS_CATALOG),
        "threads.appendOrder": _catalog_emission_order(THREAD_CATALOG),
    }
    source = RUNTIME_REGISTRY.read_text().split("private Vector<string> buildCanonicalOrder", 1)[1]
    pattern = re.compile(
        r'order\.push\("([^"]+)"\)|self\.([A-Za-z]+\.append(?:[A-Za-z]+)?Order)\(order\)'
    )
    order: list[str] = []
    for match in pattern.finditer(source):
        if match.group(1) is not None:
            order.append(match.group(1))
        else:
            order.extend(expansions[match.group(2)])
    return order


def _self_hosted_sources(source: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    pattern = re.compile(
        r'^([ \t]+)if \(name == "([^"]+)"\) \{\n(.*?)^\1\}',
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(source):
        literals = re.findall(r'"(?:\\.|[^"\\])*"', match.group(3))
        blocks[match.group(2)] = "".join(ast.literal_eval(item) for item in literals)
    return blocks


def _mirrored_sources() -> dict[str, str]:
    mirrored = _self_hosted_sources(CORE_CATALOG.read_text())
    for path in (*CYCLE_SOURCE_MIRRORS, *THREAD_SOURCE_MIRRORS):
        mirrored.update(_self_hosted_sources(path.read_text()))
    catalog = TRYCATCH_CATALOG.read_text()
    pattern = re.compile(
        r'^        self\.sources\.put\("([^"]+)",\n(.*?)'
        r"(?=^        self\.sources\.put\(|^    \})",
        re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(catalog):
        literals = re.findall(r'"(?:\\.|[^"\\])*"', match.group(2))
        mirrored[match.group(1)] = "".join(ast.literal_eval(item) for item in literals)
    return mirrored


def _named_branch_values(source: str, value_pattern: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    matches = list(_BRANCH_START_PATTERN.finditer(source))
    for index, match in enumerate(matches):
        condition = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(source)
        body = source[match.end() : end]
        names = re.findall(r'name == "([^"]+)"', condition)
        branch_values = re.findall(value_pattern, body)
        for name in names:
            values[name] = branch_values
    return values


def _runtime_metadata_maps() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    core = CORE_CATALOG.read_text()
    trycatch = TRYCATCH_CATALOG.read_text()
    process = PROCESS_CATALOG.read_text()
    threads = THREAD_CATALOG.read_text()
    cycle_dependencies = "\n".join(path.read_text() for path in CYCLE_DEPENDENCY_MIRRORS)

    dependency_sources = (
        core.split("public Vector<string> dependencies", 1)[1],
        trycatch.split("public Vector<string> dependencies", 1)[1].split(
            "public Vector<string> headers", 1
        )[0],
        cycle_dependencies,
        process.split("public Vector<string> dependencies", 1)[1].split(
            "public Vector<string> headers", 1
        )[0],
        threads.split("public Vector<string> dependencies", 1)[1].split(
            "public Vector<string> headers", 1
        )[0],
    )
    header_sources = (
        trycatch.split("public Vector<string> headers", 1)[1].split(
            "public void appendPreludeOrder", 1
        )[0],
        CYCLE_CATALOG.read_text().split("public Vector<string> headers", 1)[1].split(
            "public void appendOrder", 1
        )[0],
        process.split("public Vector<string> headers", 1)[1].split(
            "public void appendOrder", 1
        )[0],
        threads.split("public Vector<string> headers", 1)[1].split(
            "public void appendOrder", 1
        )[0],
    )

    dependencies: dict[str, list[str]] = {}
    for source in dependency_sources:
        dependencies.update(_named_branch_values(source, r'out\.push\("([^"]+)"\)'))
    headers: dict[str, list[str]] = {}
    for source in header_sources:
        headers.update(_named_branch_values(source, r'out\.push\("([^"]+)"\)'))
    return dependencies, headers


def test_self_hosted_non_string_sources_exactly_match_python_registry():
    mirrored = _mirrored_sources()

    assert set(AUDITED) <= set(mirrored)
    for name, helper in AUDITED.items():
        assert mirrored[name] == helper.c_source, name


def test_self_hosted_non_string_metadata_exactly_matches_python_registry():
    dependencies, headers = _runtime_metadata_maps()

    for name, helper in (AUDITED | PROCESS).items():
        assert dependencies.get(name, []) == helper.depends_on, name
        assert headers.get(name, []) == helper.required_headers, name


def test_runtime_helpers_do_not_aggregate_initialize_local_error_buffers():
    initializer = re.compile(r'(?m)^\s+char\s+\w*error\w*\[[^]]+\]\s*=\s*"";')
    offenders = {
        name
        for category in HELPERS.values()
        for name, helper in category.items()
        if initializer.search(helper.c_source)
    }

    # Freestanding compilers may lower a large local aggregate initializer to
    # a libc bzero/memset call even under -fno-builtin.  Initialize only the
    # sentinel byte at each call site instead.
    assert not offenders


def test_runtime_family_catalogs_are_instance_owned_by_registry():
    catalog = TRYCATCH_CATALOG.read_text()
    registry = RUNTIME_REGISTRY.read_text()

    assert "class TryCatchRuntimeCatalog" in catalog
    assert "private Map<string, string> sources;" in catalog
    assert "private CoreRuntimeCatalog core;" in registry
    assert "private CycleRuntimeSourceCatalog cycleSources;" in registry
    assert "private CycleRuntimeDependencyCatalog cycleDependencies;" in registry
    assert "private CycleRuntimeCatalog cycles;" in registry
    assert "private StringOwnershipRuntimeCatalog stringOwnership;" in registry
    assert "private TryCatchRuntimeCatalog tryCatch;" in registry
    assert "private ProcessRuntimeSourceCatalog processSources;" in registry
    assert "private ProcessRuntimeCatalog process;" in registry
    assert "private ThreadRuntimeSourceCatalog threadSources;" in registry
    assert "private ThreadRuntimeCatalog threads;" in registry
    assert "self.core = CoreRuntimeCatalog();" in registry
    assert "self.cycleSources = CycleRuntimeSourceCatalog();" in registry
    assert "self.cycleDependencies = CycleRuntimeDependencyCatalog();" in registry
    assert "self.cycleSources, self.cycleDependencies" in registry
    assert "self.tryCatch = TryCatchRuntimeCatalog();" in registry
    assert "self.processSources = ProcessRuntimeSourceCatalog();" in registry
    assert "self.process = ProcessRuntimeCatalog(self.processSources);" in registry
    assert "self.threadSources = ThreadRuntimeSourceCatalog();" in registry
    assert "self.threads = ThreadRuntimeCatalog(self.threadSources);" in registry
    for path, class_name in (
        (CYCLE_CATALOG, "CycleRuntimeCatalog"),
        (STRING_OWNERSHIP_CATALOG, "StringOwnershipRuntimeCatalog"),
        (PROCESS_CATALOG, "ProcessRuntimeCatalog"),
        (THREAD_CATALOG, "ThreadRuntimeCatalog"),
    ):
        source = path.read_text()
        assert f"class {class_name}" in source
        assert "private Map<string, bool> members;" in source
        for legacy in (
            "RuntimeHasHelper",
            "RuntimeHelperSource",
            "RuntimeHelperDependencies",
            "RuntimeHelperHeaders",
            "RuntimeHelperOrder",
        ):
            assert legacy not in source
    cycle_catalog = CYCLE_CATALOG.read_text()
    dependencies = CYCLE_DEPENDENCY_CATALOG.read_text()
    assert "private CycleRuntimeDependencyCatalog dependencyCatalog;" in cycle_catalog
    assert "class CycleRuntimeDependencyCatalog" in dependencies
    assert "public Vector<string> dependencies(string name)" in dependencies
    assert "self.dependencyCatalog.dependencies(name)" in cycle_catalog
    for path in CYCLE_DEPENDENCY_MIRRORS:
        source = path.read_text()
        assert len(re.findall(r"(?m)^    public Vector<string> [A-Za-z]", source)) == 1
        assert "cycleRuntimeStateDependencies" not in source
        assert "cycleRuntimeLifecycleDependencies" not in source
    assert "trycatchRuntime" not in catalog + registry


def test_runtime_source_shards_are_methods_on_owned_family_catalogs():
    catalog_contracts = (
        (
            CYCLE_SOURCE_CATALOG,
            "CycleRuntimeSourceCatalog",
            CYCLE_SOURCE_MIRRORS,
            13,
        ),
        (
            PROCESS_SOURCE_CATALOG,
            "ProcessRuntimeSourceCatalog",
            (
                Path("src/compiler/btrc/process_runtime_close.btrc"),
                Path("src/compiler/btrc/process_runtime_descriptor.btrc"),
                Path("src/compiler/btrc/process_runtime_spawn.btrc"),
            ),
            3,
        ),
        (
            THREAD_SOURCE_CATALOG,
            "ThreadRuntimeSourceCatalog",
            THREAD_SOURCE_MIRRORS,
            4,
        ),
    )

    for catalog_path, class_name, shards, method_count in catalog_contracts:
        catalog = catalog_path.read_text()
        assert f"class {class_name}" in catalog
        assert sum(f'#include "{path.name}"' in catalog for path in shards) == method_count
        methods = 0
        for path in shards:
            source = path.read_text()
            assert not re.search(r"(?m)^string [A-Za-z]", source)
            methods += len(re.findall(r"(?m)^    public string [A-Za-z]", source))
        assert methods == method_count

    cycles = CYCLE_CATALOG.read_text()
    process = PROCESS_CATALOG.read_text()
    threads = THREAD_CATALOG.read_text()
    assert "private CycleRuntimeSourceCatalog sources;" in cycles
    assert "CycleRuntimeSourceCatalog sources," in cycles
    assert "CycleRuntimeDependencyCatalog dependencyCatalog)" in cycles
    assert "private ProcessRuntimeSourceCatalog sources;" in process
    assert "ProcessRuntimeCatalog(ProcessRuntimeSourceCatalog sources)" in process
    assert "private ThreadRuntimeSourceCatalog sources;" in threads
    assert "ThreadRuntimeCatalog(ThreadRuntimeSourceCatalog sources)" in threads


def test_runtime_membership_headers_and_order_have_one_owner():
    registry = RUNTIME_REGISTRY.read_text()
    nodes = Path("src/compiler/btrc/ir_nodes.btrc").read_text()
    generator = Path("src/compiler/btrc/irgen.btrc").read_text()
    collector = Path("src/compiler/btrc/ir/runtime/reference_collector.btrc").read_text()

    assert "private Vector<string> canonicalOrder;" in registry
    assert "private Map<string, bool> members;" in registry
    assert "public bool has(string name)" in registry
    assert "public Vector<string> headers(string name)" in registry
    assert "public Vector<string> order()" in registry
    assert 'order.push("__btrc_' not in registry
    assert "canonicalHelperOrder" not in nodes + generator
    assert "helperHeaders" not in nodes + generator
    assert "self.runtimeHelpers.order()" in generator
    assert "self.runtimeHelpers.headers(" in generator
    assert "self.helpers.has(node.callee)" in collector
    assert "self.helpers.has(node.name)" in collector
    assert "self.helpers.source(" not in collector


def test_split_runtime_families_have_no_legacy_helper_branches():
    source = CORE_CATALOG.read_text()
    helper_sources = source[source.index("public string source") : source.index("public Vector<string> dependencies")]
    helper_dependencies = source[source.index("public Vector<string> dependencies") :]

    for name in set(CYCLES) | set(TRYCATCH) | set(THREADS):
        marker = f'if (name == "{name}")'
        assert marker not in helper_sources, name
        assert marker not in helper_dependencies, name


def test_self_hosted_dependency_edges_cover_checked_runtime_roots():
    source = CORE_CATALOG.read_text()
    cycle_source = "\n".join(path.read_text() for path in CYCLE_DEPENDENCY_MIRRORS)
    trycatch_source = TRYCATCH_CATALOG.read_text()
    thread_source = THREAD_DEPENDENCY_MIRROR.read_text()
    required_edges = {
        "__btrc_math_lcm": "__btrc_math_gcd",
        "__btrc_push_try": "__btrc_safe_realloc",
        "__btrc_register_cleanup_kind": "__btrc_safe_realloc",
        "__btrc_register_cleanup": "__btrc_register_cleanup_kind",
        "__btrc_register_direct_cleanup": "__btrc_register_cleanup_kind",
        "__btrc_arc_guard_hook": "__btrc_copy_error_message",
        "__btrc_run_cleanup_guarded": "__btrc_arc_release",
        "__btrc_flush_cycles_guarded": "__btrc_flush_cycles",
        "__btrc_run_cleanups": "__btrc_is_destroyed",
        "__btrc_throw": "__btrc_copy_error_message",
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
            dependency_source = thread_source[thread_source.index("public Vector<string> dependencies") :]
        else:
            dependency_source = source[source.index("public Vector<string> dependencies") :]
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


def test_self_hosted_order_is_complete_unique_and_dependency_topological():
    actual = _self_hosted_canonical_order()
    expected = [
        name
        for category, helpers in HELPERS.items()
        if category not in {"gpu", "collections"}
        for name in helpers
    ]

    assert len(actual) == len(set(actual))
    assert set(actual) == set(expected)
    positions = {name: index for index, name in enumerate(actual)}
    for category, helpers in HELPERS.items():
        if category in {"gpu", "collections"}:
            continue
        for name, helper in helpers.items():
            for dependency in helper.depends_on:
                assert positions[dependency] < positions[name], (name, dependency)


def test_collection_templates_guard_null_containers_and_callbacks():
    callback_helpers = {name: helper for name, helper in COLLECTIONS.items() if "(*fn)" in helper.c_source}

    assert callback_helpers
    for name, helper in callback_helpers.items():
        assert "!fn" in helper.c_source, name
        assert re.search(r"if \(![lms] \|\| !fn\)", helper.c_source), name
    assert "if (!m) return false;" in COLLECTIONS["Map_containsValue"].c_source
