"""The cache-poisoning matrix: every reachable cache across every target axis.

platform-target-contract.md section 6.3. Every key that can depend on the
target spells the resolved row's canonical label (``PackageTarget.label`` in
the reference compiler, ``FePackageTarget.label()`` in btrcc), never the
``--target`` spelling, and a key that reads a sysroot includes its identity.

For each axis pair (A, B) and both compilers, four steps share one cache
directory:

1. a cold compile under A;
2. a warm compile under B, which misses, and whose output equals a cold
   compile under B in an empty cache;
3. a warm compile under A, which hits, and whose output equals step 1;
4. a warm compile under a spelling alias of A, which hits too.

Two spellings of one row are one target, so on the spelling axis step 2 hits.
On the sysroot axis every key that carries the native identity misses, while
the module units and validation records, which key the declarations the read
returned, reuse them soundly.

Each step compiles twice. The first writes a fresh output prefix, which every
whole-program key covers, so the module units (and btrcc's validation
records) answer it; the second writes one fixed prefix, which the
whole-program artifact cache answers. What is compared is the emitted C, every
unit and the link plan, not only the counters.

The program reads one native binding through the dev shell's header reader
with a stub sysroot per row (``src/tests/native_targets.py``), so every axis
runs on a host without any SDK. ``windows-aarch64-msvc`` reads its sysroot
only on its own runner, so the binding does not select it, and an ``#if``
keeps the call out of its program. The prebuilt stdlib archive is an artifact
with one slot per directory, not a cache: across rows it refuses, and the
matrix asserts the refusal.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from src.compiler.python import Compiler
from src.compiler.python.abi.generated import TARGET_SPEC_FINGERPRINT
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.artifacts.cache import CompilerCache, ToolchainFingerprint, ToolchainSourceInventory
from src.compiler.python.artifacts.publication import ArtifactPublisher, ArtifactStorage
from src.compiler.python.artifacts.stdlib import StdlibArchivePublisher, StdlibArtifactRepository
from src.compiler.python.frontend.packages import PackageTarget
from src.tests.native_targets import stub_sysroot
from src.tests.process_limits import TRANSPILE_TIMEOUT
from tools.compiler_codegen.hosted_abi import TargetManifest

REPO = Path(__file__).resolve().parents[3]
READER = os.environ.get("BTRC_NATIVE_HEADER_READER")
pytestmark = pytest.mark.skipif(os.name == "nt", reason="the private artifact store is not available on Windows")
needs_reader = pytest.mark.skipif(not READER, reason="the native binding needs BTRC_NATIVE_HEADER_READER")


@dataclass(frozen=True)
class Axis:
    """One pair of compile settings, A and B, on one axis of section 6.3."""

    name: str
    a: str
    b: str
    # Another spelling of A's row.
    alias: str
    # B is A's row, with its sysroot's identity file rewritten in place.
    sysroot: bool = False

    @property
    def same_row(self) -> bool:
        return PackageTarget.parse(self.a).label == PackageTarget.parse(self.b).label


AXES = (
    Axis("architecture", "linux-x86_64", "linux-aarch64", "linux-x64"),
    Axis("os-and-data-model", "linux-x86_64", "windows-x86_64", "linux-x64"),
    Axis("environment-abi", "windows-aarch64", "windows-aarch64-msvc", "windows-arm64"),
    Axis("device-or-simulator", "ios-aarch64", "ios-aarch64-simulator", "ios-arm64"),
    Axis("os-with-same-data-model", "linux-aarch64", "android-aarch64", "linux-arm64"),
    # Two spellings of one row are one target: step 2 hits.
    Axis("spelling", "macos-arm64", "macos-aarch64", "macos-aarch64"),
    Axis("sysroot-identity", "android-aarch64", "android-aarch64", "android-arm64", sysroot=True),
)

MANIFEST = """\
manifest-version = 1

[package]
name = "cacheIdentity"

