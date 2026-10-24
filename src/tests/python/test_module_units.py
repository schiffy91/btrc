"""Module units: one C unit per compilation group, reused by key across builds."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import weakref
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ForkedModuleUnitWorkers, ModuleUnitCompiler, ModuleUnitRecord
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.frontend.native_imports import NativeGeneratedSource, NativeHeaderSource
from src.compiler.python.frontend.sources import CompilationGroups, SourceDependencyGraph
from src.compiler.python.ir.lowering.exceptions import (
    ExceptionLowerer,
    FunctionEffect,
    ParameterEffect,
    SetjmpUnitSolver,
)
from src.compiler.python.ir.nodes import (
    CType,
    IRBlock,
    IRCall,
    IRExprStmt,
    IRFunctionDecl,
    IRFunctionDef,
    IRModule,
    IRParam,
    IRVar,
    IRVarDecl,
)
from src.tests import runner
from src.tests.btrc.runtime_ownership_harness import require_sanitizers, sanitizer_environment
from src.tests.c_toolchains import HOST_C_COMPILERS, HOST_CLANG, host_c_compiler
from src.tests.native_bindings import NativeBindingPackage
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.core_audio_fixtures import fault_package
from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_project as native_project
from src.tests.python.pugixml_fixtures import pugixml_project as pugixml_project
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "modules"
C_COMPILER = host_c_compiler()


def test_groups_merge_import_cycles_and_reciprocal_includes(tmp_path):
    files = {name: str(tmp_path / f"{name}.btrc") for name in ("main", "a", "b", "c", "d", "leaf")}
    for path in files.values():
        Path(path).write_text("")
    graph = SourceDependencyGraph()
    graph.add_import(files["main"], files["a"])
    graph.add_import(files["a"], files["b"])
    graph.add_import(files["b"], files["a"])
    graph.add_import(files["main"], files["c"])
    graph.add_include(files["c"], files["d"])
    graph.add_import(files["d"], files["leaf"])
    groups = graph.compilation_groups(files["main"])
    canonical = {name: SourceDependencyGraph.canonical_file(path) for name, path in files.items()}
    members = [set(group) for group in groups.groups]
    assert {canonical["a"], canonical["b"]} in members
    assert {canonical["c"], canonical["d"]} in members
    order = {member: position for position, group in enumerate(groups.groups) for member in group}
    assert order[canonical["leaf"]] < order[canonical["c"]] < order[canonical["main"]]
    assert order[canonical["a"]] < order[canonical["main"]]
    assert groups.group_of(files["b"]) == groups.group_of(files["a"])
    assert groups.group_of(None) == CompilationGroups.PROGRAM
    assert groups.group_of("<stdlib>") == CompilationGroups.PROGRAM


def test_native_declarations_belong_to_the_program_unit(tmp_path):
    """What the native importer declares has no line in its binding's module.

    Native-header declarations and the classes the importer writes compare
    and hash equal to their binding module's path, but the program unit owns
    them: it alone carries the Objective-C and C++ adapter units into the link
    plan. The module's own declarations stay with its group, before and after.
    """
    module = tmp_path / "Bindings.btrc"
    module.write_text("")
    canonical = SourceDependencyGraph.canonical_file(str(module))
    groups = CompilationGroups(((canonical,),))
    # Resolve the plain path first, so a native stamp would hit its memo entry.
    assert groups.group_of(str(module)) == canonical
    header = NativeHeaderSource(str(module), "Bindings.h", language="objective-c")
    for stamp in (header, NativeGeneratedSource(header), NativeGeneratedSource(str(module))):
        assert stamp == str(module) and hash(stamp) == hash(str(module))
        assert groups.group_of(stamp) == CompilationGroups.PROGRAM
    assert groups.group_of(str(module)) == canonical


def test_record_round_trips_and_rejects_malformed_payloads():
    effect = FunctionEffect(
        writes=frozenset({ParameterEffect(0), ParameterEffect(1, 2)}),
        captures=frozenset({ParameterEffect(1)}),
        unknown_return=True,
    )
    record = ModuleUnitRecord(
        group="/g",
        text="int x;\n",
        kept=True,
        exports=("f", "g"),
        has_setjmp=True,
        effects_solved=True,
        exported_effects={"f": effect},
        consulted_effects={"h": FunctionEffect()},
        releases_cyclable=False,
        defines_entry=True,
        program_release=True,
        helpers=("__btrc_arc_release",),
        realtime_roots=("f",),
        realtime_proofs={"f": ("g", "h"), "g": ()},
    )
    assert ModuleUnitRecord.from_json(record.to_json(), "/g") == record
    assert ModuleUnitRecord.from_json(record.to_json(), "/elsewhere") is None
    assert ModuleUnitRecord.from_json(record.to_json()[:-1], "/g") is None
    assert ModuleUnitRecord.from_json(record.to_json().replace('"kept":true', '"kept":1'), "/g") is None


def test_unit_names_are_stable_and_distinct():
    first = ModuleUnitCompiler.unit_name("/work/app/Shapes/Shapes.btrc")
    assert first == ModuleUnitCompiler.unit_name("/work/app/Shapes/Shapes.btrc")
    assert first.startswith("unit-Shapes-")
    assert first != ModuleUnitCompiler.unit_name("/work/lib/Shapes/Shapes.btrc")


class _Workspace:
    """A private copy of the M11a fixture compiled through the public API."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.modules = root / "modules"
        shutil.copytree(FIXTURE, self.modules)
        self.cache = root / "cache"

    def edit(self, relative: str, old: str, new: str) -> None:
        path = self.modules / relative
        text = path.read_text()
        assert old in text
        path.write_text(text.replace(old, new))

    def build(self, entry: str, output: Path, monkeypatch, *, stdlib_strict=False):
        monkeypatch.setenv("BTRC_CACHE_DIR", str(self.cache))
        output.mkdir(parents=True, exist_ok=True)
        path = self.modules / entry
        result = Compiler(cache=CompilerCache()).compile(
            path.read_text(),
            str(path),
            CompilerOptions(
                units_prefix=str(output / "program"),
                module_units=True,
                stdlib_strict=stdlib_strict,
                generated_c_path=str(output / "program.c"),
            ),
        )
        assert result.failure is None, result.failure
        units = dict(zip(result.unit_names, result.c_units, strict=True))
        return result, units

    def run(self, result, output: Path) -> str:
        if C_COMPILER is None:
            pytest.skip("module-unit execution needs a C compiler")
        sources = [output / "program.c"]
        sources[0].write_text(result.c_source)
        for name, text in zip(result.unit_names, result.c_units, strict=True):
            sources.append(output / f"program.{name}.c")
            sources[-1].write_text(text)
        executable = output / "program"
        subprocess.run(
            [
                *C_COMPILER,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{self.modules / 'Shapes'}",
                *map(str, sources),
                "-o",
                str(executable),
                "-lm",
                "-lpthread",
            ],
            check=True,
            capture_output=True,
            timeout=180,
        )
        return subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=30).stdout


def _names(groups) -> set[str]:
    return {os.path.basename(group) for group in groups}


_SESSION_NAME = re.compile(r"\b(?:__[A-Za-z]\w*?\d+\w*|[A-Za-z]\w*_\d+)\b")
_FUNCTION_HEADER = re.compile(r"^[A-Za-z_][\w\s*]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{$")


def _function_bodies(texts) -> dict[str, set[str]]:
    """Every function body in a program's C, independent of how it was split.

    Temporaries are numbered per lowering session and `#line` directives into
    the generated C name the file that holds them, so both are normalized away:
    what remains is the code each function runs.
    """
    bodies: dict[str, set[str]] = {}
    for text in texts:
        lines = text.split("\n")
        index = 0
        while index < len(lines):
            header = _FUNCTION_HEADER.match(lines[index])
            if header is None:
                index += 1
                continue
            end = lines.index("}", index + 1)
            body = "".join(line for line in lines[index + 1 : end] if not line.startswith("#line"))
            name = _SESSION_NAME.sub("_", header.group(1))
            bodies.setdefault(name, set()).add(re.sub(r"\s+", "", _SESSION_NAME.sub("_", body)))
            index = end + 1
    return bodies


def test_private_body_edit_relowers_only_its_group(tmp_path, monkeypatch):
    workspace = _Workspace(tmp_path)
    clean, clean_units = workspace.build("CatalogMain.btrc", tmp_path / "clean", monkeypatch)
    assert {"Catalog.btrc", "CatalogMain.btrc", "Gallery.btrc", "Shapes.btrc"} <= _names(clean.module_units_lowered)
    assert not clean.module_units_reused
    assert workspace.run(clean, tmp_path / "clean") == (
        "catalog skipped empty shape of area 0\ncatalog total 15\ngallery value 1\n"
    )

    repeated, repeated_units = workspace.build("CatalogMain.btrc", tmp_path / "repeat", monkeypatch)
    assert not repeated.module_units_lowered
    assert repeated_units == clean_units

    workspace.edit("Catalog/Catalog.btrc", 'print(f"catalog skipped {error}");', 'print(f"catalog skip: {error}");')
    edited, edited_units = workspace.build("CatalogMain.btrc", tmp_path / "edit", monkeypatch)
    assert _names(edited.module_units_lowered) == {"Catalog.btrc"}
    changed = {name for name in edited_units if edited_units[name] != clean_units.get(name)}
    assert changed == {ModuleUnitCompiler.unit_name(edited.module_units_lowered[0])}
    assert workspace.run(edited, tmp_path / "edit").startswith("catalog skip: empty shape")

    # A clean build of the edited tree in a fresh cache is byte-identical.
    shutil.rmtree(workspace.cache)
    fresh, fresh_units = workspace.build("CatalogMain.btrc", tmp_path / "fresh", monkeypatch)
    assert not fresh.module_units_reused
    assert fresh_units == edited_units
    assert fresh.c_source == edited.c_source


def test_interface_edit_and_corrupt_records_rebuild(tmp_path, monkeypatch):
    workspace = _Workspace(tmp_path)
    workspace.build("GalleryMain.btrc", tmp_path / "first", monkeypatch)
    workspace.edit(
        "Shapes/Shapes.btrc",
        "public string label() {",
        'public string title() { return "shape"; }\n\n\tpublic string label() {',
    )
    widened, _ = workspace.build("GalleryMain.btrc", tmp_path / "widened", monkeypatch)
    # Stage A digests the whole program interface: every group rebuilds.
    assert not widened.module_units_reused
    records = list(workspace.cache.glob("*.module.json"))
    assert records
    for position, record in enumerate(records):
        # Truncated JSON and a checksum mismatch are both misses, never reuse.
        text = record.read_text()
        record.write_text(text[:-8] if position % 2 else text.replace('"sha256":"', '"sha256":"0', 1))
    rebuilt, _ = workspace.build("GalleryMain.btrc", tmp_path / "rebuilt", monkeypatch)
    assert not rebuilt.module_units_reused
    assert workspace.run(rebuilt, tmp_path / "rebuilt") == "shape square measured 12\ngallery value 37\n"


def _btrcc_build(btrcc, workspace: _Workspace, entry: str, output: Path) -> tuple[dict[str, int], dict[str, str], str]:
    """Compile through the self-hosted CLI; return its unit counters and texts."""
    counters, units, primary, _ = _btrcc_build_logged(btrcc, workspace, entry, output)
    return counters, units, primary


def _btrcc_build_logged(
    btrcc,
    workspace: _Workspace,
    entry: str,
    output: Path,
    environment: dict[str, str] | None = None,
    *,
    stdlib_strict=False,
) -> tuple[dict[str, int], dict[str, str], str, str]:
    """`_btrcc_build`, also returning the compiler's diagnostic output."""
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            str(btrcc),
            entry,
            "-o",
            str(output / "program.c"),
            "--emit-units",
            str(output / "program"),
            "--module-units",
            *(["--stdlib-strict"] if stdlib_strict else []),
        ],
        cwd=workspace.modules,
        env={
            **os.environ,
            "BTRC_HOME": str(ROOT / "src"),
            "BTRC_TIMING": "1",
            # The self-hosted cache requires a path without symbolic links.
            "BTRC_CACHE_DIR": str(workspace.cache.resolve()),
            **(environment or {}),
        },
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stderr
    counters = dict(
        (name, int(value))
        for name, value in (
            item.split(":") for item in result.stderr.split("module-units=", 1)[1].split()[0].split(",")
        )
    )
    units = {path.name: path.read_text() for path in sorted(output.glob("program.unit-*.c"))}
    return counters, units, (output / "program.c").read_text(), result.stderr


def _validation_records(stderr: str) -> dict[str, int]:
    """Replayed and journaled declaration counts from the timing report."""
    match = re.search(r"a-records-stored\(replayed=(\d+),journaled=(\d+)\)", stderr)
    assert match, stderr
    return {"replayed": int(match.group(1)), "journaled": int(match.group(2))}


def test_selfhost_private_body_edit_relowers_only_its_group(tmp_path, immutable_btrcc):
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("self-hosted artifact reuse needs the native header reader identity")
    workspace = _Workspace(tmp_path.resolve())
    clean, clean_units, _ = _btrcc_build(immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "clean")
    assert clean == {"lowered": 6, "reused": 0}
    repeated, repeated_units, _ = _btrcc_build(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "repeat"
    )
    assert repeated == {"lowered": 0, "reused": 6}
    assert repeated_units == clean_units

    workspace.edit("Catalog/Catalog.btrc", 'print(f"catalog skipped {error}");', 'print(f"catalog skip: {error}");')
    edited, edited_units, edited_primary = _btrcc_build(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "edit"
    )
    assert edited == {"lowered": 1, "reused": 5}
    changed = {name for name in edited_units if edited_units[name] != clean_units.get(name)}
    assert len(changed) == 1 and next(iter(changed)).startswith("program.unit-Catalog-")

    shutil.rmtree(workspace.cache)
    fresh, fresh_units, fresh_primary = _btrcc_build(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "fresh"
    )
    assert fresh == {"lowered": 6, "reused": 0}
    assert fresh_units == edited_units
    assert fresh_primary == edited_primary


