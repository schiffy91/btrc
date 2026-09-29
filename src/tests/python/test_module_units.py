"""Module units: one C unit per compilation group, reused by key across builds."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.modules import ModuleUnitCompiler, ModuleUnitRecord
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache
from src.compiler.python.frontend.sources import CompilationGroups, SourceDependencyGraph
from src.compiler.python.ir.lowering.exceptions import FunctionEffect, ParameterEffect

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
    from tools.native_plan import NativePlanBuilder

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
    output = tmp_path.resolve()
    owner = subprocess.Popen(
        [
            str(immutable_btrcc),
            "src/compiler/btrc/BtrccMain.btrc",
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
        found = subprocess.run(["pgrep", "-P", str(owner.pid)], capture_output=True, text=True)
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
            alive = [pid for pid in started if subprocess.run(["kill", "-0", pid], capture_output=True).returncode == 0]
        assert not alive, f"workers outlived their owner: {alive}"
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait()
    assert not list(output.glob("program*.c"))