[[native.bindings]]
module = "Api"
header = "Native.h"
language = "c"
standard = "c11"
symbols = ["measure"]
# Every row but windows-aarch64-msvc, whose SDK sysroot is read only on its runner.
env = ["", "gnu", "simulator"]
"""
NATIVE_HEADER = "long measure(const char *text);\n"
SOURCES = {
    "Api.btrc": "// The native wrapper module: Native.h binds into it.\n",
    # The conditioned group: an OS test, a hosted name each side lacks, the
    # binding's call, and the device, simulator, Android and architecture.
    "Probe.btrc": """\
import ./Api.btrc;

#if defined(_WIN32)
long hosted() { return (long)GetFileAttributesA("btrc"); }
#else
long hosted() { return (long)getpid(); }
#endif

#if defined(_WIN32) && !defined(__MINGW32__)
long native() { return 0; }
#else
long native() { return measure("btrc"); }
#endif

#if defined(__ANDROID__)
int flavor() { return 3; }
#elif defined(__APPLE_EMBEDDED_SIMULATOR__)
int flavor() { return 4; }
#elif defined(__aarch64__)
int flavor() { return 5; }
#else
int flavor() { return 6; }
#endif
""",
    # The same text on every row: only the row's data model types `wide`
    # (long on LP64, long long on LLP64), so no source digest tells the
    # rows' units apart.
    "Main.btrc": """\
import ./Probe.btrc;