def test_selfhost_unchanged_groups_replay_validation_records(tmp_path, immutable_btrcc):
    """Stage B: a body edit validates only its group; the others replay their
    records, and the build matches a fresh one byte for byte. Verify mode then
    validates everything live and requires every record to agree."""
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("self-hosted artifact reuse needs the native header reader identity")
    workspace = _Workspace(tmp_path.resolve())
    _, clean_units, _, clean_log = _btrcc_build_logged(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "clean"
    )
    clean = _validation_records(clean_log)
    assert clean["replayed"] == 0 and clean["journaled"] > 0

    workspace.edit("Catalog/Catalog.btrc", 'print(f"catalog skipped {error}");', 'print(f"catalog skip: {error}");')
    _, edited_units, edited_primary, edited_log = _btrcc_build_logged(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "edit"
    )
    edited = _validation_records(edited_log)
    assert edited["replayed"] > 0 and edited["journaled"] > 0
    assert edited["replayed"] + edited["journaled"] == clean["journaled"]

    workspace.edit("Catalog/Catalog.btrc", 'print(f"catalog skip: {error}");', 'print(f"catalog skip - {error}");')
    _, _, _, verified_log = _btrcc_build_logged(
        immutable_btrcc,
        workspace,
        "CatalogMain.btrc",
        workspace.root / "verify",
        {"BTRC_VERIFY_VALIDATION_RECORDS": "1"},
    )
    assert _validation_records(verified_log) == {"replayed": 0, "journaled": clean["journaled"]}

    workspace.edit("Catalog/Catalog.btrc", 'print(f"catalog skip - {error}");', 'print(f"catalog skip: {error}");')
    shutil.rmtree(workspace.cache)
    _, fresh_units, fresh_primary, _ = _btrcc_build_logged(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "fresh"
    )
    assert fresh_units == edited_units
    assert fresh_primary == edited_primary
    assert clean_units.keys() == fresh_units.keys()


