"""Contracts for the generated, shared runtime-helper specification."""

import ast
import shutil
from pathlib import Path

import pytest

from src.compiler.python.runtime.catalog import RuntimeHelperCatalog, RuntimeHelperSelection
from src.compiler.python.runtime.generated import INTRINSIC_EFFECT_ROWS, RUNTIME_HELPER_ROWS
from tools.compiler_codegen.intrinsic_effects import IntrinsicEffectManifest, IntrinsicEffectManifestError
from tools.compiler_codegen.runtime import RuntimeCatalogGenerator, RuntimeManifest, RuntimeManifestError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = REPOSITORY_ROOT / "src/runtime/c"
MANIFEST_PATH = RUNTIME_ROOT / "manifest.toml"
INTRINSIC_EFFECTS_PATH = REPOSITORY_ROOT / "src/language/intrinsic_effects.toml"
GENERATED_PYTHON = REPOSITORY_ROOT / "src/compiler/python/runtime/generated.py"
GENERATED_BTRC = REPOSITORY_ROOT / "src/compiler/btrc/generated/runtime/catalog.btrc"
BTRC_CATALOG = REPOSITORY_ROOT / "src/compiler/btrc/ir/runtime/catalog.btrc"
BTRC_REFERENCES = REPOSITORY_ROOT / "src/compiler/btrc/ir/runtime/references.btrc"


def test_generated_python_catalog_exactly_matches_the_shared_manifest() -> None:
    manifest = RuntimeManifest.load(MANIFEST_PATH)
    expected = manifest.helpers_for("python")

    assert len(RUNTIME_HELPER_ROWS) == len(expected)
    for row, helper in zip(RUNTIME_HELPER_ROWS, expected, strict=True):
        assert row.category == helper.category
        assert row.name == helper.name
        assert row.c_source == helper.source
        assert row.depends_on == helper.dependencies
        assert row.required_headers == helper.headers
        assert row.provided_types == helper.provided_types
        assert row.provided_objects == helper.provided_objects
        assert row.source_visible is helper.source_visible


def test_generated_catalog_artifacts_are_fresh() -> None:
    manifest = RuntimeManifest.load(MANIFEST_PATH)
    intrinsic_effects = IntrinsicEffectManifest.load(INTRINSIC_EFFECTS_PATH)
    artifacts = RuntimeCatalogGenerator(manifest, intrinsic_effects).artifacts()

    assert {artifact.path.as_posix() for artifact in artifacts} == {
        "src/compiler/python/runtime/generated.py",
        "src/compiler/btrc/generated/runtime/catalog.btrc",
    }
    for artifact in artifacts:
        assert REPOSITORY_ROOT.joinpath(*artifact.path.parts).read_bytes() == artifact.content


def test_generated_intrinsic_effects_exactly_match_the_canonical_specification() -> None:
    manifest = IntrinsicEffectManifest.load(INTRINSIC_EFFECTS_PATH)

    assert len(INTRINSIC_EFFECT_ROWS) == len(manifest.methods)
    for row, method in zip(INTRINSIC_EFFECT_ROWS, manifest.methods, strict=True):
        assert row.receiver == method.receiver
        assert row.method == method.method
        assert row.realtime_effect == method.realtime_effect
        assert row.c_callee == method.c_callee
        assert row.provenance == method.provenance

    catalog = RuntimeHelperCatalog()
    assert catalog.intrinsic_realtime_effect("Atomic", "load") == "safe"
    assert catalog.intrinsic_realtime_effect("Atomic", "init") == "unknown"
    assert catalog.intrinsic_realtime_effect("Atomic", "invented") == "unknown"
    assert catalog.realtime_intrinsic_targets["atomic_load_explicit"] == "Atomic.load"