int main() {
\tvar wide = 3000000000;
\treturn hosted() + native() + flavor() > 0 && wide > 0 ? 0 : 1;
}
""",
}


def write_project(root: Path) -> Path:
    (root / "src").mkdir(parents=True)
    (root / "btrc.toml").write_text(MANIFEST, encoding="utf-8")
    (root / "Native.h").write_text(NATIVE_HEADER, encoding="utf-8")
    for name, text in SOURCES.items():
        (root / "src" / name).write_text(text, encoding="utf-8")
    return root / "src" / "Main.btrc"


def write_sysroot(path: Path, target: str, identity: str) -> Path:
    """(Re)write a stub sysroot for `target` whose identity file carries `identity`.

    Rewriting it in place changes nothing a compile reads but the file that
    names the SDK, so a miss can come only from the sysroot identity.
    """

    path.mkdir(parents=True, exist_ok=True)
    stub_sysroot(path, target)
    kind = PackageTarget.parse(target).row.sysroot_kind
    if kind == "ndk":
        (path / "usr/include/android/api-level.h").write_text(f"/* stub {identity} */\n", encoding="utf-8")
    elif kind == "zig-mingw":
        marker = path / "include/any-windows-any/_mingw_mac.h"
        marker.write_text(marker.read_text(encoding="utf-8") + f"/* stub {identity} */\n", encoding="utf-8")
    elif kind == "xcrun":
        settings = path / "SDKSettings.json"
        document = json.loads(settings.read_text(encoding="utf-8"))
        settings.write_text(json.dumps({**document, "Stub": identity}), encoding="utf-8")
    return path


@dataclass(frozen=True)
class Observation:
    """What one compile emitted and which caches answered it."""

    # The emitted C, each unit and the link plan, with the output directory
    # spelled <out>.
    output: tuple[str, ...]
    artifact_hit: bool
    # Module units, when the compile lowered any; None on an artifact hit.
    lowered: int | None
    reused: int | None
    # btrcc's validation records, when the compile analyzed.
    replayed: int | None = None
    journaled: int | None = None


def normalized(texts: list[str], directory: Path) -> tuple[str, ...]:
    spellings = sorted({str(directory), os.path.realpath(directory)}, key=len, reverse=True)
    result = []
    for text in texts:
        for spelling in spellings:
            text = text.replace(spelling, "<out>")
        result.append(text)
    return tuple(result)


class ReferenceFrontend:
    """The Python compiler, in process, with its persistent cache."""

    name = "reference"

    def __init__(self, source: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.source = source
        self.monkeypatch = monkeypatch

    def compile(self, target: str | None, sysroot: Path, cache: Path, prefix: Path) -> Observation:
        """Compile for `target`, or for the inferred host when it is None."""

        prefix.parent.mkdir(parents=True, exist_ok=True)
        self.monkeypatch.setenv("BTRC_CACHE_DIR", str(cache))
        self.monkeypatch.setenv("BTRC_NATIVE_TARGET", PackageTarget.parse(target).row.triple)
        self.monkeypatch.setenv("BTRC_NATIVE_SYSROOT", str(sysroot))
        result = Compiler(cache=CompilerCache()).compile(
            self.source.read_text(encoding="utf-8"),
            str(self.source),
            CompilerOptions(
                include_stdlib=False,
                target=target,
                units_prefix=str(prefix),
                module_units=True,
                generated_c_path=f"{prefix}.c",
            ),
        )
        assert result.successful, (target, result.failure, [item.message for item in result.diagnostics])
        texts = [result.c_source or ""]
        texts.extend(f"{name}\n{text}" for name, text in zip(result.unit_names, result.c_units, strict=True))
        texts.append(result.native_plan.canonical_json())
        compiled = not result.cache_hit
        return Observation(
            normalized(texts, prefix.parent),
            result.cache_hit,
            len(result.module_units_lowered) if compiled else None,
            len(result.module_units_reused) if compiled else None,
        )


class SelfhostFrontend:
    """btrcc, as a process, with BTRC_TIMING's cache report."""

    name = "selfhost"

    def __init__(self, source: Path, btrcc: Path) -> None:
        self.source = source
        self.btrcc = btrcc

    def compile(self, target: str | None, sysroot: Path, cache: Path, prefix: Path) -> Observation:
        """Compile for `target`, or with no --target when it is None."""

        prefix.parent.mkdir(parents=True, exist_ok=True)
        environment = {
            **os.environ,
            "BTRC_HOME": str(REPO / "src"),
            "BTRC_TIMING": "1",
            "BTRC_CACHE_DIR": str(cache),
            "BTRC_NATIVE_TARGET": PackageTarget.parse(target).row.triple,
            "BTRC_NATIVE_SYSROOT": str(sysroot),
        }
        environment.pop("BASH_ENV", None)
        result = subprocess.run(
            [
                str(self.btrcc),
                "--no-stdlib",
                *(("--target", target) if target is not None else ()),
                str(self.source),
                "-o",
                f"{prefix}.c",
                "--emit-units",
                str(prefix),
                "--module-units",
                "--emit-link-plan",
                f"{prefix}.json",
            ],
            cwd=self.source.parent.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=TRANSPILE_TIMEOUT,
        )
        assert result.returncode == 0, (target, result.stderr)
        units = sorted(prefix.parent.glob(f"{prefix.name}.*.c"))
        texts = [Path(f"{prefix}.c").read_text(encoding="utf-8")]
        texts.extend(f"{path.name.removeprefix(prefix.name)}\n{path.read_text(encoding='utf-8')}" for path in units)
        texts.append(Path(f"{prefix}.json").read_text(encoding="utf-8"))
        counters = re.search(r"\bmodule-units=lowered:(\d+),reused:(\d+)", result.stderr)
        records = re.search(r"a-records-stored\(replayed=(\d+),journaled=(\d+)\)", result.stderr)
        return Observation(
            normalized(texts, prefix.parent),
            "artifact-hit=" in result.stderr,
            int(counters.group(1)) if counters else None,
            int(counters.group(2)) if counters else None,
            int(records.group(1)) if records else None,
            int(records.group(2)) if records else None,
        )


@dataclass(frozen=True)
class Step:
    """One matrix step: a fresh-prefix compile, then a fixed-prefix compile."""

    units: Observation
    artifact: Observation


