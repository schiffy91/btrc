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
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ForkedModuleUnitWorkers, ModuleUnitCompiler, ModuleUnitRecord
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.frontend.native_imports import NativeGeneratedSource, NativeHeaderSource
from src.compiler.python.frontend.sources import CompilationGroups, SourceDependencyGraph
from src.compiler.python.ir.lowering.exceptions import FunctionEffect, ParameterEffect
from src.tests.process_limits import TOOL_TIMEOUT
from src.tests.python.test_native_cxx_owners import pugixml_project as pugixml_project
from src.tests.python.test_native_import_consumer import apple_environment
from src.tests.python.test_native_import_consumer import native_project as native_project
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "src" / "tests" / "native" / "modules"
C_COMPILER = shutil.which("cc")


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

    def build(self, entry: str, output: Path, monkeypatch):
        monkeypatch.setenv("BTRC_CACHE_DIR", str(self.cache))
        output.mkdir(parents=True, exist_ok=True)
        path = self.modules / entry
        result = Compiler(cache=CompilerCache()).compile(
            path.read_text(),
            str(path),
            CompilerOptions(
                units_prefix=str(output / "program"),
                module_units=True,
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
                C_COMPILER,
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
    btrcc, workspace: _Workspace, entry: str, output: Path, environment: dict[str, str] | None = None
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
    arguments = [
        "--strict-imports",
        "--target",
        "macos-arm64",
        str(AUDIO / "CoreAudioUnitConformance.btrc"),
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
    plan["emitted-units"] = [Path(path).name for path in plan.get("emitted-units", [])]
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
            [C_COMPILER, "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", *sources, "-o", str(executable)]
            + ["-lm", "-lpthread"],
            check=True,
            capture_output=True,
            timeout=180,
        )
        ran = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
        assert ran.returncode == 0 and ran.stdout == "Dark\nHit\n", (compiler, ran)


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
    for name in ("BTRC_TIMING", "BTRCC_TIMING"):
        environment.pop(name, None)
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
        [C_COMPILER, "-std=c11", *map(str, units), "-o", str(executable), "-lm", "-lpthread"],
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
            C_COMPILER,
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
    clang = shutil.which("clang")
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
