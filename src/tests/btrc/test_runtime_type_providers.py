"""Self-hosted runtime type/object provider reachability contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.btrc.test_semantic_validation import _compile_source

pytest_plugins = ("src.tests.btrc.test_semantic_validation",)

REPO = Path(__file__).resolve().parents[3]
SELFHOST = REPO / "src/compiler/btrc"
COMPILERS = tuple(path for name in ("gcc", "clang") if (path := shutil.which(name)))
TYPE_CASES = (
    ("Mutex", "__btrc_mutex_val_t"),
    ("Thread", "__btrc_thread_t"),
)
EXTERN_MUTEX_SOURCE = "extern Mutex<int> acquire(); int main(){ Mutex<int> value = acquire(); return 0; }"


def _strict_compile(source: Path, output: Path, compiler: str) -> None:
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            "-c",
            str(source),
            "-o",
            str(output),
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert compiled.returncode == 0, compiled.stderr


def _strict_build_and_run(source: Path, output: Path, compiler: str) -> None:
    compiled = subprocess.run(
        [
            compiler,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pthread",
            str(source),
            "-o",
            str(output),
            "-lm",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run(
        [str(output)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert executed.returncode == 0, executed.stderr


def test_runtime_catalog_owns_generated_provider_indexes() -> None:
    catalog = (SELFHOST / "ir/runtime/catalog.btrc").read_text()
    references = (SELFHOST / "ir/runtime/references.btrc").read_text()

    assert "private Map<string, string> typeProviders;" in catalog
    assert "private Map<string, string> objectProviders;" in catalog
    assert "row.provided_types" in catalog
    assert "row.provided_objects" in catalog
    assert "helperProvidingType" in catalog
    assert "helperProvidingObject" in catalog
    assert "runtime type '%s' is provided by both" in catalog
    assert "runtime object '%s' is provided by both" in catalog

    assert "self.catalog.helperProvidingType(identifier)" in references
    assert "self.catalog.helperProvidingObject(name)" in references
    assert "node.c_type" in references
    assert "node.target_type" in references
    assert "node.kind == IRK_VAR" in references
    assert "typeUsesArcCallbackAbi" not in references
    assert 'used.put("__btrc_arc_callback_types", true)' not in references


def test_enum_value_irvar_roots_only_surviving_object_provider(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    model = json.dumps(str(SELFHOST / "ir/model.btrc"))
    generated = json.dumps(str(SELFHOST / "generated/runtime/catalog.btrc"))
    catalog = json.dumps(str(SELFHOST / "ir/runtime/catalog.btrc"))
    references = json.dumps(str(SELFHOST / "ir/runtime/references.btrc"))
    source = f"""
        import std.map;
        import std.vector;
        import {model};
        import {generated};
        import {catalog};
        import {references};

        int main() {{
            Vector<GeneratedRuntimeHelperRow> rows = [];
            Vector<string> empty = [];
            Vector<string> liveObjects = ["live_runtime_object"];
            Vector<string> deadObjects = ["dead_runtime_object"];
            rows.push(GeneratedRuntimeHelperRow(
                "test", "live_provider", empty, empty, empty,
                empty, liveObjects, false, "unknown"));
            rows.push(GeneratedRuntimeHelperRow(
                "test", "dead_provider", empty, empty, empty,
                empty, deadObjects, false, "unknown"));

            IRModule module = IRModule();
            IREnumDef live = IREnumDef("Live");
            live.values.push(IREnumValue(
                "LIVE", IRNode.variable("live_runtime_object")));
            IREnumDef dead = IREnumDef("Dead");
            dead.values.push(IREnumValue(
                "DEAD", IRNode.variable("dead_runtime_object")));
            module.enum_defs.push(live);
            module.enum_defs.push(dead);
            module.enum_defs.pop();

            RuntimeHelperCatalog providers = RuntimeHelperCatalog(rows);
            Map<string, bool> roots =
                RuntimeReferenceCollector(providers).requiredBy(module);
            if (!roots.has("live_provider")) {{ return 1; }}
            if (roots.has("dead_provider")) {{ return 2; }}
            return 0;
        }}
    """
    result, emitted = _compile_source(
        semantic_btrcc,
        tmp_path,
        source,
        no_stdlib=False,
    )
    assert result.returncode == 0, result.stderr

    for compiler in COMPILERS:
        _strict_build_and_run(
            emitted,
            tmp_path / f"enum-provider-{Path(compiler).name}",
            compiler,
        )


@pytest.mark.parametrize(("base", "c_type"), TYPE_CASES)
def test_live_type_only_sizeof_retains_catalog_provider(
    semantic_btrcc: Path,
    tmp_path: Path,
    base: str,
    c_type: str,
) -> None:
    result, generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        f"int main() {{ return (int)sizeof({base}<int>); }}",
    )
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert f"}} {c_type};" in emitted

    for compiler in COMPILERS:
        _strict_compile(
            generated,
            tmp_path / f"live-{base.lower()}-{Path(compiler).name}.o",
            compiler,
        )


@pytest.mark.parametrize(("base", "c_type"), TYPE_CASES)
def test_dead_type_only_sizeof_does_not_pin_catalog_provider(
    semantic_btrcc: Path,
    tmp_path: Path,
    base: str,
    c_type: str,
) -> None:
    result, generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        f"int dead() {{ return (int)sizeof({base}<int>); }} int main() {{ return 0; }}",
    )
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert f"}} {c_type};" not in emitted

    for compiler in COMPILERS:
        _strict_compile(
            generated,
            tmp_path / f"dead-{base.lower()}-{Path(compiler).name}.o",
            compiler,
        )


def test_live_runtime_object_reference_retains_catalog_provider(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    result, generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        EXTERN_MUTEX_SOURCE,
    )
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "static const __btrc_arc_type __btrc_mutex_arc_descriptor" in emitted
    assert "&__btrc_mutex_arc_descriptor" in emitted

    for compiler in COMPILERS:
        _strict_compile(
            generated,
            tmp_path / f"live-object-{Path(compiler).name}.o",
            compiler,
        )


def test_dead_runtime_object_reference_does_not_pin_catalog_provider(
    semantic_btrcc: Path,
    tmp_path: Path,
) -> None:
    result, generated = _compile_source(
        semantic_btrcc,
        tmp_path,
        "extern Mutex<int> acquire(); int dead(){ Mutex<int> value = acquire(); return 0; } int main(){ return 0; }",
    )
    assert result.returncode == 0, result.stderr
    emitted = generated.read_text()
    assert "static const __btrc_arc_type __btrc_mutex_arc_descriptor" not in emitted
    assert "&__btrc_mutex_arc_descriptor" not in emitted

    for compiler in COMPILERS:
        _strict_compile(
            generated,
            tmp_path / f"dead-object-{Path(compiler).name}.o",
            compiler,
        )