class Matrix:
    """The four steps of one axis through one compiler, plus a cold B."""

    def __init__(self, frontend, root: Path, axis: Axis) -> None:
        self.frontend = frontend
        self.root = root
        self.axis = axis
        self.warm = root / "cache-warm"
        self.fixed = root / "out-fixed" / "program"
        self.outputs = itertools.count()
        # One sysroot directory per row; the sysroot axis rewrites its
        # identity file in place between A and B.
        self.identities: dict[str, str] = {}

    def fresh(self) -> Path:
        return self.root / f"out-{next(self.outputs)}" / "program"

    def sysroot(self, target: str | None, side: str) -> Path:
        label = PackageTarget.parse(target).label
        path = self.root / f"sysroot-{label}"
        identity = side if self.axis.sysroot else "a"
        if self.identities.get(label) != identity:
            write_sysroot(path, label, identity)
            self.identities[label] = identity
        return path

    def step(self, target: str | None, side: str) -> Step:
        units = self.frontend.compile(target, self.sysroot(target, side), self.warm, self.fresh())
        return Step(units, self.frontend.compile(target, self.sysroot(target, side), self.warm, self.fixed))

    def cold(self, target: str, side: str) -> Observation:
        return self.frontend.compile(target, self.sysroot(target, side), self.root / "cache-cold", self.fresh())


def assert_compiled(observation: Observation, *, reused: bool) -> None:
    """A fresh-prefix compile lowered or reused every unit, as `reused` says."""

    assert not observation.artifact_hit
    assert observation.lowered is not None and observation.reused is not None
    if reused:
        assert observation.lowered == 0 and observation.reused > 0, observation
    else:
        assert observation.reused == 0 and observation.lowered > 0, observation
    if observation.replayed is not None:
        if reused:
            assert observation.journaled == 0 and observation.replayed > 0, observation
        else:
            assert observation.replayed == 0 and observation.journaled > 0, observation


def run_matrix(frontend, root: Path, axis: Axis) -> None:
    matrix = Matrix(frontend, root, axis)

    # 1. Cold under A.
    first = matrix.step(axis.a, "a")
    assert_compiled(first.units, reused=False)
    assert not first.artifact.artifact_hit
    assert first.artifact.output == first.units.output

    # 2. Warm under B. A different row misses every layer. Two spellings of
    # one row are one target and hit. A second sysroot misses every key that
    # carries the native identity -- the whole-program artifacts -- while
    # units and validation records key the declarations the read returned,
    # which are the same, so they are reused soundly.
    second = matrix.step(axis.b, "b")
    cold = matrix.cold(axis.b, "b")
    assert_compiled(cold, reused=False)
    assert second.units.output == cold.output
    assert second.artifact.output == cold.output
    if axis.same_row and not axis.sysroot:
        assert_compiled(second.units, reused=True)
        assert second.artifact.artifact_hit
        assert cold.output == first.units.output
    elif axis.sysroot:
        assert_compiled(second.units, reused=True)
        assert not second.artifact.artifact_hit
        # The emitted C is the same; the plan records the other sysroot.
        assert cold.output[:-1] == first.units.output[:-1]
        assert cold.output[-1] != first.units.output[-1]
    else:
        assert_compiled(second.units, reused=False)
        assert not second.artifact.artifact_hit
        assert cold.output[:-1] != first.units.output[:-1]

    # 3. Warm under A again: every layer hits, with step 1's output.
    third = matrix.step(axis.a, "a")
    assert_compiled(third.units, reused=True)
    assert third.artifact.artifact_hit
    assert third.units.output == first.units.output
    assert third.artifact.output == first.units.output

    # 4. A spelling alias of A hits the same entries.
    fourth = matrix.step(axis.alias, "a")
    assert_compiled(fourth.units, reused=True)
    assert fourth.artifact.artifact_hit
    assert fourth.units.output == first.units.output
    assert fourth.artifact.output == first.units.output