@pytest.mark.parametrize(
    ("document", "diagnostic"),
    (
        (
            'schema_version = 2\n[[methods]]\nreceiver = "Atomic"\nmethod = "load"\nrealtime_effect = "safe"\n',
            "unsupported intrinsic effect schema version",
        ),
        (
            'schema_version = 1\nunexpected = true\n[[methods]]\nreceiver = "Atomic"\n'
            'method = "load"\nrealtime_effect = "safe"\n',
            "unknown intrinsic effect manifest keys",
        ),
        (
            'schema_version = 1\n[[methods]]\nreceiver = "Span"\nmethod = "length"\n'
            'realtime_effect = "safe"\n[[methods]]\nreceiver = "Atomic"\nmethod = "load"\n'
            'realtime_effect = "safe"\n',
            "methods must be sorted by receiver and method",
        ),
        (
            'schema_version = 1\n[[methods]]\nreceiver = "Atomic"\nmethod = "load"\n'
            'realtime_effect = "safe"\n[[methods]]\nreceiver = "Atomic"\nmethod = "load"\n'
            'realtime_effect = "safe"\n',
            "methods must not contain duplicate receiver/method pairs",
        ),
        (
            'schema_version = 1\n[[methods]]\nreceiver = "Atomic"\nmethod = "load"\nrealtime_effect = "sometimes"\n',
            "realtime_effect is invalid",
        ),
        (
            'schema_version = 1\n[[methods]]\nreceiver = "Atomic"\nmethod = "load"\n'
            'realtime_effect = "safe"\nc_callee = "not-a-c-name"\n',
            "c_callee must be a C identifier",
        ),
    ),
    ids=("schema", "unknown-key", "order", "duplicate", "effect", "c-callee"),
)
def test_intrinsic_effect_manifest_rejects_malformed_input(
    tmp_path: Path,
    document: str,
    diagnostic: str,
) -> None:
    manifest = tmp_path / "intrinsic-effects.toml"
    manifest.write_text(document)

    with pytest.raises(IntrinsicEffectManifestError, match=diagnostic):
        IntrinsicEffectManifest.load(manifest)


def test_runtime_assets_are_cohesive_domains_with_no_behavior_outside_markers() -> None:
    manifest = RuntimeManifest.load(MANIFEST_PATH)
    assert {helper.asset for helper in manifest.helpers} == {
        "core.c",
        "collections.c",
        "cycles.c",
        "gpu.c",
        "mutex.c",
        "process.c",
        "strings.c",
        "threads.c",
        "trycatch.c",
    }


def test_runtime_helpers_do_not_aggregate_initialize_local_error_buffers() -> None:
    offenders = {row.name for row in RUNTIME_HELPER_ROWS if "char error[" in row.c_source and '= "";' in row.c_source}

    # A freestanding compiler may lower a large local aggregate initializer to
    # a libc memset call. Runtime helpers initialize only the sentinel byte.
    assert not offenders


def test_manifest_dependencies_are_known_and_catalog_complete() -> None:
    manifest = RuntimeManifest.load(MANIFEST_PATH)
    known = {helper.name for helper in manifest.helpers}

    assert len(known) == len(manifest.helpers)
    for helper in manifest.helpers:
        assert set(helper.dependencies) <= known, helper.name

    python_names = {helper.name for helper in manifest.helpers_for("python")}
    btrc_names = {helper.name for helper in manifest.helpers_for("btrc")}
    assert btrc_names <= python_names
    assert python_names - btrc_names == {
        helper.name for helper in manifest.helpers if helper.category in {"collections", "gpu"}
    }