def test_selfhost_generation_references_stored_units(tmp_path, immutable_btrcc):
    """A stored generation names the module units the store already holds
    instead of copying their text; a referenced unit whose bytes changed makes
    the generation a miss, and the rebuild emits the same program."""
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("self-hosted artifact reuse needs the native header reader identity")
    workspace = _Workspace(tmp_path.resolve())
    output = workspace.root / "out"
    output.mkdir()

    def build() -> tuple[str, dict[str, str], str]:
        result = subprocess.run(
            [
                str(immutable_btrcc),
                "CatalogMain.btrc",
                "-o",
                str(output / "program.c"),
                "--emit-units",
                str(output / "program"),
                "--module-units",
            ],
            cwd=workspace.modules,
            env={
                **os.environ,
                "BTRC_HOME": str(ROOT / "src"),
                "BTRC_TIMING": "1",
                "BTRC_CACHE_DIR": str(workspace.cache.resolve()),
            },
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
        units = {path.name: path.read_text() for path in sorted(output.glob("program.unit-*.c"))}
        return result.stderr, units, (output / "program.c").read_text()

    first_log, first_units, first_primary = build()
    assert "artifact-hit=" not in first_log
    manifest_path = next(workspace.cache.glob("selfhost-artifacts-v1/*/manifest.json"))
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema"] == 2
    referenced = [index for index, reference in enumerate(manifest["units"]) if reference]
    assert referenced, manifest
    assert all(not (manifest_path.parent / f"part-{index}").exists() for index in referenced)

    hit_log, hit_units, hit_primary = build()
    assert "artifact-hit=" in hit_log
    assert (hit_units, hit_primary) == (first_units, first_primary)

    digest = manifest["hashes"][referenced[-1]]
    stored = [
        path
        for path in workspace.cache.glob("selfhost-artifacts-v1/*/unit.c")
        if hashlib.sha256(path.read_bytes()).hexdigest() == digest
    ]
    assert stored
    for path in stored:
        path.write_text(path.read_text() + "/* changed */\n")
    miss_log, miss_units, miss_primary = build()
    assert "artifact-hit=" not in miss_log
    assert (miss_units, miss_primary) == (first_units, first_primary)


AUDIO = ROOT / "src" / "tests" / "native" / "audio"


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreAudio is available only on macOS")
def test_realtime_proofs_cross_units_into_native_adapters(compiler: str, tmp_path, request):
    """A realtime root proves through another unit's native callback adapter.

    The adapter's unit publishes its native callee as realtime-safe; the proof
    rooted in a different unit must accept it, as whole-program lowering does.
    """
    if not os.environ.get("BTRC_NATIVE_SYSROOT") or not os.environ.get("BTRC_NATIVE_TARGET"):
        pytest.skip("CoreAudio units need the native SDK environment")
    prefix = tmp_path / "program"
    source = fault_package(tmp_path / "package", "CoreAudioUnitConformance.btrc")
    arguments = [
        "--strict-imports",
        "--target",
        "macos-arm64",
        str(source),
        "-o",
        f"{prefix}.c",
        "--emit-units",
        str(prefix),
        "--module-units",
    ]
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main", *arguments]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc")), *arguments]
    environment = {
        **os.environ,
        "BTRC_HOME": str(ROOT / "src"),
        # The self-hosted cache requires a path without symbolic links.
        "BTRC_CACHE_DIR": str((tmp_path / "cache").resolve()),
    }
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr
    units = sorted(tmp_path.glob("program.unit-*.c"))
    assert len(units) > 1
    # A unit includes a native binding header only when its C names something
    # the header declares, so the units' include sets differ; the link below
    # proves each unit still has every header it needs.
    includes = [frozenset(re.findall(r'^#include "([^"]+)"', unit.read_text(), re.M)) for unit in units]
    assert len(set(includes)) > 1
    host = {key: value for key, value in os.environ.items() if key not in {"DEVELOPER_DIR", "SDKROOT"}}
    executable = tmp_path / "program"
    built = subprocess.run(
        [
            "/usr/bin/clang",
            "-std=c11",
            "-O2",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic-errors",
            "-isysroot",
            os.environ["BTRC_NATIVE_SYSROOT"],
            "-target",
            os.environ["BTRC_NATIVE_TARGET"],
            "-include",
            str(AUDIO / "UnitFaults.h"),
            f"{prefix}.c",
            *map(str, units),
            str(AUDIO / "UnitFaults.c"),
            "-framework",
            "CoreAudio",
            "-framework",
            "CoreFoundation",
            "-framework",
            "AudioToolbox",
            "-o",
            str(executable),
        ],
        env=host,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run([str(executable)], env=host, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout == "PASS: BTRC CoreAudio unit preserves samples, clocks and retryable ownership\n"


@dataclass(frozen=True)
class _NativeAdapters:
    """The generated unit a native project links, and adapters only it defines."""

    unit: str
    linker: str
    symbols: tuple[str, ...]


@pytest.fixture
def objective_c_units_project(native_project):
    """A class, a category of it and an AppKit constant from three binding modules.

    Each binding module is its own compilation group, so each would lower its
    own Objective-C adapters if a group owned them.
    """
    source, _sdk, _triple = native_project
    root = source.parent.parent
    (root / "Foundation.h").unlink()
    (source.parent / "Foundation.btrc").unlink()
    (root / "Base.h").write_text(
        "#pragma once\n#import <Foundation/Foundation.h>\n@interface NativeWidget : NSObject\n- (long)baseValue;\n@end\n",
        encoding="utf-8",
    )
    (root / "Extra.h").write_text(
        '#pragma once\n#import "Base.h"\n@interface NativeWidget (Extra)\n- (long)offsetValue:(long)value;\n@end\n',
        encoding="utf-8",
    )
    (root / "Modal.h").write_text("#pragma once\n#import <AppKit/AppKit.h>\n", encoding="utf-8")
    (root / "Native.m").write_text(
        '#import "Extra.h"\n@implementation NativeWidget\n- (long)baseValue { return 11; }\n@end\n'
        "@implementation NativeWidget (Extra)\n- (long)offsetValue:(long)value { return self.baseValue + value; }\n@end\n",
        encoding="utf-8",
    )
    manifest = 'manifest-version = 1\n[package]\nname = "nativeModuleUnits"\n'
    for module, header, symbols in (
        ("Alpha", "Base.h", ["+[NativeWidget new]", "-[NativeWidget baseValue]"]),
        ("Beta", "Extra.h", ["-[NativeWidget baseValue]", "-[NativeWidget offsetValue:]"]),
        ("Gamma", "Modal.h", ["NSModalResponseOK"]),
    ):
        manifest += (
            f'[[native.bindings]]\nmodule = "{module}"\nheader = "{header}"\nlanguage = "objective-c"\n'
            f'standard = "c11"\nos = ["macos"]\nsymbols = {json.dumps(symbols)}\n'
        )
        (source.parent / f"{module}.btrc").write_text("// Selected native declarations.\n", encoding="utf-8")
    manifest += (
        '[[native.sources]]\npath = "Native.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.frameworks]]\nname = "Foundation"\n[[native.frameworks]]\nname = "AppKit"\n'
    )
    (root / "btrc.toml").write_text(manifest, encoding="utf-8")
    source.write_text(
        "import ./Alpha.btrc;\nimport ./Beta.btrc;\nimport ./Gamma.btrc;\nint main() {\n"
        "\tvar widget = NativeWidget.new(); if (widget == null) { return 1; }\n"
        "\tif (widget.baseValue() != 11L || widget.offsetValue(7L) != 18L) { return 2; }\n"
        "\tif (NSModalResponseOK != 1L) { return 3; }\n"
        "\trelease widget; return 0;\n}\n",
        encoding="utf-8",
    )
    return source, _NativeAdapters(
        "ObjectiveCAdapters",
        "c",
        (
            "__btrc_objc_NativeWidget_retain",
            "__btrc_objc_NativeWidget_offsetValue",
            "__btrc_objc_address_NSModalResponseOK",
        ),
    )


@pytest.fixture
def cxx_units_project(pugixml_project):
    """pugixml's C++ owners, whose initializer outcome class the importer writes."""
    source, _sdk, _triple = pugixml_project
    return source, _NativeAdapters(
        "CxxAdapters", "c++", ("__btrc_cxx_PugiDocument_load_buffer", "__btrc_cxx_PugiNode_name")
    )


def _native_unit_plan(command: list[str], source: Path, output: Path, *, module_units: bool) -> dict:
    """Compile `source` through a compiler CLI; return its link plan with unit paths made relative."""
    output.mkdir(parents=True)
    completed = subprocess.run(
        [
            *command,
            "--no-cache",
            "--no-stdlib",
            "--strict-imports",
            "--target",
            "macos-arm64" if platform.machine() == "arm64" else "macos-x86_64",
            str(source),
            "-o",
            str(output / "program.c"),
            "--emit-units",
            str(output / "program"),
            "--emit-link-plan",
            str(output / "program.link.json"),
            *(["--module-units", "--jobs", "2"] if module_units else []),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src"), "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    plan = json.loads((output / "program.link.json").read_text(encoding="utf-8"))
    units = [Path(path) if Path(path).is_absolute() else ROOT / path for path in plan.get("emitted-units", [])]
    # Each digest is this compiler's own C for that unit, and the two
    # compilers' unit bodies still differ (docs/design/compiler-parity.md), so
    # the digests are checked against the files here and left out of the plan.
    digests = plan.pop("emitted-unit-digests", None)
    if digests is not None:
        assert digests == [hashlib.sha256(unit.read_bytes()).hexdigest() for unit in units]
    plan["emitted-units"] = [unit.name for unit in units]
    return plan


def _native_command(compiler: str, request) -> list[str]:
    if compiler == "python":
        return [sys.executable, "-m", "src.compiler.python.main"]
    return [str(request.getfixturevalue("immutable_btrcc"))]


@pytest.mark.parametrize("project", ["objective_c_units_project", "cxx_units_project"])
def test_module_unit_link_plans_carry_native_adapters(compiler: str, project: str, tmp_path, request):
    """A module-unit build links the same adapter units as a whole-program build.

    The adapters belong to the program unit wherever their binding module
    is, so the plan names the generated Objective-C or C++ unit and its
    linker, every C unit only calls the adapters, and the program links.
    """
    source, expected = request.getfixturevalue(project)
    source = source.resolve()
    command = _native_command(compiler, request)
    whole = _native_unit_plan(command, source, tmp_path / "whole", module_units=False)
    plan = _native_unit_plan(command, source, tmp_path / "module", module_units=True)
    assert [unit["name"] for unit in plan.get("generated-units", [])] == [expected.unit]
    assert plan["linker-language"] == whole["linker-language"] == expected.linker
    assert plan["generated-units"] == whole["generated-units"]
    adapters = plan["generated-units"][0]["source"]
    units = [tmp_path / "module" / "program.c", *(tmp_path / "module" / name for name in plan["emitted-units"])]
    for symbol in expected.symbols:
        # A definition opens at column zero with its linkage and return type; a
        # call never does.
        definition = re.compile(rf'^(?:extern "C" )?[A-Za-z_][\w \t*]*\b{symbol}\([^;\n]*\)\s*\{{', re.M)
        assert definition.search(adapters), symbol
        assert not any(definition.search(unit.read_text(encoding="utf-8")) for unit in units), symbol
    environment = apple_environment()

    def run(command, **kwargs):
        flags = ["-O1"] if command[0].endswith(("clang", "clang++")) else []
        return subprocess.run(
            [command[0], *flags, *command[1:]], env=apple_environment(kwargs.pop("env", environment)), **kwargs
        )

    executable = tmp_path / "module" / "program"
    NativePlanBuilder(runner=run).build(
        plan_path=tmp_path / "module" / "program.link.json",
        generated_c=tmp_path / "module" / "program.c",
        output=executable,
        cc="/usr/bin/clang",
        cxx="/usr/bin/clang++",
        jobs=2,
    )
    ran = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, (ran.stdout, ran.stderr)
    assert not ran.stderr


@pytest.mark.parametrize("project", ["objective_c_units_project", "cxx_units_project"])
def test_module_unit_link_plans_match_across_compilers(project: str, tmp_path, request):
    """Both compilers give native declarations to the program unit, so their
    module-unit link plans name the same units, adapters and linker."""
    source, _expected = request.getfixturevalue(project)
    source = source.resolve()
    plans = {
        compiler: _native_unit_plan(_native_command(compiler, request), source, tmp_path / compiler, module_units=True)
        for compiler in ("python", "btrc")
    }
    assert plans["python"] == plans["btrc"]


_ENUM_PROGRAM = {
    "Kinds.btrc": (
        "enum Shade { Light, Dark };\n\n"
        "enum class Mark {\n\tHit(int points),\n\tMiss\n}\n\n"
        "interface IShaded {\n\tShade shade();\n}\n"
    ),
    "Main.btrc": (
        "import ./Kinds.btrc;\n\n"
        "int main() {\n"
        "\tShade value = Shade.Dark;\n"
        "\tMark mark = Mark.Hit(3);\n"
        "\tprint(value.toString());\n"
        "\tprint(mark.toString());\n"
        "\treturn 0;\n"
        "}\n"
    ),
}


def test_enum_functions_belong_to_the_enums_unit(tmp_path, request):
    """An enum's `_toString` and variant constructors have program-wide names,
    so the enum's group defines them once with external linkage and every
    other unit declares them, in both compilers, even when only another
    group calls them (the declaring group then keeps a unit of its own)."""
    source = (tmp_path / "program").resolve()
    source.mkdir()
    for name, text in _ENUM_PROGRAM.items():
        (source / name).write_text(text)
    units: dict[str, dict[str, str]] = {}
    for compiler in ("python", "btrc"):
        output = tmp_path.resolve() / compiler
        output.mkdir()
        completed = subprocess.run(
            [
                *_native_command(compiler, request),
                "Main.btrc",
                "-o",
                str(output / "p.c"),
                "--emit-units",
                str(output / "p"),
                "--module-units",
                "--jobs",
                "1",
            ],
            cwd=source,
            env={
                **os.environ,
                "BTRC_HOME": str(ROOT / "src"),
                "PYTHONPATH": str(ROOT),
                "BTRC_CACHE_DIR": str(output / "cache"),
            },
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        units[compiler] = {path.name: path.read_text() for path in sorted(output.glob("p*.c"))}
    assert sorted(units["python"]) == sorted(units["btrc"])
    kinds = ModuleUnitCompiler.unit_name(str(source / "Kinds.btrc"))
    main = ModuleUnitCompiler.unit_name(str(source / "Main.btrc"))
    for compiler, texts in units.items():
        assert f"p.{kinds}.c" in texts, compiler
        for symbol in ("Shade_toString", "Mark_toString", "Mark_Hit"):
            definition = re.compile(rf"^(static )?[A-Za-z_][\w \t*]*\b{symbol}\([^;\n]*\)\s*\{{", re.M)
            defining = [name for name, text in texts.items() if definition.search(text)]
            assert defining == [f"p.{kinds}.c"], (compiler, symbol, defining)
            assert not definition.search(texts[f"p.{kinds}.c"]).group(1), (compiler, symbol)
            assert re.search(rf"^[^\n]*\b{symbol}\([^;\n]*\);$", texts[f"p.{main}.c"], re.M), (compiler, symbol)
    if C_COMPILER is None:
        return
    for compiler in units:
        output = tmp_path.resolve() / compiler
        sources = sorted(str(path) for path in output.glob("p*.c"))
        executable = output / "program"
        subprocess.run(
            [
                *C_COMPILER,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                *sources,
                "-o",
                str(executable),
            ]
            + ["-lm", "-lpthread"],
            check=True,
            capture_output=True,
            timeout=180,
        )
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
        assert ran.returncode == 0 and ran.stdout == "Dark\nHit\n", (compiler, ran)


@pytest.mark.parametrize("rich", [False, True], ids=["plain", "rich"])
def test_module_enum_declarations_match_their_owning_group_order(tmp_path, request, rich):
    if C_COMPILER is None:
        pytest.skip("module-unit execution needs a C compiler")
    sanitizer = require_sanitizers(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    if rich:
        shared = "enum class SharedKind { Value(int amount), Empty }\n"
        local = """
            enum class LocalKind { Mark(int amount), Missing }
            int main() {
                SharedKind shared = SharedKind.Value(5);
                LocalKind local = LocalKind.Mark(7);
                print(shared.toString());
                print(local.toString());
                print(shared.data.Value.amount + local.data.Mark.amount);
                return 0;
            }
        """
        expected = "Value\nMark\n12\n"
    else:
        shared = "enum SharedKind { low = 3, high = low + 2 };\n"
        local = """
            enum LocalKind { first = 6, here = first + 1 };
            int main() {
                SharedKind shared = SharedKind.high;
                LocalKind local = LocalKind.here;
                print(shared.toString());
                print(local.toString());
                print((int)shared + (int)local);
                return 0;
            }
        """
        expected = "high\nhere\n12\n"
    (source / "Shared.btrc").write_text(shared)
    (source / "Main.btrc").write_text("import ./Shared.btrc;\n" + local)
    declarations = {}
    for compiler in ("python", "btrc"):
        output = tmp_path / compiler
        output.mkdir()
        completed = subprocess.run(
            [
                *_native_command(compiler, request),
                str(source / "Main.btrc"),
                "--no-cache",
                "--strict-imports",
                "--module-units",
                "--jobs",
                "1",
                "--emit-units",
                str(output / "program"),
                "-o",
                str(output / "program.c"),
            ],
            cwd=ROOT,
            env={**os.environ, "BTRC_HOME": str(ROOT / "src"), "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        sources = sorted(output.glob("*.c"))
        main_unit = next(path for path in sources if ".unit-Main-" in path.name)
        declarations[compiler] = re.findall(
            r"^typedef enum \{\n[^{}]*^\} (?:SharedKind|LocalKind)(?:_Tag)?;",
            main_unit.read_text(),
            re.M,
        )
        assert len(declarations[compiler]) == 2
        for mode in ("strict", "sanitized"):
            native_compiler = sanitizer.command if mode == "sanitized" else C_COMPILER
            flags = (
                ["-O1", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if mode == "sanitized" else ["-O2"]
            )
            environment = sanitizer.environment if mode == "sanitized" else None
            executable = output / mode
            built = subprocess.run(
                [
                    *native_compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    *flags,
                    *map(str, sources),
                    "-lm",
                    "-lpthread",
                    "-o",
                    str(executable),
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert built.returncode == 0, built.stderr
            ran = subprocess.run(
                [str(executable)],
                env=sanitizer_environment(sanitizer) if mode == "sanitized" else None,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert ran.returncode == 0 and ran.stdout == expected, (compiler, mode, ran)
    assert declarations["python"] == declarations["btrc"]


def _cli_units(command: list[str], workspace: _Workspace, entry: str, output: Path, jobs: int) -> dict[str, str]:
    """Compile `entry` through a compiler CLI with `jobs` workers; return every emitted C file."""
    output.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            *command,
            entry,
            "-o",
            str(output / "program.c"),
            "--emit-units",
            str(output / "program"),
            "--module-units",
            "--jobs",
            str(jobs),
        ],
        cwd=workspace.modules,
        env={
            **os.environ,
            "BTRC_HOME": str(ROOT / "src"),
            "PYTHONPATH": str(ROOT),
            "BTRC_CACHE_DIR": str((output / "cache").resolve()),
        },
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    return {path.name: path.read_text() for path in sorted(output.glob("program*.c"))}


def test_worker_counts_emit_identical_units(compiler: str, tmp_path, request):
    """One worker and several forked workers run the same schedule to the same C."""
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main"]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc"))]
    workspace = _Workspace(tmp_path.resolve())
    single = _cli_units(command, workspace, "CatalogMain.btrc", workspace.root / "single", 1)
    forked = _cli_units(command, workspace, "CatalogMain.btrc", workspace.root / "forked", 3)
    assert len(single) > 3
    # Debug-free output never names its directory, so the files compare directly.
    assert forked == single


@dataclass
class _TimedBuild:
    """One CLI module-unit compile's owner pid, timing lines and units."""

    pid: int
    owner: list[str]
    workers: list[str]
    stderr: str
    units: dict[str, str]


def _timed_cli_build(
    command: list[str],
    workspace: _Workspace,
    output: Path,
    jobs: int | None,
    *,
    timing: bool = True,
    cache: Path | None = None,
) -> _TimedBuild:
    """Compile CatalogMain through a compiler CLI, with BTRC_TIMING set or unset."""
    output.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "BTRC_HOME": str(ROOT / "src"),
        "PYTHONPATH": str(ROOT),
        "BTRC_CACHE_DIR": str((cache or output / "cache").resolve()),
    }
    environment.pop("BTRC_TIMING", None)
    if timing:
        environment["BTRC_TIMING"] = "1"
    process = subprocess.Popen(
        [
            *command,
            "CatalogMain.btrc",
            "-o",
            str(output / "program.c"),
            "--emit-units",
            str(output / "program"),
            "--module-units",
            *(["--jobs", str(jobs)] if jobs is not None else []),
        ],
        cwd=workspace.modules,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _stdout, stderr = process.communicate(timeout=300)
    assert process.returncode == 0, stderr
    lines = stderr.splitlines()
    return _TimedBuild(
        process.pid,
        [line for line in lines if re.match(r"^(btrcpy|btrcc) timing: ", line)],
        [line for line in lines if re.match(r"^(btrcpy|btrcc) worker timing: ", line)],
        stderr,
        {path.name: path.read_text() for path in sorted(output.glob("program*.c"))},
    )


def _timing_command(compiler: str, request) -> list[str]:
    if compiler == "python":
        return [sys.executable, "-m", "src.compiler.python.main"]
    return [str(request.getfixturevalue("immutable_btrcc"))]


def _python_lowered_groups(workspace: _Workspace, output: Path) -> int:
    """How many groups a cold module-unit build of CatalogMain lowers."""
    path = workspace.modules / "CatalogMain.btrc"
    result = Compiler(cache=CompilerCache()).compile(
        path.read_text(),
        str(path),
        CompilerOptions(units_prefix=str(output / "program"), module_units=True, use_cache=False),
    )
    assert result.failure is None, result.failure
    return len(result.module_units_lowered)


def test_forked_workers_report_timing_through_the_owner(compiler: str, tmp_path, request):
    """A forked pool's workers each send the owner a report it prints last.

    The owner's line comes first and is unchanged, so `tools.perf` sums only
    the owner's phases; every worker reports once, from its own process, with
    no owner-only token, and together the workers lowered every group.
    """
    from tools import perf

    workspace = _Workspace(tmp_path.resolve())
    build = _timed_cli_build(_timing_command(compiler, request), workspace, workspace.root / "cold", 2)
    assert len(build.owner) == 1
    assert build.stderr.splitlines().index(build.owner[0]) < min(
        build.stderr.splitlines().index(line) for line in build.workers
    )
    owner = build.owner[0]
    if compiler == "python":
        count = 2
        lowered = _python_lowered_groups(workspace, workspace.root / "probe")
    else:
        count = int(re.search(r"\bmodule-unit-workers=(\d+)", owner).group(1))
        lowered = int(re.search(r"\bmodule-units=lowered:(\d+)", owner).group(1))
    assert count == 2
    assert len(build.workers) == count
    fields = [dict(item.partition("=")[::2] for item in line.split(": ", 1)[1].split()) for line in build.workers]
    assert sorted(int(field["worker"]) for field in fields) == list(range(count))
    pids = {int(field["pid"]) for field in fields}
    assert len(pids) == count and build.pid not in pids
    requests = [dict(entry.split(":") for entry in field["requests"].split(",")) for field in fields]
    assert all(set(entry) == {"lower", "setjmp", "realtime", "finish"} for entry in requests)
    assert sum(int(entry["lower"]) for entry in requests) == lowered
    for line in build.workers:
        assert "w-wait=" in line
        for token in ("grammar=", "analyze=", "u-plan=", "module-units=", "a-records-stored(", "artifact-hit="):
            assert token not in line
        if compiler == "btrc":
            assert "l-setup=" in line and "w-reply=" in line

    # `phase_times` cannot yet read btrcc's `a-records-stored(...)=` counter,
    # whose name holds an `=`; that token is the owner's either way.
    def summable(text: str) -> str:
        return re.sub(r"\S*\(\S*", "", text)

    assert perf.phase_times(summable(build.stderr)) == perf.phase_times(summable(owner))
    assert sorted(perf.worker_phase_times(build.stderr)) == list(range(count))
    # The owner reaps each worker and appends what that process used, last:
    # CPU time in microseconds and peak resident memory in KiB on every host.
    for line in build.workers:
        assert re.search(r" usage=user:\d+us,sys:\d+us,maxrss:\d+KiB$", line), line
    usage = perf.worker_usage(build.stderr)
    assert sorted(usage) == list(range(count))
    for used in usage.values():
        assert used["user"] + used["sys"] > 0
        # A worker's peak is at most hundreds of megabytes; the same figure
        # read in bytes would pass 16 GiB.
        assert 1024 <= used["maxrss_kib"] < 16 * 1024 * 1024


def test_inline_and_incremental_builds_print_no_worker_timing(compiler: str, tmp_path, request):
    """Where the owner is the only worker its time is already the owner's."""
    command = _timing_command(compiler, request)
    workspace = _Workspace(tmp_path.resolve())
    inline = _timed_cli_build(command, workspace, workspace.root / "inline", 1)
    assert len(inline.owner) == 1 and not inline.workers
    assert not re.search(r"\bw-", inline.owner[0])
    assert "usage=" not in inline.stderr
    cache = workspace.root / "cache"
    _timed_cli_build(command, workspace, workspace.root / "cold", 2, cache=cache)
    # Timing keeps the artifact cache on in both compilers, so a no-op
    # rebuild of the same outputs is a hit, and both mark it.
    again = _timed_cli_build(command, workspace, workspace.root / "cold", 2, cache=cache)
    assert len(again.owner) == 1 and not again.workers
    assert re.search(r"\bartifact-hit=\d+us", again.owner[0]), again.owner[0]
    warm = _timed_cli_build(command, workspace, workspace.root / "warm", 2, cache=cache)
    assert len(warm.owner) == 1 and not warm.workers
    workspace.edit("Catalog/Catalog.btrc", 'print(f"catalog skipped {error}");', 'print(f"catalog skip: {error}");')
    edited = _timed_cli_build(command, workspace, workspace.root / "edited", 2, cache=cache)
    assert len(edited.owner) == 1 and not edited.workers


def test_default_worker_count_is_one_per_online_cpu_up_to_four(compiler: str, tmp_path, request):
    """Without --jobs both compilers start the same pool: one worker per
    online CPU, at most four, and never more than the groups to lower."""
    workspace = _Workspace(tmp_path.resolve())
    build = _timed_cli_build(_timing_command(compiler, request), workspace, workspace.root / "cold", None)
    lowered = _python_lowered_groups(workspace, workspace.root / "probe")
    expected = min(os.sysconf("SC_NPROCESSORS_ONLN"), 4, lowered)
    assert len(build.workers) == (expected if expected > 1 else 0), build.stderr
    if compiler == "btrc":
        assert f"module-unit-workers={max(expected, 1)}" in build.owner[0]


def test_worker_timing_never_changes_the_units(compiler: str, tmp_path, request):
    """Without BTRC_TIMING nothing is reported, and the units are the same."""
    command = _timing_command(compiler, request)
    workspace = _Workspace(tmp_path.resolve())
    quiet = _timed_cli_build(command, workspace, workspace.root / "quiet", 2, timing=False)
    assert "timing:" not in quiet.stderr
    timed = _timed_cli_build(command, workspace, workspace.root / "timed", 2)
    assert timed.workers
    assert quiet.units == timed.units


def test_native_includes_are_include_once_blocks(compiler: str, tmp_path, request):
    """A module unit wraps each native include in a guard named for its header,
    so a precompiled prelude that already included it leaves the unit's copy
    out; system includes stay bare."""
    import hashlib

    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main"]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc"))]
    workspace = _Workspace(tmp_path.resolve())
    units = _cli_units(command, workspace, "CatalogMain.btrc", workspace.root / "out", 1)
    guard = "BTRC_INCLUDE_" + hashlib.sha256(b"ShapeScale.h").hexdigest()[:16].upper()
    block = f'#ifndef {guard}\n#define {guard}\n#include "ShapeScale.h"\n#endif\n'
    including = [text for text in units.values() if '#include "ShapeScale.h"' in text]
    assert including
    assert all(text.count('#include "ShapeScale.h"') == text.count(block) == 1 for text in including)
    assert all("BTRC_INCLUDE_" not in line for text in units.values() for line in text.split("\n") if "<" in line)


_CYCLE_PROGRAM = {
    "Model/Node.btrc": """import Library.Vector;

int nodeCount = 0;

class Node {
	public int id;
	public Vector<Node> children;

	public Node(int id) {
		self.id = id;
		self.children = {};
		nodeCount++;
	}

	public void __del__() { nodeCount--; }
}
""",
    "Build.btrc": """import Library.Vector;
import ./Model/Node.btrc;

int buildCycle() {
	Vector<Node> roots = [];
	Node a = new Node(1);
	Node b = new Node(2);
	a.children.push(b);
	b.children.push(a);
	roots.push(a);
	return roots.len;
}
""",
    "Main.btrc": """import ./Build.btrc;
import ./Model/Node.btrc;

int main() {
	int built = buildCycle();
	print(f"{built} {nodeCount}");
	return 0;
}
""",
}


def test_module_units_emit_the_whole_program_functions(compiler: str, tmp_path, request):
    """A unit that uses a specialization another unit owns keeps its cycle visitor.

    `Build` holds a `Vector<Node>` whose specialization it does not lower; the
    descriptor it builds must still name the visitor, as a whole-program build
    does, so every function body matches and the cycle is reclaimed.
    """
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main"]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc"))]
    source = (tmp_path / "program").resolve()
    for name, text in _CYCLE_PROGRAM.items():
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text(text)

    def build(output: Path, *mode: str) -> list[Path]:
        output.mkdir(parents=True)
        completed = subprocess.run(
            [*command, "Main.btrc", "-o", str(output / "p.c"), "--emit-units", str(output / "p"), *mode],
            cwd=source,
            env={
                **os.environ,
                "BTRC_HOME": str(ROOT / "src"),
                "PYTHONPATH": str(ROOT),
                "BTRC_CACHE_DIR": str(output / "cache"),
            },
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        return sorted(output.glob("p*.c"))

    whole = build(tmp_path.resolve() / "whole")
    units = build(tmp_path.resolve() / "units", "--module-units", "--jobs", "2")
    bodies = _function_bodies(path.read_text() for path in units)
    assert "buildCycle" in bodies
    assert bodies == _function_bodies(path.read_text() for path in whole)
    if C_COMPILER is None:
        pytest.skip("module-unit execution needs a C compiler")
    executable = tmp_path / "units" / "program"
    subprocess.run(
        [*C_COMPILER, "-std=c11", *map(str, units), "-o", str(executable), "-lm", "-lpthread"],
        check=True,
        capture_output=True,
        timeout=180,
    )
    ran = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=30)
    assert ran.stdout == "1 0\n"


_DEFINITION = re.compile(r"^([A-Za-z_][\w \t*]*?)\b(__btrc_\w+)\s*\(", re.MULTILINE)


def _runtime_definitions(text: str) -> dict[str, str]:
    """Top-level runtime helper function definitions in one unit, name to storage.

    A definition's signature may span lines, so each candidate header is read
    up to its first `;` or `{`: a `{` makes it a definition."""
    found = {}
    for match in _DEFINITION.finditer(text):
        rest = text[match.end() :]
        end = min((index for index in (rest.find(";"), rest.find("{")) if index >= 0), default=-1)
        if end >= 0 and rest[end] == "{" and "=" not in rest[:end]:
            found[match.group(2)] = match.group(1)
    return found


def test_runtime_helpers_are_compiled_once_in_the_runtime_unit(compiler: str, tmp_path, request):
    """The runtime unit defines every runtime helper once, with external
    linkage; the group units only declare them, so the C compiler builds the
    runtime once per program rather than once per unit."""
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main"]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc"))]
    source = (tmp_path / "program").resolve()
    for name, text in _CYCLE_PROGRAM.items():
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text(text)
    output = tmp_path.resolve() / "units"
    output.mkdir()
    completed = subprocess.run(
        [*command, "Main.btrc", "-o", str(output / "p.c"), "--emit-units", str(output / "p"), "--module-units"],
        cwd=source,
        env={
            **os.environ,
            "BTRC_HOME": str(ROOT / "src"),
            "PYTHONPATH": str(ROOT),
            "BTRC_CACHE_DIR": str(output / "cache"),
        },
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    runtime = output / "p.unit-runtime.c"
    others = [path for path in sorted(output.glob("p*.c")) if path != runtime]
    defined = _runtime_definitions(runtime.read_text())
    # The ARC release path and the try stack are always in a program with
    # cycles and exceptions; each is defined here and declared elsewhere.
    assert {"__btrc_arc_release_impl", "__btrc_push_try"} <= defined.keys()
    assert not any("static" in storage or "inline" in storage for storage in defined.values())
    for path in others:
        text = path.read_text()
        assert not _runtime_definitions(text).keys() & defined.keys(), path.name
    assert any("__btrc_push_try(void);" in path.read_text() for path in others)
    if C_COMPILER is None:
        pytest.skip("module-unit execution needs a C compiler")
    executable = output / "program"
    subprocess.run(
        [
            *C_COMPILER,
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            *map(str, [runtime, *others]),
            "-o",
            str(executable),
            "-lm",
            "-lpthread",
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    ran = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=30)
    assert ran.stdout == "1 0\n"


def test_an_edit_replaces_only_the_changed_unit_files(compiler: str, tmp_path, request):
    """Units whose bytes are unchanged keep their files, inode and mtime included.

    Native preprocessing receipts are bound to that identity; rewriting every
    unit made each edit preprocess the whole program again.
    """
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main"]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc"))]
    source = (tmp_path / "program").resolve()
    source.mkdir()
    for name, text in _EFFECTS_PROGRAM.items():
        (source / name).write_text(text)
    output = tmp_path.resolve() / "out"
    output.mkdir()
    environment = {
        **os.environ,
        "BTRC_HOME": str(ROOT / "src"),
        "PYTHONPATH": str(ROOT),
        "BTRC_CACHE_DIR": str(tmp_path.resolve() / "cache"),
        "BTRC_STATE_DIR": str(tmp_path.resolve() / "state"),
    }

    def build() -> dict[str, os.stat_result]:
        completed = subprocess.run(
            [*command, "Main.btrc", "-o", str(output / "p.c"), "--emit-units", str(output / "p"), "--module-units"],
            cwd=source,
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        return {path.name: path.stat() for path in output.glob("p.unit-*.c")}

    before = build()
    main = source / "Main.btrc"
    main.write_text(
        main.read_text().replace('print(f"{useFill()} {useGrow()}");', 'print(f"{useGrow()} {useFill()}");')
    )
    after = build()
    assert after.keys() == before.keys() and len(after) >= 3
    replaced = {name for name in after if after[name].st_ino != before[name].st_ino}
    assert replaced == {name for name in after if "Main" in name}
    for name in after.keys() - replaced:
        assert after[name].st_mtime_ns == before[name].st_mtime_ns


# Each group's header reads a macro an earlier group defines and must not see
# one a later group defines, so a unit that put its own directives ahead of the
# other groups' fails to preprocess. Two groups repeat a macro and an include,
# and Probe imports a raw C source, which only Probe's unit may include.
_DIRECTIVE_PROGRAM = {
    "Config/Config.btrc": """#define CFG_SCALE 3
#define CFG_LABEL "cfg"
#define SHARED_FLAG 1
#include <iso646.h>

int configScale() {
	return CFG_SCALE;
}
""",
    "Probe/Probe.btrc": """import ../Config/Config.btrc;
import ./helper.c;
#include "probe.h"
#define SHARED_FLAG 1
#include <iso646.h>

extern int probeHelper(int value);

int probeValue() {
	return probeHelper(probeScaled(configScale()));
}
""",
    "Main.btrc": """import ./Config/Config.btrc;
import ./Probe/Probe.btrc;
#include "lib.h"
#define MAIN_OFFSET 10

int main() {
	int scaled = libScaled(2);
	print(f"{configScale()} {probeValue()} {scaled + MAIN_OFFSET}");
	return 0;
}
""",
    "Probe/helper.c": """int probeHelper(int value) {
    return value * 2;
}
""",
    "Probe/probe.h": """#ifndef CFG_SCALE
#error CFG_SCALE must precede probe.h
#endif
#ifdef MAIN_OFFSET
#error MAIN_OFFSET must follow probe.h
#endif
static inline int probeScaled(int value) { return value + CFG_SCALE; }
""",
    "lib.h": """#ifndef CFG_SCALE
#error CFG_SCALE must precede lib.h
#endif
#ifdef MAIN_OFFSET
#error MAIN_OFFSET must follow lib.h
#endif
static inline int libScaled(int value) { return value * CFG_SCALE; }
""",
}
# The whole program's source directives, in source order: the repeated macro
# stays twice, the repeated include once.
_DIRECTIVES = (
    "#define CFG_SCALE 3",
    '#define CFG_LABEL "cfg"',
    "#define SHARED_FLAG 1",
    "#include <iso646.h>",
    '#include "probe.h"',
    "#define SHARED_FLAG 1",
    '#include "lib.h"',
    "#define MAIN_OFFSET 10",
)


def _source_directives(text: str, directives: tuple[str, ...]) -> list[str]:
    return [line for line in text.split("\n") if line in directives]


def _c_source_includes(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith("#include") and line.endswith('helper.c"')]


def test_every_unit_carries_the_whole_directive_list_in_source_order(compiler: str, tmp_path, request):
    """A `#define` / `#include` pair split across groups keeps its order in every unit.

    Each unit, the runtime unit included, carries the whole program's directive
    list in source order, so it compiles as strict C11 and the program runs.
    Macros are never deduplicated, identical includes are, and an imported C
    source stays in its own group's unit. A warm build after a directive edit
    equals a cold one.
    """
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main"]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc"))]
    source = (tmp_path / "program").resolve()
    for name, text in _DIRECTIVE_PROGRAM.items():
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_text(text)

    def build(output: Path, cache: Path, *mode: str) -> dict[str, str]:
        output.mkdir(parents=True)
        completed = subprocess.run(
            [*command, "Main.btrc", "-o", str(output / "p.c"), "--emit-units", str(output / "p"), *mode],
            cwd=source,
            env={
                **os.environ,
                "BTRC_HOME": str(ROOT / "src"),
                "PYTHONPATH": str(ROOT),
                "BTRC_CACHE_DIR": str(cache),
            },
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        return {path.name: path.read_text() for path in sorted(output.glob("p*.c"))}

    def check(texts: dict[str, str], whole: str, directives: tuple[str, ...]) -> None:
        for name, text in texts.items():
            assert _source_directives(text, directives) == list(directives), name
        # Only Probe's unit includes the C source, at its place in the whole list.
        including = [name for name, text in texts.items() if _c_source_includes(text)]
        assert len(including) == 1 and ".unit-Probe-" in including[0], including
        expected = [line for line in whole.split("\n") if line in directives or line in _c_source_includes(whole)]
        assert _source_directives(texts[including[0]], (*directives, *_c_source_includes(whole))) == expected

    root = tmp_path.resolve()
    whole = build(root / "whole", root / "whole-cache")
    assert list(whole) == ["p.c"]
    assert _source_directives(whole["p.c"], _DIRECTIVES) == list(_DIRECTIVES)
    assert len(_c_source_includes(whole["p.c"])) == 1
    units = build(root / "units", root / "cache", "--module-units")
    assert len([name for name in units if ".unit-" in name]) >= 3
    check(units, whole["p.c"], _DIRECTIVES)

    # Every key covers the directive text: a warm build after a directive edit
    # gives the same C as a cold build.
    main = source / "Main.btrc"
    main.write_text(main.read_text().replace("#define MAIN_OFFSET 10", "#define MAIN_OFFSET 20"))
    warm = build(root / "warm", root / "cache", "--module-units")
    assert warm == build(root / "cold", root / "cold-cache", "--module-units")
    edited = (*_DIRECTIVES[:-1], "#define MAIN_OFFSET 20")
    check(warm, whole["p.c"].replace("#define MAIN_OFFSET 10", "#define MAIN_OFFSET 20"), edited)

    if not HOST_C_COMPILERS:
        pytest.skip("module-unit compilation needs a C compiler")
    for c_compiler in HOST_C_COMPILERS:
        objects = []
        for name in units:
            objects.append(root / "units" / f"{name}.{Path(c_compiler).name}.o")
            compiled = subprocess.run(
                [
                    c_compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{source}",
                    f"-I{source / 'Probe'}",
                    "-c",
                    str(root / "units" / name),
                    "-o",
                    str(objects[-1]),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert compiled.returncode == 0, (c_compiler, name, compiled.stderr)
        executable = root / f"program-{Path(c_compiler).name}"
        linked = subprocess.run(
            [c_compiler, *map(str, objects), "-o", str(executable), "-lm", "-lpthread"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert linked.returncode == 0, (c_compiler, linked.stderr)
        ran = subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=30)
        assert ran.stdout == "3 12 16\n", c_compiler


def test_package_defines_reach_headers_and_invalidate_units(compiler: str, tmp_path, request):
    source = tmp_path / "source"
    source.mkdir()
    (source / "Main.btrc").write_text('import "./Probe.btrc";\nint main() { return probe() == 8 ? 0 : 1; }\n')
    (source / "Probe.btrc").write_text(
        '#include "Feature.h"\nextern int featureValue();\nint probe() { return featureValue(); }\n'
    )
    (source / "Feature.h").write_text(
        "#ifndef FEATURE_LEVEL\n#error missing package definition\n#endif\n"
        "#ifdef INACTIVE_FEATURE\n#error inactive target definition\n#endif\n"
        "static inline int featureValue(void) { return FEATURE_LEVEL + BARE_SWITCH; }\n"
    )
    manifest = source / "btrc.toml"

    def define(level):
        manifest.write_text(
            'manifest-version = 1\n[package]\nname = "features"\n'
            f'[[native.defines]]\nname = "FEATURE_LEVEL"\nvalue = "{level}"\nmodules = ["Probe"]\n'
            '[[native.defines]]\nname = "BARE_SWITCH"\nvalue = ""\nmodules = ["Probe"]\n'
            '[[native.defines]]\nname = "INACTIVE_FEATURE"\nvalue = "1"\nos = ["android"]\n'
        )

    def build(name, cache, module_units):
        output = tmp_path / name
        output.mkdir()
        result = subprocess.run(
            [
                *_timing_command(compiler, request),
                str(source / "Main.btrc"),
                "-o",
                str(output / "p.c"),
                "--emit-units",
                str(output / "p"),
                *(["--module-units", "--jobs", "1"] if module_units else []),
            ],
            cwd=source,
            env={
                **os.environ,
                "BTRC_HOME": str(ROOT / "src"),
                "PYTHONPATH": str(ROOT),
                "BTRC_CACHE_DIR": str(tmp_path / cache),
            },
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stderr
        texts = {path.name: path.read_text() for path in sorted(output.glob("p*.c"))}
        for text in texts.values():
            assert text.index("#define FEATURE_LEVEL ") < text.index("#include")
            assert "#define BARE_SWITCH 1" in text
            assert "#define INACTIVE_FEATURE" not in text
        return output, texts

    define(7)
    whole, _ = build("whole", "whole-cache", False)
    units, _ = build("units", "cache", True)
    for output in (whole, units):
        executable = output / "program"
        compiled = subprocess.run(
            [
                *C_COMPILER,
                "-std=c11",
                "-pedantic-errors",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{source}",
                *map(str, sorted(output.glob("p*.c"))),
                "-o",
                str(executable),
                "-lm",
                "-lpthread",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert compiled.returncode == 0, compiled.stderr
        subprocess.run([str(executable)], check=True, timeout=30)
    define(11)
    _, warm = build("warm", "cache", True)
    _, cold = build("cold", "cold-cache", True)
    assert warm == cold
    assert all("#define FEATURE_LEVEL 11" in text for text in warm.values())


_DYING_WORKER = """
import os, sys
from pathlib import Path
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ForkedModuleUnitWorkers
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache

start = ForkedModuleUnitWorkers.start.__func__

def dying(cls, count, handler):
    def answer(request):
        if request["op"] == "lower" and request["group"].endswith("Catalog.btrc"):
            os._exit(9)
        return handler(request)
    return start(cls, count, answer)

ForkedModuleUnitWorkers.start = classmethod(dying)
entry, output = Path(sys.argv[1]), Path(sys.argv[2])
result = Compiler(cache=CompilerCache()).compile(
    entry.read_text(),
    str(entry),
    CompilerOptions(units_prefix=str(output / "program"), module_units=True, module_jobs=3),
)
print(result.failure.message if result.failure is not None else "no failure")
try:
    os.waitpid(-1, os.WNOHANG)
    print("workers left behind")
except ChildProcessError:
    print("no workers left")
"""


def test_a_dying_worker_fails_the_compile_and_leaves_no_workers(tmp_path):
    """A worker that exits mid-compile fails the build; every worker is reaped."""
    workspace = _Workspace(tmp_path.resolve())
    output = workspace.root / "out"
    output.mkdir()
    completed = subprocess.run(
        [sys.executable, "-c", _DYING_WORKER, str(workspace.modules / "CatalogMain.btrc"), str(output)],
        cwd=ROOT,
        env={**os.environ, "BTRC_CACHE_DIR": str(workspace.cache), "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert lines[0] == "module-unit worker failed: worker exited with status 9"
    assert lines[1] == "no workers left"
    assert not list(output.glob("program*.c"))


_RAISING_WORKER = """
import os, sys
from pathlib import Path
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ModuleUnitWorker
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.ir.lowering.types import CodegenError

answer = ModuleUnitWorker._answer

def raising(self, request):
    if request["op"] == "lower" and request["group"].endswith("Catalog.btrc"):
        raise CodegenError("probe diagnostic from Catalog")
    return answer(self, request)

ModuleUnitWorker._answer = raising
entry, output, jobs = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
result = Compiler(cache=CompilerCache()).compile(
    entry.read_text(),
    str(entry),
    CompilerOptions(units_prefix=str(output / "program"), module_units=True, module_jobs=jobs, use_cache=False),
)
print(result.failure.message if result.failure is not None else "no failure")
"""


def test_a_raising_request_surfaces_its_own_diagnostic_from_any_pool(tmp_path):
    """What a worker's request raises reaches the owner unchanged, whether the
    worker is the owner itself or a forked process: the same failure text."""
    workspace = _Workspace(tmp_path.resolve())
    messages = []
    for jobs in (1, 3):
        output = workspace.root / f"out-{jobs}"
        output.mkdir()
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                _RAISING_WORKER,
                str(workspace.modules / "CatalogMain.btrc"),
                str(output),
                str(jobs),
            ],
            cwd=ROOT,
            env={**os.environ, "BTRC_CACHE_DIR": str(workspace.cache), "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        messages.append(completed.stdout.splitlines()[0])
    assert "probe diagnostic from Catalog" in messages[0]
    assert messages[0] == messages[1]


def test_workers_never_fork_beside_another_thread():
    """A lock another thread held at the fork would stay held in the worker,
    so the pool refuses to start and the owner lowers inline instead."""
    release = threading.Event()
    thread = threading.Thread(target=release.wait, daemon=True)
    thread.start()
    try:
        assert ForkedModuleUnitWorkers.other_threads_running()
        assert ForkedModuleUnitWorkers.start(2, lambda request: request) is None
    finally:
        release.set()
        thread.join(timeout=10)


def test_suggested_worker_count_matches_the_self_hosted_pools():
    """btrcc's pools suggest one worker per online CPU, at most four."""
    assert ForkedModuleUnitWorkers.suggested_count() == max(1, min(os.sysconf("SC_NPROCESSORS_ONLN"), 4))


_EFFECTS_PROGRAM = {
    "Lib.btrc": """import Library.Vector;

void fill(Vector<int> values) { values.push(1); }

void grow(Vector<int> values) {
	values.push(2);
	values.push(3);
}

void mayThrow(int count) {
	if (count > 100) { throw "too many"; }
}
""",
    "UseFill.btrc": """import Library.Vector;

import ./Lib.btrc;

int useFill() {
	Vector<int> values = [];
	try {
		fill(values);
		mayThrow(values.len);
	} catch (string error) {
		return -1;
	}
	return values.len;
}
""",
    "UseGrow.btrc": """import Library.Vector;

import ./Lib.btrc;

int useGrow() {
	Vector<int> values = [];
	try {
		grow(values);
		mayThrow(values.len);
	} catch (string error) {
		return -1;
	}
	return values.len;
}
""",
    "Main.btrc": """import ./UseFill.btrc;
import ./UseGrow.btrc;

int main() {
	print(f"{useFill()} {useGrow()}");
	return 0;
}
""",
}


def test_an_effect_changing_edit_matches_a_clean_build(compiler: str, tmp_path, request):
    """Editing a callee's setjmp effect re-solves with unchanged summaries intact.

    `fill` stops writing through its argument, so the reused `UseFill` unit
    consulted a summary that moved and is lowered again, which solves the
    program a second time. The unchanged summary of `grow`, consulted by the
    reused `UseGrow`, must survive that second solve: `UseGrow` stays reused
    and the incremental build matches a clean one, whose functions are in turn
    the ones a whole-program build emits.
    """
    source = (tmp_path / "program").resolve()
    source.mkdir()
    for name, text in _EFFECTS_PROGRAM.items():
        (source / name).write_text(text)

    def build(output: Path, cache: Path, monkeypatch, module_units: bool = True) -> tuple[dict[str, str], set[str]]:
        output.mkdir(parents=True)
        if compiler == "python":
            monkeypatch.setenv("BTRC_CACHE_DIR", str(cache))
            main = source / "Main.btrc"
            result = Compiler(cache=CompilerCache()).compile(
                main.read_text(),
                str(main),
                CompilerOptions(
                    units_prefix=str(output / "p"), module_units=module_units, generated_c_path=str(output / "p.c")
                ),
            )
            assert result.failure is None, result.failure
            units = {"p.c": result.c_source, **dict(zip(result.unit_names, result.c_units, strict=True))}
            return units, _names(result.module_units_lowered)
        completed = subprocess.run(
            [
                str(request.getfixturevalue("immutable_btrcc")),
                "Main.btrc",
                "-o",
                str(output / "p.c"),
                "--emit-units",
                str(output / "p"),
                *(["--module-units", "--jobs", "1"] if module_units else []),
            ],
            cwd=source,
            env={**os.environ, "BTRC_HOME": str(ROOT / "src"), "BTRC_TIMING": "1", "BTRC_CACHE_DIR": str(cache)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        units = {path.name: path.read_text() for path in sorted(output.glob("p*.c"))}
        if not module_units:
            return units, {}
        lowered = {"lowered": int(completed.stderr.split("module-units=lowered:", 1)[1].split(",", 1)[0])}
        return units, lowered

    monkeypatch = request.getfixturevalue("monkeypatch")
    cache = tmp_path.resolve() / "cache"
    build(tmp_path / "cold", cache, monkeypatch)
    lib = source / "Lib.btrc"
    lib.write_text(
        lib.read_text().replace(
            "void fill(Vector<int> values) { values.push(1); }",
            # No longer writing through its argument, and reaching nothing new:
            # the program facts every key digests stay the same.
            "void fill(Vector<int> values) { mayThrow(values.len); }",
        )
    )
    incremental, lowered = build(tmp_path / "incremental", cache, monkeypatch)
    if compiler == "python":
        assert lowered == {"Lib.btrc", "UseFill.btrc"}
    else:
        # The edited group and the consumer whose consulted summary moved.
        assert lowered == {"lowered": 2}
    clean, _ = build(tmp_path / "clean", tmp_path.resolve() / "fresh-cache", monkeypatch)
    assert incremental == clean
    whole, _ = build(tmp_path / "whole", tmp_path.resolve() / "whole-cache", monkeypatch, module_units=False)
    bodies = _function_bodies(clean.values())
    assert "useGrow" in bodies and "useFill" in bodies
    assert bodies == _function_bodies(whole.values())


def test_native_plan_rebuilds_only_the_edited_unit(compiler: str, tmp_path, request):
    """The real CLI, link plan, native object cache and linker, clean then edited.

    A clean build compiles every unit; an unchanged rebuild compiles none; a
    private body edit recompiles only the edited group's unit and relinks,
    and the program runs with the edit.
    """
    clang = HOST_CLANG
    if clang is None:
        pytest.skip("the native plan builder needs clang")
    if compiler == "python":
        command = [sys.executable, "-m", "src.compiler.python.main"]
    else:
        command = [str(request.getfixturevalue("immutable_btrcc"))]
    from src.compiler.python.frontend.packages import PackageTarget

    target = PackageTarget.parse(None)
    workspace = _Workspace(tmp_path.resolve())
    output = workspace.root / "build"
    output.mkdir()
    environment = {
        **os.environ,
        "BTRC_HOME": str(ROOT / "src"),
        "PYTHONPATH": str(ROOT),
        "BTRC_CACHE_DIR": str(workspace.cache),
    }
    # The fixture's own header is a plain include, not a package binding.
    request.getfixturevalue("monkeypatch").setenv("CPATH", str(workspace.modules / "Shapes"))

    def build() -> tuple[set[str], str]:
        transpiled = subprocess.run(
            [
                *command,
                "CatalogMain.btrc",
                "--target",
                f"{target.operating_system}-{target.architecture}",
                "-o",
                str(output / "program.c"),
                "--emit-units",
                str(output / "program"),
                "--emit-link-plan",
                str(output / "program.link.json"),
                "--module-units",
                "--jobs",
                "2",
            ],
            cwd=workspace.modules,
            env=environment,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert transpiled.returncode == 0, transpiled.stderr
        report = NativePlanBuilder().build(
            plan_path=output / "program.link.json",
            generated_c=output / "program.c",
            output=output / "program",
            cc=clang,
            object_cache=workspace.root / "objects",
        )
        compiled = {Path(unit.source).name for unit in report.units if unit.cache_status != "hit"}
        ran = subprocess.run([str(output / "program")], capture_output=True, text=True, timeout=30, check=True)
        return compiled, ran.stdout

    compiled, stdout = build()
    assert "program.c" in compiled and len(compiled) > 3
    assert stdout.startswith("catalog skipped empty shape")
    assert build()[0] == set()
    workspace.edit("Catalog/Catalog.btrc", 'print(f"catalog skipped {error}");', 'print(f"catalog skip: {error}");')
    compiled, stdout = build()
    assert len(compiled) == 1 and next(iter(compiled)).startswith("program.unit-Catalog-")
    assert stdout.startswith("catalog skip: empty shape")


def test_cancelling_the_owner_leaves_no_workers(tmp_path, immutable_btrcc):
    """Terminating a compile mid-lowering ends its workers and publishes nothing.

    Workers see the end of their request pipe once the owner is gone, or fail
    writing a reply to it, and exit; no output or partial unit is written.
    """
    if shutil.which("pgrep") is None:
        pytest.skip("finding worker processes needs pgrep")
    from src.compiler.python.frontend.packages import PackageTarget

    host = PackageTarget.parse(None)
    output = tmp_path.resolve()
    owner = subprocess.Popen(
        [
            str(immutable_btrcc),
            "src/compiler/btrc/BtrccMain.btrc",
            # HostWorkerPools selects its provider by target, which btrcc
            # never infers.
            "--target",
            f"{host.operating_system}-{host.architecture}",
            "-o",
            str(output / "program.c"),
            "--emit-units",
            str(output / "program"),
            "--module-units",
            "--jobs",
            "2",
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src"), "BTRC_CACHE_DIR": str(output / "cache")},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def workers() -> list[str]:
        found = subprocess.run(["pgrep", "-P", str(owner.pid)], capture_output=True, text=True, timeout=TOOL_TIMEOUT)
        return found.stdout.split()

    try:
        deadline = time.monotonic() + 240
        while not workers():
            assert owner.poll() is None, "the compile finished before its workers could be observed"
            assert time.monotonic() < deadline, "no module-unit workers started"
            time.sleep(0.2)
        started = workers()
        owner.send_signal(signal.SIGTERM)
        owner.wait(timeout=30)
        deadline = time.monotonic() + 120
        alive = started
        while alive and time.monotonic() < deadline:
            time.sleep(0.5)
            alive = [
                pid
                for pid in started
                if subprocess.run(["kill", "-0", pid], capture_output=True, timeout=TOOL_TIMEOUT).returncode == 0
            ]
        assert not alive, f"workers outlived their owner: {alive}"
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait()
    assert not list(output.glob("program*.c"))


# Corpus programs that once failed only as module units: an enum whose members
# share an explicit value (its `_toString` was a switch with duplicate labels),
# and a program whose C type came from a runtime helper header that only another
# unit includes. The module-unit corpus run is opt-in, so these keep running.
_MODULE_UNIT_CORPUS_REGRESSIONS = ("enums/EnumDuplicateExplicitValues.btrc", "stdlib/ChildProcessClosedFds.btrc")


@pytest.mark.parametrize("program", _MODULE_UNIT_CORPUS_REGRESSIONS)
def test_module_unit_corpus_regressions_build_and_run(compiler: str, program: str, tmp_path, request):
    """Each program builds as module units, links, runs and matches its golden."""
    path = os.path.join(runner.BTRC_TEST_DIR, program)
    if compiler == "python":
        units, warnings = runner._transpile_python_module_units(path, str(tmp_path))
    else:
        units, warnings = runner._transpile_btrc_module_units(request.getfixturevalue("btrcc_bin"), path, str(tmp_path))
    assert len(units) > 1
    assert warnings == runner.expected_warnings(path)
    runner._compile_run_check(units, path, program)


@pytest.mark.parametrize("flow_roots", [None, {"entry"}, set()], ids=["all", "safety-root", "no-safety-roots"])
def test_unit_flow_roots_release_unused_facts_without_losing_recursive_summaries(flow_roots, monkeypatch):
    """A retained caller must observe changed effects through unretained recursion.

    Weak references prove that non-root per-node results become collectible;
    checking just the returned contexts would miss an internal retained cache.
    """
    module = IRModule()
    for name, callees in {
        "entry": ["middle"],
        "middle": ["recursive"],
        "recursive": ["middle", "foreignWrite"],
    }.items():
        module.function_defs.append(
            IRFunctionDef(
                name,
                CType("void"),
                [IRParam(CType("int*"), "value")],
                IRBlock([IRExprStmt(IRCall(callee, [IRVar("value")])) for callee in callees]),
            )
        )
    module.function_decls.append(IRFunctionDecl("foreignWrite", CType("void"), [IRParam(CType("int*"), "value")]))
    expected_roots = {"entry", "middle", "recursive"} if flow_roots is None else set(flow_roots)
    reference = SetjmpUnitSolver(module)
    candidate = SetjmpUnitSolver(module, flow_roots=flow_roots)
    if flow_roots is not None:
        flow_roots.clear()  # The caller cannot change an existing solver's policy.
    original = ExceptionLowerer.analyze_pointer_flow
    observations = {}

    def observe(function, globals_by_name, type_facts, catalog):
        flow = original(function, globals_by_name, type_facts, catalog)
        observations.setdefault(function.name, []).append(weakref.ref(flow))
        return flow

    for external in [FunctionEffect(), FunctionEffect(writes=frozenset({ParameterEffect(0)}))]:
        solved = {"foreignWrite": external}
        reference_effects, reference_consulted = reference.solve(solved)
        observations.clear()
        with monkeypatch.context() as context:
            context.setattr(ExceptionLowerer, "analyze_pointer_flow", staticmethod(observe))
            effects, consulted = candidate.solve(solved)
        assert set(effects) == expected_roots
        assert consulted == reference_consulted == {"foreignWrite"}
        assert candidate.summaries() == reference.summaries()
        assert all(summary.writes == external.writes for summary in candidate.summaries().values())
        for name, observed in observations.items():
            assert bool(observed[-1]()) == (name in expected_roots)
            if name not in expected_roots:
                assert all(result() is None for result in observed)
        for name, effects_for_name in effects.items():
            assert effects_for_name.flow.writes == reference_effects[name].flow.writes


@pytest.mark.parametrize("location", ["direct", "call-argument", "array-bound"])
def test_unit_flow_roots_cover_every_setjmp_safety_location(location):
    call = IRCall("setjmp", [IRVar("environment")])
    if location == "direct":
        statement = IRExprStmt(call)
    elif location == "call-argument":
        statement = IRExprStmt(IRCall("consume", [call]))
    else:
        statement = IRVarDecl(CType("int"), "values", array_size=call)
    module = IRModule()
    module.function_defs = [
        IRFunctionDef("protected", CType("void"), body=IRBlock([statement])),
        IRFunctionDef("ordinary", CType("void"), body=IRBlock([])),
    ]
    assert ModuleUnitCompiler.setjmp_flow_functions(module) == {"protected"}


def test_strict_stdlib_validation_has_separate_module_units(tmp_path, monkeypatch):
    workspace = _Workspace(tmp_path)
    normal, normal_units = workspace.build("CatalogMain.btrc", tmp_path / "normal", monkeypatch)
    assert normal.module_units_lowered and not normal.module_units_reused
    strict, strict_units = workspace.build("CatalogMain.btrc", tmp_path / "strict", monkeypatch, stdlib_strict=True)
    assert strict.module_units_lowered == normal.module_units_lowered
    assert not strict.module_units_reused
    repeated, repeated_units = workspace.build("CatalogMain.btrc", tmp_path / "repeat", monkeypatch, stdlib_strict=True)
    assert repeated.module_units_reused and not repeated.module_units_lowered
    assert normal_units == strict_units == repeated_units


def test_selfhost_strict_stdlib_validation_has_separate_records(tmp_path, immutable_btrcc):
    if not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("self-hosted artifact reuse needs the native header reader identity")
    workspace = _Workspace(tmp_path.resolve())
    normal, normal_units, _, normal_log = _btrcc_build_logged(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "normal"
    )
    strict, strict_units, _, strict_log = _btrcc_build_logged(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "strict", stdlib_strict=True
    )
    assert normal == strict == {"lowered": 6, "reused": 0}
    assert _validation_records(strict_log) == _validation_records(normal_log)
    assert _validation_records(strict_log)["replayed"] == 0
    repeated, repeated_units, _, repeated_log = _btrcc_build_logged(
        immutable_btrcc, workspace, "CatalogMain.btrc", workspace.root / "repeat", stdlib_strict=True
    )
    assert repeated == {"lowered": 0, "reused": 6}
    assert _validation_records(repeated_log)["replayed"] > 0
    assert normal_units == strict_units == repeated_units


def _compile_and_run_module_frontends(source, tmp_path, immutable_btrcc, expected_stdout):
    sanitizer = require_sanitizers(tmp_path)
    generated = {}
    for frontend, command in (
        ("reference", [sys.executable, "-m", "src.compiler.python.main"]),
        ("selfhost", [str(immutable_btrcc)]),
    ):
        output = tmp_path.resolve() / frontend
        output.mkdir()
        compiled = subprocess.run(
            [
                *command,
                str(source / "Main.btrc"),
                "--strict-imports",
                "--no-cache",
                "--module-units",
                "--jobs",
                "1",
                "--emit-units",
                str(output / "program"),
                "-o",
                str(output / "program.c"),
            ],
            cwd=ROOT,
            env={**os.environ, "BTRC_HOME": str(ROOT / "src"), "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert compiled.returncode == 0, compiled.stderr
        units = sorted(output.glob("program*.c"))
        generated[frontend] = {unit.name: unit.read_text() for unit in units}
        for mode, compiler, flags, environment in (
            ("strict", C_COMPILER, ["-O2"], None),
            (
                "sanitized",
                sanitizer.command,
                ["-O1", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"],
                sanitizer.environment,
            ),
        ):
            assert compiler is not None, "module qualification requires a C compiler"
            executable = output / mode
            built = subprocess.run(
                [
                    *compiler,
                    "-std=c11",
                    "-pedantic-errors",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    *flags,
                    *map(str, units),
                    "-lm",
                    "-lpthread",
                    "-o",
                    str(executable),
                ],
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
            )
            assert built.returncode == 0, built.stderr
            ran = subprocess.run(
                [str(executable)],
                env=sanitizer_environment(sanitizer) if mode == "sanitized" else None,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert ran.returncode == 0, ran.stderr
            assert ran.stdout == expected_stdout
    return generated


@pytest.mark.parametrize(
    ("payload", "values", "macro"),
    [
        ("uint", "uint first = 1u; uint second = 7u;", "ATOMIC_INT_LOCK_FREE"),
        (
            "const int*",
            "int firstValue = 1; int secondValue = 7; const int* first = &firstValue; const int* second = &secondValue;",
            "ATOMIC_POINTER_LOCK_FREE",
        ),
    ],
)
def test_module_atomic_types_keep_their_lock_free_proofs(tmp_path, immutable_btrcc, payload, values, macro):
    source = tmp_path.resolve() / "source"
    source.mkdir()
    (source / "Counter.btrc").write_text(
        f"{payload} readCounter(Atomic<{payload}>* counter) {{ return counter->load(MemoryOrder.ACQUIRE); }}\n"
    )
    (source / "Main.btrc").write_text(
        f"""
        #include <assert.h>
        import ./Counter.btrc;
        int main() {{
            {values}
            Atomic<{payload}> counter = Atomic(first);
            assert(readCounter(&counter) == first);
            counter.store(second, MemoryOrder.RELEASE);
            assert(readCounter(&counter) == second);
            print("PASS");
            return 0;
        }}
        """
    )
    generated = _compile_and_run_module_frontends(source, tmp_path, immutable_btrcc, "PASS\n")
    for frontend, units in generated.items():
        atomic_units = [text for name, text in units.items() if ".unit-Main-" in name or ".unit-Counter-" in name]
        assert len(atomic_units) == 2, frontend
        for text in atomic_units:
            assert text.count("__btrc_atomic_lock_free_") == 1, frontend
            assert f"{macro} == 2" in text, frontend


@pytest.mark.parametrize("generic", [False, True])
def test_shared_span_callback_layouts_keep_frontend_order(tmp_path, immutable_btrcc, generic):
    source = tmp_path.resolve() / "source"
    source.mkdir()
    (source / "Shared.btrc").write_text(
        "typedef RealtimeFunction<int, Span<int>, Span<const int>> Processor;\n"
        "@realtime int process(Span<int> values, Span<const int> source) { return 0; }\n"
        "class Holder {\n"
        "    public Processor callback;\n"
        "    public int value;\n"
        "    public Holder(int value) { self.callback = process; self.value = value; }\n"
        "}\n"
    )
    local_type = "Box<int>" if generic else "Marker"
    declaration = (
        "class Box<T> { public T value; public Box(T value) { self.value = value; } }"
        if generic
        else "class Marker { public int value; public Marker(int value) { self.value = value; } }"
    )
    (source / "Local.btrc").write_text(
        "import ./Shared.btrc;\n" + declaration + "\n"
        "int sample() {\n"
        "    Holder holder = new Holder(15);\n"
        f"    {local_type} marker = new {local_type}(7);\n"
        "    return holder.value + marker.value;\n"
        "}\n"
    )
    (source / "Main.btrc").write_text("import ./Local.btrc;\nint main() { print(sample()); return 0; }\n")
    generated = _compile_and_run_module_frontends(source, tmp_path, immutable_btrcc, "22\n")
    local_units = {
        frontend: next(text for name, text in units.items() if ".unit-Local-" in name)
        for frontend, units in generated.items()
    }
    for frontend, text in local_units.items():
        layouts = re.findall(r"^struct (\w+) \{", text, re.MULTILINE)
        spans = [name for name in layouts if name.startswith(("btrc_Span_", "btrc_ZQgb8_5370616e"))]
        assert len(spans) == 2, (frontend, layouts)
        assert "const int* data;" in text and "int* data;" in text
    assert local_units["reference"] == local_units["selfhost"]


def _compile_and_run_native_frontends(source, tmp_path, immutable_btrcc, expected_stdout, *, module_units):
    NativeBindingPackage.require_reader()
    sanitizer = require_sanitizers(tmp_path)
    root = tmp_path.resolve()
    generated = {}
    for frontend, compiler in (
        ("reference", [sys.executable, "-m", "src.compiler.python.main"]),
        ("selfhost", [str(immutable_btrcc)]),
    ):
        output = root / frontend
        output.mkdir()
        c_source, plan = output / "program.c", output / "program.json"
        compiled = subprocess.run(
            [
                *compiler,
                str(source / "Main.btrc"),
                "--strict-imports",
                "--no-cache",
                *(["--module-units", "--jobs", "1", "--emit-units", str(output / "program")] if module_units else []),
                "--emit-link-plan",
                str(plan),
                "-o",
                str(c_source),
            ],
            cwd=ROOT,
            env={**os.environ, "BTRC_HOME": str(ROOT / "src"), "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert compiled.returncode == 0, compiled.stderr
        generated[frontend] = {path.name: path.read_bytes() for path in output.glob("program*.c")}
        for mode, compiler, optimization, flags, environment in (
            ("strict", C_COMPILER, 2, [], None),
            (
                "sanitized",
                sanitizer.command,
                1,
                ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"],
                sanitizer.environment,
            ),
        ):
            assert compiler is not None, "native module qualification requires a C compiler"

            def run_build(command, *, environment=environment, **kwargs):
                kwargs["timeout"] = 180
                if environment is not None:
                    kwargs["env"] = environment
                return subprocess.run(command, **kwargs)

            executable = output / mode
            NativePlanBuilder(runner=run_build).build(
                plan_path=plan,
                generated_c=c_source,
                output=executable,
                cc=compiler,
                optimization=optimization,
                jobs=1,
                compile_flags=["-pedantic-errors", "-Wall", "-Wextra", "-Werror", *flags],
                link_flags=flags,
            )
            ran = subprocess.run(
                [str(executable)],
                env=sanitizer_environment(sanitizer) if mode == "sanitized" else None,
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert ran.returncode == 0 and ran.stdout == expected_stdout, (frontend, mode, ran.stdout, ran.stderr)
    return generated


@pytest.mark.parametrize(
    "header_order,symbol_order,resource_order",
    [
        (("Gamma", "Beta", "Alpha"), ("Alpha", "Beta", "Gamma"), ("Beta", "Gamma", "Alpha")),
        (("Alpha", "Beta", "Gamma"), ("Alpha", "Beta", "Gamma"), ("Beta", "Gamma", "Alpha")),
        (("Gamma", "Beta", "Alpha"), ("Gamma", "Beta", "Alpha"), ("Beta", "Gamma", "Alpha")),
        (("Gamma", "Beta", "Alpha"), ("Alpha", "Beta", "Gamma"), ("Alpha", "Gamma", "Beta")),
    ],
    ids=["mixed-order", "reverse-header", "reverse-symbols", "reverse-resources"],
)
def test_native_resource_shared_declarations_keep_frontend_order(
    tmp_path, immutable_btrcc, header_order, symbol_order, resource_order
):
    root = tmp_path.resolve()
    source = root / "src"
    source.mkdir()
    header = "#include <stdlib.h>\n#include <assert.h>\n"
    for resource in header_order:
        header += (
            f"typedef struct {resource}Storage {{ int references; int value; }} *{resource}Ref;\n"
            f"static inline {resource}Ref {resource}Create(int value) {{\n"
            f"    {resource}Ref item = malloc(sizeof(*item)); assert(item);\n"
            "    item->references = 1; item->value = value; return item;\n}\n"
            f"static inline void {resource}Retain({resource}Ref item) {{\n"
            "    assert(item && item->references > 0); ++item->references;\n}\n"
            f"static inline void {resource}Release({resource}Ref item) {{\n"
            "    assert(item && item->references > 0); if (--item->references == 0) { free(item); }\n}\n"
            f"static inline int {resource}Read({resource}Ref item) {{ assert(item); return item->value; }}\n"
        )
    (root / "Resources.h").write_text(header)
    symbols = [name + suffix for name in symbol_order for suffix in ("Ref", "Create", "Read", "Retain", "Release")]
    manifest = (
        'manifest-version = 1\n[package]\nname = "nativeOrder"\n'
        '[[native.bindings]]\nmodule = "Resources"\nheader = "Resources.h"\n'
        'language = "c"\nstandard = "c11"\n'
        f"symbols = {json.dumps(symbols)}\n"
        f"owned-results = {json.dumps([name + 'Create' for name in symbol_order])}\n"
        f"borrowed-parameters = {json.dumps([name + 'Read.item' for name in symbol_order])}\n"
    )
    for resource in resource_order:
        manifest += (
            f"[native.bindings.resources.{resource}Ref]\n"
            'ownership = "reference-counted"\n'
            f'retain = "{resource}Retain"\nrelease = "{resource}Release"\n'
        )
    (root / "btrc.toml").write_text(manifest)
    (source / "Resources.btrc").write_text("// Declarations come from Resources.h.\n")
    (source / "Shared.btrc").write_text(
        "import ./Resources.btrc;\n"
        "class Holder {\n"
        "    public GammaRef? gamma; public BetaRef? beta; public AlphaRef? alpha; public int value;\n"
        "    public Holder() {\n"
        "        self.gamma = GammaCreate(7); self.beta = BetaCreate(15); self.alpha = AlphaCreate(20);\n"
        "        self.value = GammaRead(self.gamma) + BetaRead(self.beta) + AlphaRead(self.alpha);\n"
        "    }\n}\n"
        "Holder makeHolder() { return new Holder(); }\n"
    )
    (source / "Local.btrc").write_text(
        "import ./Shared.btrc;\nint sample() { Holder holder = makeHolder(); return holder.value; }\n"
    )
    (source / "Main.btrc").write_text("import ./Local.btrc;\nint main() { print(sample()); return 0; }\n")
    generated = _compile_and_run_native_frontends(source, tmp_path, immutable_btrcc, "42\n", module_units=True)
    local_units = {
        frontend: next(text for name, text in units.items() if ".unit-Local-" in name)
        for frontend, units in generated.items()
    }
    for text in local_units.values():
        forwards = re.findall(rb"^typedef struct (__btrc_native_\w+) ", text, re.MULTILINE)
        assert set(forwards) == {b"__btrc_native_AlphaRef", b"__btrc_native_BetaRef", b"__btrc_native_GammaRef"}
    assert local_units["reference"] == local_units["selfhost"]


@pytest.mark.parametrize("status_release", [False, True], ids=["void", "status"])
@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
def test_unique_resource_lifetime_helpers_match_frontends(tmp_path, immutable_btrcc, status_release, module_units):
    folder = tmp_path.resolve()
    source = folder / "src"
    source.mkdir()
    close_type = "int" if status_release else "void"
    (folder / "Resource.h").write_text(
        "#ifndef RESOURCE_H\n#define RESOURCE_H\n"
        "typedef struct WidgetStorage { int value; } *WidgetRef;\n"
        "WidgetRef WidgetCreate(int value);\n"
        f"{close_type} WidgetRelease(WidgetRef widget);\n"
        "int WidgetRead(WidgetRef widget);\nint WidgetLive(void);\nint WidgetDestroyed(void);\n#endif\n"
    )
    (source / "Resource.c").write_text(
        '#include "../Resource.h"\n#include <assert.h>\n#include <stdlib.h>\n'
        "static int live = 0, destroyed = 0;\n"
        "WidgetRef WidgetCreate(int value) { if (value < 0) return NULL; WidgetRef widget = malloc(sizeof(*widget)); assert(widget); widget->value = value; ++live; return widget; }\n"
        f"{close_type} WidgetRelease(WidgetRef widget) {{ assert(widget && live > 0); --live; ++destroyed; free(widget);"
        + (" return -37;" if status_release else "")
        + " }\n"
        "int WidgetRead(WidgetRef widget) { return widget ? widget->value : -1; }\n"
        "int WidgetLive(void) { return live; }\nint WidgetDestroyed(void) { return destroyed; }\n"
    )
    (folder / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "uniqueNames"\n'
        '[[native.sources]]\npath = "src/Resource.c"\nlanguage = "c"\nstandard = "c11"\nmodules = ["Resource"]\n'
        '[[native.bindings]]\nmodule = "Resource"\nheader = "Resource.h"\nlanguage = "c"\nstandard = "c11"\n'
        'symbols = ["WidgetRef", "WidgetCreate", "WidgetRelease", "WidgetRead", "WidgetLive", "WidgetDestroyed"]\n'
        'owned-results = ["WidgetCreate"]\nborrowed-parameters = ["WidgetRead.widget"]\n'
        '[native.bindings.resources.WidgetRef]\nownership = "unique"\nrelease = "WidgetRelease"\n'
        + ('release-consumption = "always"\ncleanup-status = "discard"\n' if status_release else "")
    )
    (source / "Resource.btrc").write_text("// Resource.h declarations with a manifest-owned implementation.\n")
    (source / "Shared.btrc").write_text(
        "import ./Resource.btrc;\n"
        "class Holder { public WidgetRef? value; public Holder(int value) { self.value = WidgetCreate(value); } }\n"
        "Holder makeHolder(int value) { return new Holder(value); }\n"
    )
    close = (
        "assert(holder.value.close() == -37 && alias.close() == -37);"
        if status_release
        else "holder.value.close(); alias.close();"
    )
    (source / "Local.btrc").write_text(
        "import ./Resource.btrc;\nimport ./Shared.btrc;\n"
        "void sample() {\n"
        " for (int index = 0; index < 3; index++) { var holder = makeHolder(42); var alias = holder.value;\n"
        "  assert(alias != null && alias.isOpen() && WidgetRead(alias) == 42 && WidgetLive() == 1);\n"
        f"  {close}\n"
        "  assert(!alias.isOpen() && WidgetLive() == 0 && WidgetDestroyed() == index + 1);\n"
        " }\n"
        " assert(WidgetDestroyed() == 3);\n"
        " { var holder = makeHolder(7); assert(WidgetRead(holder.value) == 7 && WidgetLive() == 1); }\n"
        " assert(WidgetLive() == 0 && WidgetDestroyed() == 4);\n"
        ' try { var holder = makeHolder(8); assert(holder.value.isOpen()); throw "expected"; }\n'
        ' catch (string error) { assert(error == "expected"); }\n'
        " assert(WidgetLive() == 0 && WidgetDestroyed() == 5);\n"
        " var absent = WidgetCreate(-1); assert(absent == null && WidgetRead(absent) == -1); WidgetCreate(9);\n"
        " assert(WidgetLive() == 0 && WidgetDestroyed() == 6);\n}\n"
    )
    (source / "Main.btrc").write_text('import ./Local.btrc;\nint main() { sample(); print("PASS"); return 0; }\n')
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    assert generated["reference"] == generated["selfhost"]


@pytest.mark.parametrize("native_binding", [False, True], ids=["extern", "native-binding"])
@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
def test_c_only_imported_module_keeps_its_implementation(tmp_path, immutable_btrcc, native_binding, module_units):
    source = tmp_path / "src"
    source.mkdir()
    (tmp_path / "Counter.h").write_text("int counterNext(void);\n")
    (source / "Counter.c").write_text(
        '#include "../Counter.h"\nstatic int count = 40;\nint counterNext(void) { return ++count; }\n'
    )
    (source / "Counter.btrc").write_text(
        "import ./Counter.c;\n" + ("" if native_binding else "extern int counterNext();\n")
    )
    manifest = 'manifest-version = 1\n[package]\nname = "cOnlyImport"\n'
    if native_binding:
        manifest += '[[native.bindings]]\nmodule = "Counter"\nheader = "Counter.h"\nlanguage = "c"\nstandard = "c11"\nsymbols = ["counterNext"]\n'
    (tmp_path / "btrc.toml").write_text(manifest)
    (source / "Shared.btrc").write_text("import ./Counter.btrc;\nint sharedNext() { return counterNext(); }\n")
    (source / "Main.btrc").write_text(
        'import ./Counter.btrc;\nimport ./Shared.btrc;\nint main() { assert(counterNext() == 41); assert(sharedNext() == 42); assert(counterNext() == 43); print("PASS"); return 0; }\n'
    )
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    for frontend, units in generated.items():
        includes = [
            name for name, content in units.items() if str((source / "Counter.c").resolve()).encode() in content
        ]
        assert len(includes) == 1, (frontend, includes)


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize("addressed", [False, True], ids=["function", "address"])
@pytest.mark.parametrize("generic", [False, True], ids=["class", "generic-class"])
def test_ordered_function_values_normalize_class_signatures(
    tmp_path, immutable_btrcc, module_units, addressed, generic
):
    source = tmp_path.resolve() / "source"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "orderedCallback"\n')
    declaration = "Item<T>" if generic else "Item"
    value_type = "T" if generic else "int"
    payload = "Item<int>" if generic else "Item"
    callback = "&receive" if addressed else "receive"
    (source / "Main.btrc").write_text(
        f"""
        class {declaration} {{
            public {value_type} value;
            public Item({value_type} value) {{ self.value = value; }}
        }}
        static int calls = 0;
        int next() {{ calls++; return calls; }}
        int receive({payload} value) {{ return value.value; }}
        int dispatch(int first, int second, CFunction<int, {payload}> callback, {payload} value) {{
            assert(first == 1 && second == 2);
            return callback(value);
        }}
        int main() {{
            var input = new {payload}(42);
            int output = dispatch(next(), next(), {callback}, input);
            assert(output == 42 && calls == 2);
            print("PASS");
            return 0;
        }}
        """
    )
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    assert generated["selfhost"] == generated["reference"]


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize("volatile", [False, True], ids=["plain", "volatile"])
@pytest.mark.parametrize(
    "declaration,local,argument",
    [
        ("", "Value value = 42;", "&value"),
        ("", "Value value = 42; Pointer pointer = &value;", "pointer"),
        ("", "Value value = 42; Pointer pointer = &value; Pointer* outer = &pointer;", "*outer"),
        (
            "struct Record { Pointer output; };",
            "Value value = 42; Record record = {&value};",
            "record.output",
        ),
        ("Pointer read(Pointer value) { return value; }", "Value value = 42;", "read(&value)"),
        (
            "",
            "Value value = 42; bool condition = true; Pointer first = &value; Pointer second = &value;",
            "condition ? first : second",
        ),
        ("", "Value values[2] = {42, 43};", "values"),
    ],
    ids=["address", "identifier", "dereference", "field", "call-result", "conditional", "array"],
)
def test_ordered_pointer_aliases_preserve_qualifiers(
    tmp_path, immutable_btrcc, module_units, volatile, declaration, local, argument
):
    source = tmp_path.resolve() / "source"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "orderedPointer"\n')
    value_type = "volatile int" if volatile else "unsigned long"
    (source / "Main.btrc").write_text(
        f"""
        typedef {value_type} Value;
        typedef Value* Pointer;
        {declaration}
        static int calls = 0;
        int next() {{ calls++; return calls; }}
        bool capture(int first, int second, Pointer input) {{
            assert(first == 1 && second == 2);
            return *input == 42;
        }}
        int main() {{
            {local}
            assert(capture(next(), next(), {argument}));
            assert(calls == 2);
            print("PASS");
            return 0;
        }}
        """
    )
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    assert generated["selfhost"] == generated["reference"]


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize(
    "local,argument",
    [
        ("", "&handle"),
        ("Slot* pointer = &handle;", "pointer"),
        ("Slot* first = &handle; Slot* second = &handle; bool condition = true;", "condition ? first : second"),
    ],
    ids=["address", "identifier", "conditional"],
)
def test_ordered_const_handle_slots_preserve_mutable_pointees(tmp_path, immutable_btrcc, module_units, local, argument):
    source = tmp_path.resolve() / "source"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "orderedConstSlot"\n')
    (source / "Main.btrc").write_text(
        f"""
        typedef int* Handle;
        typedef const Handle Slot;
        static int calls = 0;
        int next() {{ calls++; return calls; }}
        bool capture(int first, int second, Slot* input) {{
            assert(first == 1 && second == 2 && **input == 42);
            **input = 43;
            return true;
        }}
        int main() {{
            int value = 42;
            Slot handle = &value;
            {local}
            assert(capture(next(), next(), {argument}));
            assert(calls == 2 && value == 43);
            print("PASS");
            return 0;
        }}
        """
    )
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    assert generated["selfhost"] == generated["reference"]


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize("method", [False, True], ids=["function", "method"])
@pytest.mark.parametrize(
    "kind,collection,literal,assertion",
    [
        (
            "Vector",
            "Vector<string>",
            '["first", "second"]',
            'values.len == 2 && values.get(0) == "first" && values.get(1) == "second"',
        ),
        (
            "Map",
            "Map<string, int>",
            '{"first": 41, "second": 42}',
            'values.get("first") == 41 && values.get("second") == 42',
        ),
    ],
    ids=["vector", "map"],
)
def test_collection_construction_cleanup_matches_frontends(
    tmp_path, immutable_btrcc, module_units, method, kind, collection, literal, assertion
):
    source = tmp_path.resolve() / "source"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "collectionConstruction"\n')
    declaration = f"{collection} makeValues() {{ return {literal}; }}"
    if method:
        declaration = "class Factory { public Factory() {} public " + declaration + " }"
    setup = "var factory = new Factory();" if method else ""
    call = "factory.makeValues()" if method else "makeValues()"
    (source / "Main.btrc").write_text(
        f"""
        import Library.{kind};
        {declaration}
        int main() {{
            {setup}
            try {{
                for (int index = 0; index < 3; index++) {{
                    {collection} values = {call};
                    assert({assertion});
                }}
            }} catch (string error) {{ print(error); return 1; }}
            print("PASS");
            return 0;
        }}
        """
    )
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    if not module_units:
        assert generated["reference"] == generated["selfhost"]
        return
    function_name = "Factory_makeValues" if method else "makeValues"
    pattern = re.compile(rb"^\w+\* " + function_name.encode() + rb"\([^;\n]*\) \{\n.*?^\}", re.MULTILINE | re.DOTALL)
    bodies = {}
    for frontend, units in generated.items():
        main = next(text for name, text in units.items() if ".unit-Main-" in name)
        match = pattern.search(main)
        assert match is not None, (frontend, function_name)
        bodies[frontend] = match.group()
    assert bodies["reference"] == bodies["selfhost"]


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize(
    "kind,collection,literal",
    [
        ("Vector", "Vector<Item>", "[new Item(), makeItem(iteration)]"),
        ("Map", "Map<int, Item>", "{1: new Item(), 2: makeItem(iteration)}"),
    ],
    ids=["vector", "map"],
)
def test_collection_construction_cleanup_survives_try_reentry(
    tmp_path, immutable_btrcc, module_units, kind, collection, literal
):
    source = tmp_path.resolve() / "source"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "collectionReentry"\n')
    (source / "Main.btrc").write_text(
        f"""
        import Library.{kind};
        int alive = 0;
        class Item {{
            public Item() {{ alive++; }}
            public void __del__() {{ alive--; }}
        }}
        Item makeItem(int iteration) {{
            if (iteration == 1) {{ throw "expected"; }}
            return new Item();
        }}
        int main() {{
            int caught = 0;
            for (int iteration = 0; iteration < 3; iteration++) {{
                try {{
                    {collection} values = {literal};
                    assert(values.len == 2 && alive == 2);
                }} catch (string error) {{
                    assert(error == "expected");
                    caught++;
                }}
                assert(alive == 0);
            }}
            assert(caught == 1);
            print("PASS");
            return 0;
        }}
        """
    )
    _compile_and_run_native_frontends(source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units)


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize("reverse", [False, True], ids=["source", "reverse"])
@pytest.mark.parametrize("inherited", [False, True], ids=["independent", "inherited"])
def test_interface_declarations_preserve_source_order(tmp_path, immutable_btrcc, module_units, reverse, inherited):
    source = tmp_path / "src"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "interfaceOrder"\n')
    parent = " extends IShort" if inherited else ""
    declarations = ["interface IShort { int read(); }", f"interface ILongName{parent} {{ int write(int value); }}"]
    if reverse:
        declarations.reverse()
    (source / "Owners.btrc").write_text(
        "\n".join(declarations)
        + """
int alive = 0;
class Buffer implements IShort, ILongName {
    public int stored;
    public Buffer() { self.stored = 1; alive++; }
    public void __del__() { alive--; }
    public int read() { return self.stored; }
    public int write(int value) { self.stored = value; return value; }
}
"""
    )
    inherited_check = "assert(writer.read() == 41);" if inherited else ""
    (source / "Main.btrc").write_text(
        """import ./Owners.btrc;
int consume(IShort reader, ILongName writer) {
    int initial = reader.read();
    int changed = writer.write(41);
"""
        + inherited_check
        + """
    return initial + changed;
}
int main() {
    try {
        var buffer = new Buffer();
        IShort reader = buffer;
        ILongName writer = buffer;
        assert(consume(reader, writer) == 42);
        assert(reader.read() == 41 && alive == 1);
    } catch (string message) {
        assert(false);
    }
    assert(alive == 0);
    print("PASS");
    return 0;
}
"""
    )
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    assert generated["reference"] == generated["selfhost"]


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize("readonly", [False, True], ids=["mutable", "readonly"])
@pytest.mark.parametrize("effectful", [False, True], ids=["plain", "ordered"])
def test_span_construction_and_arguments_match_frontends(tmp_path, immutable_btrcc, module_units, readonly, effectful):
    source = tmp_path / "src"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "spanOrder"\n')
    element = "const int" if readonly else "int"
    data = "selectData(values)" if effectful else "values"
    extent = "selectExtent()" if effectful else "(size_t)3"
    index = "nextIndex()" if effectful else "indexValue"
    output = "selectOutput()" if effectful else "&output"
    value = "nextValue()" if effectful else "41"
    writes = (
        ""
        if readonly
        else f"""
    trace = 0;
    assert(view.trySet({index}, {value}));
    assert(trace == {35 if effectful else 0} && values[1] == 41);
    indexValue = (size_t)3;
    trace = 0;
    assert(!view.trySet({index}, {value}));
    assert(trace == {35 if effectful else 0} && values[1] == 41);
    trace = 0;
    assert(!missing.trySet({index}, {value}));
    assert(trace == {35 if effectful else 0});
"""
    )
    (source / "Operations.btrc").write_text(
        """int trace = 0;
int output = 0;
size_t indexValue = (size_t)1;
int* selectData(int* storage) { trace = trace * 10 + 1; return storage; }
size_t selectExtent() { trace = trace * 10 + 2; return (size_t)3; }
size_t nextIndex() { trace = trace * 10 + 3; return indexValue; }
int* selectOutput() { trace = trace * 10 + 4; return &output; }
int nextValue() { trace = trace * 10 + 5; return 41; }
void probe() {
    int values[3] = {11, 13, 17};
"""
        + f"""    Span<{element}> view = Span(({element}*){data}, {extent});
    assert(trace == {12 if effectful else 0} && view.length() == (size_t)3);
    trace = 0;
    assert(view.tryGet({index}, {output}));
    assert(trace == {34 if effectful else 0} && output == 13);
    indexValue = (size_t)3;
    trace = 0;
    assert(!view.tryGet({index}, {output}));
    assert(trace == {34 if effectful else 0} && output == 13);
    Span<{element}> missing = Span(({element}*)null, (size_t)1);
    indexValue = (size_t)0;
    trace = 0;
    assert(!missing.tryGet({index}, {output}));
    assert(trace == {34 if effectful else 0} && output == 13);
    indexValue = (size_t)1;
"""
        + writes
        + """
    int fixed[2 + 1] = {7, 11, 19};
    Span<int> fixedView = Span(fixed);
    assert(fixedView.length() == (size_t)3);
    output = 0;
    assert(fixedView.tryGet((size_t)2, &output) && output == 19);
}
"""
    )
    (source / "Main.btrc").write_text('import ./Operations.btrc;\nint main() { probe(); print("PASS"); return 0; }\n')
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    assert generated["reference"] == generated["selfhost"]


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize(
    "backing, extent, index",
    [("values", 3, 1), ("values", 3, 3), ("null", 3, 1), ("values", 0, 0)],
    ids=["valid", "out-of-bounds", "null", "empty"],
)
def test_span_argument_exceptions_precede_bounds_checks(
    tmp_path, immutable_btrcc, module_units, backing, extent, index
):
    source = tmp_path / "src"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "spanThrows"\n')
    (source / "Operations.btrc").write_text(
        """int trace = 0;
int caught = 0;
int values[3] = {11, 13, 17};
int* selectData(int* storage) { trace = trace * 10 + 1; return storage; }
size_t throwingExtent() { trace = trace * 10 + 2; throw "extent"; }
int throwingValue() { trace = trace * 10 + 5; throw "value"; }
"""
        + f"size_t nextIndex() {{ trace = trace * 10 + 3; return (size_t){index}; }}\n"
        + """void probe() {
    try {
        Span<int> impossible = Span(selectData(values), throwingExtent());
        assert(impossible.length() == (size_t)3);
    } catch (string error) {
        assert(error == "extent" && trace == 12);
        caught++;
    }
    assert(caught == 1);
    trace = 0;
"""
        + f"    Span<int> view = Span((int*){backing}, (size_t){extent});\n"
        + """    try {
        bool stored = view.trySet(nextIndex(), throwingValue());
        assert(!stored);
    } catch (string error) {
        assert(error == "value");
        caught++;
    }
    assert(caught == 2 && trace == 35 && values[1] == 13);
}
"""
    )
    (source / "Main.btrc").write_text('import ./Operations.btrc;\nint main() { probe(); print("PASS"); return 0; }\n')
    _compile_and_run_native_frontends(source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units)


@pytest.mark.parametrize("module_units", [False, True], ids=["whole", "modules"])
@pytest.mark.parametrize("field_kind", ["scalar", "chain", "readonly-pointer", "managed"])
def test_owned_field_alias_storage_matches_frontends(tmp_path, immutable_btrcc, module_units, field_kind):
    source = tmp_path / "src"
    source.mkdir()
    (tmp_path / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "ownedFieldAlias"\n')
    managed = field_kind == "managed"
    declarations = {
        "scalar": "typedef unsigned long long Value;\n",
        "chain": "typedef unsigned long long Token;\ntypedef Token Value;\n",
        "readonly-pointer": "typedef const int* Value;\nint storage = 41;\n",
        "managed": """int payloads = 0;
class Payload {
    public int number;
    public Payload(int number) { self.number = number; payloads++; }
    public void __del__() { payloads--; }
}
typedef Payload Value;
""",
    }[field_kind]
    value = "new Payload(41)" if managed else "&storage" if field_kind == "readonly-pointer" else "41ULL"
    (source / "Entries.btrc").write_text(
        declarations
        + """int alive = 0;
int calls = 0;
class Entry {
    public Value value;
    public Entry(Value value) { self.value = value; alive++; }
    public void __del__() { alive--; }
}
Entry createEntry(bool fail) {
    calls++;
"""
        + f"    Entry entry = new Entry({value});\n"
        + """    if (fail) { throw "factory"; }
    return entry;
}
"""
    )
    inspect = (
        "value.number == 41 && payloads == 1"
        if managed
        else "value == &storage && *value == 41"
        if field_kind == "readonly-pointer"
        else "value == 41ULL"
    )
    payload_check = "assert(payloads == 0);" if managed else ""
    (source / "Operations.btrc").write_text(
        "import ./Entries.btrc;\n"
        + """void probe() {
    for (int iteration = 0; iteration < 3; iteration++) {
        try {
            Value value = createEntry(iteration == 1).value;
"""
        + f"            assert({inspect});\n"
        + """            assert(alive == 0 && calls == iteration + 1);
            assert(iteration != 1);
        } catch (string message) {
            assert(message == "factory" && iteration == 1);
        }
        assert(alive == 0 && calls == iteration + 1);
"""
        + f"        {payload_check}\n"
        + """    }
}
"""
    )
    storage_import = "import ./Entries.btrc;\n" if field_kind == "readonly-pointer" else ""
    storage_check = "assert(storage == 41);" if field_kind == "readonly-pointer" else ""
    (source / "Main.btrc").write_text(
        "import ./Operations.btrc;\n"
        + storage_import
        + f'int main() {{ try {{ probe(); {storage_check} print("PASS"); }} '
        + "catch (string message) { assert(false); } return 0; }\n"
    )
    generated = _compile_and_run_native_frontends(
        source, tmp_path, immutable_btrcc, "PASS\n", module_units=module_units
    )
    if not managed:
        assert generated["reference"] == generated["selfhost"]
        return
    # Alias and concrete class fields still select distinct ARC visitor helpers.
    # Compare the complete field-access consumer here; native runs cover the
    # generated visitors and destruction of both the owner and its payload.
    pattern = re.compile(rb"^void probe\(void\) \{\n.*?^\}", re.MULTILINE | re.DOTALL)
    bodies = {}
    for frontend, units in generated.items():
        matches = [match.group() for unit in units.values() if (match := pattern.search(unit)) is not None]
        assert len(matches) == 1, frontend
        bodies[frontend] = matches[0]
    assert bodies["reference"] == bodies["selfhost"]