@needs_reader
@pytest.mark.parametrize("axis", AXES, ids=lambda axis: axis.name)
def test_reference_caches_follow_the_target(axis: Axis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = write_project(tmp_path / "project")
    run_matrix(ReferenceFrontend(source, monkeypatch), tmp_path, axis)


@needs_reader
@pytest.mark.parametrize("axis", AXES, ids=lambda axis: axis.name)
def test_selfhost_caches_follow_the_target(axis: Axis, immutable_btrcc: Path, tmp_path: Path) -> None:
    source = write_project(tmp_path / "project")
    run_matrix(SelfhostFrontend(source, immutable_btrcc), tmp_path, axis)


@needs_reader
@pytest.mark.parametrize("frontend_name", ("reference", "selfhost"))
def test_the_inferred_host_is_a_spelling_of_its_row(
    frontend_name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """With no --target, the host's row keys every cache as its label does (§1.7)."""

    host = PackageTarget.parse(None).label
    source = write_project(tmp_path / "project")
    frontend = (
        ReferenceFrontend(source, monkeypatch)
        if frontend_name == "reference"
        else SelfhostFrontend(source, request.getfixturevalue("immutable_btrcc"))
    )
    matrix = Matrix(frontend, tmp_path, Axis("inferred-host", host, host, host))
    explicit = matrix.step(host, "a")
    assert_compiled(explicit.units, reused=False)
    inferred = matrix.step(None, "a")
    assert_compiled(inferred.units, reused=True)
    assert inferred.artifact.artifact_hit
    assert inferred.units.output == inferred.artifact.output == explicit.units.output


# -- The prebuilt stdlib archive ------------------------------------------------

# Every row of every axis but spelling emits different C for this program.
ARCHIVE_PROGRAM = """\
#if defined(_WIN32) && !defined(__MINGW32__)
int flavor() { return 1; }
#elif defined(_WIN32)
int flavor() { return 2; }
#elif defined(__ANDROID__)
int flavor() { return 3; }
#elif defined(__APPLE_EMBEDDED_SIMULATOR__)
int flavor() { return 4; }
#elif defined(__aarch64__)
int flavor() { return 5; }
#else
int flavor() { return 6; }
#endif
int main() { var wide = 3000000000; return flavor() > 0 && wide > 0 ? 0 : 1; }
"""


def archive_compiler() -> Compiler:
    repository = StdlibArtifactRepository(StdlibArchivePublisher(ArtifactPublisher(ArtifactStorage())))
    return Compiler(CompilationPipeline(archive_repository=repository))


class ArchiveRows:
    """One archive per row, built once through build_stdlib_archive."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.program = root / "Main.btrc"
        self.program.write_text(ARCHIVE_PROGRAM, encoding="utf-8")
        self.built: dict[tuple[str, str], Path] = {}

    def archive(self, target: str, slot: str = "warm") -> Path:
        label = PackageTarget.parse(target).label
        directory = self.built.get((label, slot))
        if directory is None:
            directory = self.root / f"{slot}-{label}"
            # The build takes the spelling it is given; the manifest records the row.
            built = archive_compiler().build_stdlib_archive(str(directory), target)
            assert built.failure is None, built.failure
            manifest = json.loads((directory / "btrc_stdlib.manifest").read_text(encoding="utf-8"))
            assert (manifest["target"], manifest["target_spec"]) == (label, TARGET_SPEC_FINGERPRINT)
            self.built[(label, slot)] = directory
        return directory

    def consume(self, archive: Path, target: str):
        return archive_compiler().compile(
            self.program.read_text(encoding="utf-8"),
            str(self.program),
            CompilerOptions(use_cache=False, target=target, stdlib_archive=str(archive)),
        )


@pytest.fixture(scope="module")
def archive_rows(tmp_path_factory: pytest.TempPathFactory) -> ArchiveRows:
    return ArchiveRows(tmp_path_factory.mktemp("archive-rows"))


@pytest.mark.parametrize("axis", [axis for axis in AXES if not axis.sysroot], ids=lambda axis: axis.name)
def test_prebuilt_stdlib_archive_refuses_another_row(axis: Axis, archive_rows: ArchiveRows) -> None:
    """The archive holds emitted C for one row; another row is refused by name, never served."""

    a, b = PackageTarget.parse(axis.a).label, PackageTarget.parse(axis.b).label
    # 1. Under A.
    first = archive_rows.consume(archive_rows.archive(axis.a), axis.a)
    assert first.successful, first.failure
    # 2. A's archive under B: refused, unless B spells A's row.
    crossed = archive_rows.consume(archive_rows.archive(axis.a), axis.b)
    if a == b:
        assert crossed.successful and crossed.c_source == first.c_source, crossed.failure
    else:
        assert crossed.failure is not None
        assert crossed.failure.message == f"prebuilt stdlib archive was built for {a}; regenerate it for {b}"
        # B's own archive serves B, as a freshly built one does, and refuses A.
        own = archive_rows.consume(archive_rows.archive(axis.b), axis.b)
        fresh = archive_rows.consume(archive_rows.archive(axis.b, "cold"), axis.b)
        assert own.successful and fresh.successful, (own.failure, fresh.failure)
        assert own.c_source == fresh.c_source != first.c_source
        refused = archive_rows.consume(archive_rows.archive(axis.b), axis.a)
        assert refused.failure is not None
        assert refused.failure.message == f"prebuilt stdlib archive was built for {b}; regenerate it for {a}"
    # 3. Under A again, and 4. under an alias of A: the same emitted C.
    for spelling in (axis.a, axis.alias):
        again = archive_rows.consume(archive_rows.archive(axis.a), spelling)
        assert again.successful and again.c_source == first.c_source, again.failure


# -- The spec fingerprint ----------------------------------------------------------


def test_the_target_spec_is_part_of_every_toolchain_identity(immutable_btrcc: Path, tmp_path: Path) -> None:
    """A generated-table change is a toolchain change in both compilers (asserted once).

    The reference compiler's toolchain fingerprint, which every artifact,
    module unit and stdlib archive key carries, covers the generated module
    that holds TARGET_SPEC_FINGERPRINT. btrcc compiles its tables in, and
    salts every stored key with its own executable's content: a byte-identical
    copy reuses the units, a changed one lowers them again. (A whole-program
    key also names the files the compile read, the executable among them, so
    a copy elsewhere misses there whatever its bytes.)
    """

    assert TargetManifest.load_repository(REPO).fingerprint == TARGET_SPEC_FINGERPRINT
    inventory = ToolchainSourceInventory.canonical()
    generated = Path(inventory.compiler_directory) / "abi" / "generated.py"
    assert str(generated) in inventory.files("full")
    copied = tmp_path / "compiler"
    (copied / "abi").mkdir(parents=True)
    shutil.copyfile(generated, copied / "abi" / "generated.py")
    before = ToolchainFingerprint(ToolchainSourceInventory(str(copied), str(tmp_path))).digest("full")
    text = (copied / "abi" / "generated.py").read_text(encoding="utf-8")
    (copied / "abi" / "generated.py").write_text(text.replace(TARGET_SPEC_FINGERPRINT, "0" * 64), encoding="utf-8")
    after = ToolchainFingerprint(ToolchainSourceInventory(str(copied), str(tmp_path))).digest("full")
    assert before != after

    if not READER:
        pytest.skip("the program's native binding needs BTRC_NATIVE_HEADER_READER")
    source = write_project(tmp_path / "project")
    sysroot = write_sysroot(tmp_path / "sysroot", "linux-x86_64", "a")
    cache = tmp_path / "cache"
    same = tmp_path / "bin" / "btrcc-copy"
    changed = tmp_path / "bin" / "btrcc-changed"
    same.parent.mkdir()
    shutil.copyfile(immutable_btrcc, same)
    shutil.copyfile(immutable_btrcc, changed)
    with changed.open("ab") as handle:
        handle.write(b"\0")
    for binary in (same, changed):
        binary.chmod(0o755)
    builds = []
    for index, binary in enumerate((immutable_btrcc, same, changed)):
        prefix = tmp_path / f"out-{index}" / "program"
        builds.append(SelfhostFrontend(source, binary).compile("linux-x86_64", sysroot, cache, prefix))
    first, copy, other = builds
    assert_compiled(first, reused=False)
    assert_compiled(copy, reused=True)
    assert_compiled(other, reused=False)
    assert first.output == copy.output == other.output