def test_manifest_rejects_an_undeclared_helper_source_reference(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    shutil.copytree(RUNTIME_ROOT, runtime_root)
    manifest_path = runtime_root / "manifest.toml"
    source = manifest_path.read_text()
    with_dependency = '''name = "__btrc_arc_retain_edge"
category = "cycles"
asset = "cycles.c"
dependencies = [
  "__btrc_arc_register_incoming",
  "__btrc_arc_validate",
  "__btrc_arc_mutation_lock",'''
    without_dependency = with_dependency.replace('  "__btrc_arc_validate",\n', "")
    assert source.count(with_dependency) == 1
    manifest_path.write_text(source.replace(with_dependency, without_dependency, 1))

    with pytest.raises(
        RuntimeManifestError,
        match=(
            "helper __btrc_arc_retain_edge source references helpers outside "
            "its declared dependency closure: __btrc_arc_validate"
        ),
    ):
        RuntimeManifest.load(manifest_path)


def test_manifest_rejects_an_unreachable_provided_type(tmp_path: Path) -> None:
    runtime_root = tmp_path / "runtime"
    shutil.copytree(RUNTIME_ROOT, runtime_root)
    manifest_path = runtime_root / "manifest.toml"
    source = manifest_path.read_text()
    with_dependency = '''name = "__btrc_cycle_collector_state"
category = "cycles"
asset = "cycles.c"
dependencies = ["__btrc_arc_callback_types"]'''
    without_dependency = with_dependency.replace(
        'dependencies = ["__btrc_arc_callback_types"]',
        "dependencies = []",
    )
    assert source.count(with_dependency) == 1
    manifest_path.write_text(source.replace(with_dependency, without_dependency, 1))

    with pytest.raises(
        RuntimeManifestError,
        match=(
            "helper __btrc_cycle_collector_state source references helpers outside "
            "its declared dependency closure: __btrc_arc_callback_types"
        ),
    ):
        RuntimeManifest.load(manifest_path)


def test_btrc_catalog_order_is_unique_and_dependency_topological() -> None:
    helpers = RuntimeManifest.load(MANIFEST_PATH).helpers_for("btrc")
    positions = {helper.name: index for index, helper in enumerate(helpers)}

    assert len(positions) == len(helpers)
    for helper in helpers:
        for dependency in helper.dependencies:
            assert positions[dependency] < positions[helper.name], (helper.name, dependency)


def test_required_runtime_dependency_edges_live_in_the_manifest() -> None:
    rows = {row.name: row for row in RUNTIME_HELPER_ROWS}
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
        assert dependency in rows[helper].depends_on, helper
    assert "__btrc_arc_topology_depth_state" in rows["__btrc_arc_topology_begin"].depends_on


def test_python_selection_owns_dependency_closure() -> None:
    catalog = RuntimeHelperCatalog()
    throw_helpers = {row.name for row in catalog.definitions_for({"__btrc_throw"})}
    push_helpers = {row.name for row in catalog.definitions_for({"__btrc_push_try"})}

    assert "__btrc_trycatch_globals" in throw_helpers
    assert "__btrc_push_try" in throw_helpers
    assert "__btrc_try_capacity" in throw_helpers
    assert "__btrc_try_capacity" in push_helpers


def test_runtime_helper_selection_is_isolated_validated_run_state() -> None:
    first = RuntimeHelperSelection()
    second = RuntimeHelperSelection()

    first.use("__btrc_throw")

    assert first.roots == frozenset({"__btrc_throw"})
    assert second.roots == frozenset()
    assert "__btrc_trycatch_globals" in {row.name for row in first.definitions()}
    assert first.uses_any({"__btrc_throw", "__btrc_push_try"})
    assert not second.uses_any({"__btrc_throw"})


def test_topology_cleanup_closure_omits_unused_abandon_queue_storage() -> None:
    helpers = {row.name for row in RuntimeHelperCatalog().definitions_for({"__btrc_arc_topology_cleanup"})}

    assert "__btrc_arc_abandon_queue_drain" in helpers
    assert "__btrc_arc_abandon_callback_state" in helpers
    assert "__btrc_arc_abandon_queue_state" not in helpers


def test_cleanup_setjmp_is_confined_to_non_inline_guards() -> None:
    rows = {row.name: row for row in RUNTIME_HELPER_ROWS}
    cleanup_guard = rows["__btrc_run_cleanup_guarded"]
    flush_guard = rows["__btrc_flush_cycles_guarded"]
    run_cleanups = rows["__btrc_run_cleanups"]

    assert cleanup_guard.c_source.startswith("static void __btrc_run_cleanup_guarded(")
    assert flush_guard.c_source.startswith("static void __btrc_flush_cycles_guarded(")
    assert cleanup_guard.c_source.count("setjmp(") == 1
    assert flush_guard.c_source.count("setjmp(") == 1
    assert "setjmp(" not in run_cleanups.c_source
    assert "__btrc_run_cleanup_guarded(entry, object);" in run_cleanups.c_source
    assert "__btrc_flush_cycles_guarded();" in run_cleanups.c_source
    assert "__btrc_run_cleanup_guarded" in run_cleanups.depends_on
    assert "__btrc_flush_cycles_guarded" in run_cleanups.depends_on


def test_generic_intrinsics_are_not_runtime_macro_helpers() -> None:
    hash_helpers = {row.name for row in RUNTIME_HELPER_ROWS if row.category == "hash"}

    assert hash_helpers == {"__btrc_hash_real", "__btrc_hash_str"}
    for obsolete in ("__btrc_eq", "__btrc_lt", "__btrc_gt", "__btrc_hash"):
        assert obsolete not in hash_helpers


def test_collection_templates_guard_null_containers_and_callbacks() -> None:
    callbacks = {
        row.name: row.c_source
        for row in RUNTIME_HELPER_ROWS
        if row.category == "collections" and "(*fn)" in row.c_source
    }

    assert callbacks
    for name, source in callbacks.items():
        assert "!fn" in source, name
        assert any(f"if (!{container} || !fn)" in source for container in "lms"), name
    rows = {row.name: row for row in RUNTIME_HELPER_ROWS}
    assert "if (!m) return false;" in rows["Map_containsValue"].c_source


def test_selfhost_runtime_behavior_has_one_catalog_and_one_reference_owner() -> None:
    catalog = BTRC_CATALOG.read_text()
    references = BTRC_REFERENCES.read_text()
    generated = GENERATED_BTRC.read_text()

    assert "class RuntimeHelperCatalog" in catalog
    assert "private Vector<GeneratedRuntimeHelperRow> rows;" in catalog
    assert "private Map<string, int> indices;" in catalog
    assert "private Map<string, string> materializedSources;" in catalog
    assert "public Vector<string> selectedInCanonicalOrder(" in catalog
    assert "class RuntimeReferenceCollector" in references
    assert "private RuntimeHelperCatalog catalog;" in references
    assert "class GeneratedRuntimeCatalogData" in generated
    assert "class GeneratedRuntimeHelperRow" in generated
    assert "#include" not in catalog


def test_legacy_runtime_catalogs_and_source_shards_are_deleted() -> None:
    compiler_root = REPOSITORY_ROOT / "src/compiler/btrc"
    forbidden = (
        "CoreRuntimeCatalog",
        "CycleRuntimeSourceCatalog",
        "CycleRuntimeDependencyCatalog",
        "StringOwnershipRuntimeCatalog",
        "TryCatchRuntimeCatalog",
        "ProcessRuntimeSourceCatalog",
        "ProcessRuntimeCatalog",
        "ThreadRuntimeSourceCatalog",
        "ThreadRuntimeCatalog",
    )
    production = "\n".join(path.read_text() for path in compiler_root.rglob("*.btrc"))

    for class_name in forbidden:
        assert f"class {class_name}" not in production
    assert not list(compiler_root.glob("cycle_runtime_*.btrc"))
    assert not list(compiler_root.glob("thread_runtime_*.btrc"))
    assert not list(compiler_root.glob("process_runtime_*.btrc"))
    assert not list(compiler_root.glob("string_runtime_*.btrc"))
    for deleted in (
        "ir/runtime/core_catalog.btrc",
        "ir/runtime/trycatch/catalog.btrc",
        "ir/helpers",
    ):
        assert not (compiler_root / deleted).exists()


def test_generated_catalogs_are_data_only() -> None:
    python_source = GENERATED_PYTHON.read_text()
    btrc_source = GENERATED_BTRC.read_text()
    python_module = ast.parse(python_source)

    assert not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in python_module.body)
    assert "GeneratedRuntimeHelperRow(" in python_source
    assert "class GeneratedRuntimeCatalogData" in btrc_source
    assert "public bool has(" not in btrc_source
    assert "public string source(" not in btrc_source
