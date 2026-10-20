"""The provider matrix of platform-target-contract.md section 5.3.

Every stdlib group manifest, every ``examples/`` package with a ``btrc.toml``
and the native test packages are resolved for each of the 11 rows of
``targets.toml``, with every export imported, exactly as a compile resolves
them before it reads a native header: the package graph, the conditioned
import graph with its provider selections, then the native link plan
restricted to the loaded sources plus the stdlib's. Nothing here reads an SDK,
so every row runs on every host.

A resolution is a ``Resolution`` of workspace-relative facts, so the
reference resolver here and btrc's ``ProviderMatrixDriver`` compare record for
record. Every selected provider, declaration and binding is then classified:

- foreign: it lives under a platform directory of another operating system,
  or it is a framework on a row without frameworks, an Objective-C binding or
  source on a row without Objective-C, or a pkg-config record on ios or
  android. The matrix requires none.
- missing: the program imports a configured module with no provider for the
  row, so its resolution fails; an export under another operating system's
  platform directory is os-restricted instead.
- portable: every other selected record.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.packages import (
    IncludeResolutionError,
    PackageImportPolicy,
    PackageTarget,
    PackageUniverse,
)
from src.compiler.python.frontend.sources import (
    ConditionalEnvironment,
    SourceDirective,
    SourceDirectiveScanner,
    StdlibRepository,
)
from src.tests.process_limits import TRANSPILE_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
STDLIB = REPO / "src" / "stdlib"
GRAMMAR = REPO / "src" / "language" / "grammar.ebnf"
INVENTORY = REPO / "docs" / "design" / "platform-inventory.toml"
# The package trees resolved besides the stdlib: every examples/ package and
# every native test package, each by its top package directory.
PACKAGE_TREES = ("examples", "src/tests/native")
# UI0 inventories these groups' exports through its own denominators
# (test_platform_inventory.py), so the P0 inventory has no cell for them.
UI0_GROUPS = frozenset({"App", "GUI", "Tray", "UI"})
OPERATING_SYSTEMS = frozenset(row.operating_system for row in TARGET_ROWS)
ROWS = {row.label: row for row in TARGET_ROWS}
# The P0 inventory's six slices and the rows each covers (test_target_contract.py).
SLICE_ROWS = {
    "windows-x64": ("windows-x86_64",),
    "windows-arm64": ("windows-aarch64", "windows-aarch64-msvc"),
    "ios-device": ("ios-aarch64",),
    "ios-simulator": ("ios-aarch64-simulator",),
    "android-arm64": ("android-aarch64",),
    "android-x86_64": ("android-x86_64",),
}
# An inventory cell in one of these implementation states is unavailable on its slice.
UNAVAILABLE_IMPLEMENTATIONS = frozenset({"missing", "source-only"})
# Package modules that no ordinary compile resolves, by program key, with why.
EXPECTED_REFUSALS = {
    "package:src/tests/native/gui/webgpu_child/Main.btrc": (
        "imports the GUI package's private MacOS modules; test_native_webgpu_imports.py compiles it "
        "against the GUI provider data root, not the stdlib"
    ),
    "package:src/tests/native/gui/webgpu_child/Ownership.btrc": (
        "imports the GUI package's private MacOS modules; test_native_webgpu_imports.py compiles it "
        "against the GUI provider data root, not the stdlib"
    ),
}
NO_PROVIDER = re.compile(r"module '(?P<module>.+)' has no provider for target (?P<target>\S+)$")
QUOTED_PATH = re.compile(r"'(/[^']*)'")
PACKAGE_FAILURE = "error: package resolution failed: "
OBJECTIVE_C = frozenset({"objective-c", "objective-c++"})
PATH_KINDS = frozenset({"source", "header", "include-directory"})


@dataclass(frozen=True)
class MatrixProgram:
    """One resolution input: a synthetic stdlib import program or a package module."""

    key: str
    relative: str
    text: str | None = None
    exports: tuple[str, ...] = ()

    @property
    def group(self) -> str:
        return self.relative.split("/")[1]


@dataclass(frozen=True)
class Resolution:
    """What one program resolves to for one row.

    Paths are spelled ``repo:<relative>`` inside the repository and
    ``work:<relative>`` inside the frontend's workspace, so two workspaces
    compare equal. ``missing`` names the module with no provider for the row;
    ``refused`` is any other resolution failure, with its paths spelled.
    """

    missing: str | None = None
    refused: str | None = None
    sources: tuple[str, ...] = ()
    providers: tuple[tuple[str, str], ...] = ()
    packages: tuple[str, ...] = ()
    declarations: tuple[tuple[str, ...], ...] = ()
    bindings: tuple[tuple[str, ...], ...] = ()

    @property
    def resolved(self) -> bool:
        return self.missing is None and self.refused is None


@dataclass
class MatrixRow:
    """One row's classified records: foreign reasons, missing programs and portable records."""

    label: str
    foreign: list[str] = field(default_factory=list)
    missing: set[str] = field(default_factory=set)
    refused: set[str] = field(default_factory=set)
    portable: set[tuple[str, ...]] = field(default_factory=set)


class PathSpelling:
    """Workspace-independent spellings of canonical paths."""

    def __init__(self, workspace: Path) -> None:
        bases = (("repo", Path(os.path.realpath(REPO))), ("work", Path(os.path.realpath(workspace))))
        # A workspace inside the repository (build/) is the deeper base, so it wins.
        self.bases = sorted(bases, key=lambda item: len(item[1].parts), reverse=True)

    def spell(self, path: str) -> str:
        if not os.path.isabs(path):
            return path
        canonical = Path(os.path.realpath(path))
        for name, base in self.bases:
            if canonical == base or base in canonical.parents:
                return f"{name}:{canonical.relative_to(base).as_posix()}"
        return canonical.as_posix()

    def message(self, text: str) -> str:
        """A failure message with its quoted absolute paths spelled."""

        return QUOTED_PATH.sub(lambda match: f"'{self.spell(match[1])}'", text.removeprefix(PACKAGE_FAILURE).strip())

    def failure(self, text: str, label: str) -> Resolution:
        message = self.message(text)
        match = NO_PROVIDER.fullmatch(message)
        if match is not None and match["target"] == label:
            return Resolution(missing=match["module"])
        return Resolution(refused=message)


class MatrixWorkspace:
    """One frontend's directory of programs, and how its paths are spelled."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.spelling = PathSpelling(root)

    def path(self, program: MatrixProgram) -> Path:
        return self.root / program.relative

    def write(self, program: MatrixProgram) -> None:
        if program.text is not None:
            path = self.path(program)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(program.text, encoding="utf-8")


class ProviderMatrix(MatrixWorkspace):
    """The matrix programs laid out in one frontend's workspace, and the per-row run."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.programs = self.all_programs()
        for program in self.programs:
            self.write(program)
        for tree in self.package_trees():
            shutil.copytree(REPO / tree, root / "packages" / tree)

    @staticmethod
    def stdlib_exports() -> dict[str, tuple[str, str]]:
        """Every stdlib export by inventory id: its group ("" at the root) and its import."""

        root = tomllib.loads((STDLIB / "btrc.toml").read_text(encoding="utf-8"))
        exports = {f"Library.{name}": ("", f"Library.{name}") for name in root["package"]["exports"]}
        for group, dependency in root["dependencies"].items():
            manifest = tomllib.loads((STDLIB / dependency["path"] / "btrc.toml").read_text(encoding="utf-8"))
            for name in manifest["package"]["exports"]:
                identifier = f"Library.{group}" if name == group else f"Library.{group}.{name}"
                exports[identifier] = (group, f"Library.{group}.{name}")
        return exports

    @staticmethod
    def provider_exports() -> frozenset[str]:
        """The exports that are configured modules: the module of a [[package.providers]] entry."""

        root = tomllib.loads((STDLIB / "btrc.toml").read_text(encoding="utf-8"))
        configured = set()
        for group, dependency in root["dependencies"].items():
            manifest = tomllib.loads((STDLIB / dependency["path"] / "btrc.toml").read_text(encoding="utf-8"))
            for provider in manifest["package"].get("providers", ()):
                module = provider["module"]
                configured.add(f"Library.{group}" if module == group else f"Library.{group}.{module}")
        return frozenset(configured)

    @staticmethod
    def package_trees() -> tuple[str, ...]:
        """The top package directories under PACKAGE_TREES, relative to the repository."""

        roots = sorted({path.parent for tree in PACKAGE_TREES for path in (REPO / tree).rglob("btrc.toml")})
        top = [root for root in roots if not any(other in root.parents for other in roots)]
        return tuple(root.relative_to(REPO).as_posix() for root in top)

    @classmethod
    def all_programs(cls) -> tuple[MatrixProgram, ...]:
        """Every program the matrix may resolve on a row.

        The stdlib's are one program per group importing all of its exports
        and one per export, which runs only where its group's program found a
        missing provider; a package tree's are each of its modules, resolved
        as the root input against its nearest manifest.
        """

        exports = cls.stdlib_exports()
        groups: dict[str, list[str]] = {}
        for identifier, (group, _spelled) in exports.items():
            groups.setdefault(group or "Root", []).append(identifier)
        programs = []
        for group, identifiers in sorted(groups.items()):
            text = "".join(f"import {exports[identifier][1]};\n" for identifier in identifiers)
            programs.append(MatrixProgram(f"group:{group}", f"stdlib/{group}/Group.btrc", text, tuple(identifiers)))
            programs.extend(
                MatrixProgram(
                    f"export:{identifier}",
                    f"stdlib/{group}/Export{index}.btrc",
                    f"import {exports[identifier][1]};\n",
                    (identifier,),
                )
                for index, identifier in enumerate(identifiers)
            )
        for tree in cls.package_trees():
            for module in sorted((REPO / tree).rglob("*.btrc")):
                relative = module.relative_to(REPO).as_posix()
                programs.append(MatrixProgram(f"package:{relative}", f"packages/{relative}"))
        return tuple(programs)

    def row(
        self, label: str, resolve: Callable[[Sequence[MatrixProgram], str], dict[str, Resolution]]
    ) -> dict[str, Resolution]:
        """One row's resolutions through ``resolve``: the group and package
        programs, then each export of a group whose program found a missing provider."""

        results = resolve([program for program in self.programs if not program.key.startswith("export:")], label)
        failed = {
            key.removeprefix("group:")
            for key, resolution in results.items()
            if key.startswith("group:") and resolution.missing is not None
        }
        exports = [
            program for program in self.programs if program.key.startswith("export:") and program.group in failed
        ]
        results.update(resolve(exports, label))
        return results

    def export_status(self, label: str, results: dict[str, Resolution]) -> dict[str, str]:
        """Each stdlib export's status on one row: resolved, missing or os-restricted."""

        status = {}
        for program in self.programs:
            if not program.key.startswith("group:"):
                continue
            group = results[program.key]
            for identifier in program.exports:
                export = group if group.missing is None else results[f"export:{identifier}"]
                platforms = MatrixClassifier.platforms(tuple(identifier.split(".")[1:-1]))
                if export.missing is not None:
                    status[identifier] = "missing"
                elif platforms and platforms != {ROWS[label].operating_system}:
                    status[identifier] = "os-restricted"
                else:
                    status[identifier] = "resolved"
        return status


class RememberedDirectiveScanner(SourceDirectiveScanner):
    """The real directive scanner, remembering each conditioned text's scan.

    A scan is a function of the text alone, and the matrix conditions the same
    stdlib files hundreds of times.
    """

    def __init__(self) -> None:
        super().__init__()
        self._scans: dict[str, tuple[SourceDirective, ...]] = {}

    def scan(self, source: str, *, cache_input: str | None = None) -> list[SourceDirective]:
        if source not in self._scans:
            self._scans[source] = tuple(super().scan(source))
        return list(self._scans[source])


class ReferenceResolver:
    """The reference compiler's resolution of matrix programs."""

    def __init__(self, matrix: MatrixWorkspace) -> None:
        self.matrix = matrix
        self.universe = PackageUniverse()
        self.imports = ImportResolver(StdlibRepository(), directive_scanner=RememberedDirectiveScanner())

    def __call__(self, programs: Sequence[MatrixProgram], label: str) -> dict[str, Resolution]:
        target = PackageTarget.from_row(ROWS[label])
        return {program.key: self.resolve(program, target) for program in programs}

    def resolve(self, program: MatrixProgram, target: PackageTarget) -> Resolution:
        path = str(self.matrix.path(program))
        spelling = self.matrix.spelling
        spell = spelling.spell
        try:
            packages = self.universe.resolve_for(path, target=target)
            _text, _provenance, _positions, graph = self.imports.resolve_mapped(
                Path(path).read_text(encoding="utf-8"),
                path,
                packages,
                exit_on_error=False,
                use_cache=False,
                environment=ConditionalEnvironment.for_packages(packages),
            )
        except IncludeResolutionError as error:
            return spelling.failure(str(error).splitlines()[0], target.label)
        sources = graph.source_paths()
        plan = packages.native_plan.for_sources(sources).with_stdlib(str(STDLIB), sources)
        policy = PackageImportPolicy(target)
        return Resolution(
            sources=tuple(sorted(spell(source) for source in sources)),
            providers=tuple(
                sorted(
                    (spell(source), spell(implementation))
                    for source in sources
                    for implementation in policy.provider_for(source)
                )
            ),
            packages=tuple(sorted(package.name for package in plan.packages)),
            declarations=tuple(
                sorted(
                    (
                        item.package,
                        item.kind,
                        spell(item.value) if item.kind in PATH_KINDS else item.value,
                        item.detail,
                        item.language,
                        item.standard,
                        ",".join(sorted(spell(module) for module in item.modules)),
                    )
                    for item in plan.declarations
                    if item.selected_for(target)
                )
            ),
            bindings=tuple(
                sorted(
                    (
                        binding.package,
                        spell(binding.module),
                        spell(binding.header),
                        binding.language,
                        binding.standard,
                        ",".join(sorted(binding.symbols)),
                    )
                    for binding in plan.bindings
                )
            ),
        )


class SelfhostResolver:
    """btrc's resolution of matrix programs, through ``ProviderMatrixDriver``.

    The driver resolves its programs in order and exits at a package failure,
    as a compile does, so a failed program is recorded from its stderr and
    the driver resumes with the next one.
    """

    def __init__(self, matrix: MatrixWorkspace, driver: Path) -> None:
        self.matrix = matrix
        self.driver = driver

    def __call__(self, programs: Sequence[MatrixProgram], label: str) -> dict[str, Resolution]:
        results: dict[str, Resolution] = {}
        pending = list(programs)
        while pending:
            completed = subprocess.run(
                [
                    str(self.driver),
                    str(GRAMMAR),
                    str(STDLIB),
                    label,
                    *(str(self.matrix.path(item)) for item in pending),
                ],
                cwd=self.matrix.root,
                capture_output=True,
                text=True,
                timeout=TRANSPILE_TIMEOUT,
            )
            finished = self.parse(completed.stdout)
            for index, resolution in finished.items():
                results[pending[index].key] = resolution
            if completed.returncode == 0:
                assert len(finished) == len(pending), completed.stdout[-2000:]
                break
            started = completed.stdout.count("begin\t")
            assert completed.returncode == 1 and started == len(finished) + 1, (completed.returncode, completed.stderr)
            results[pending[len(finished)].key] = self.matrix.spelling.failure(completed.stderr.strip(), label)
            pending = pending[started:]
        return results

    def parse(self, output: str) -> dict[int, Resolution]:
        """Every program the driver finished, by its index in the call."""

        spell = self.matrix.spelling.spell
        finished: dict[int, Resolution] = {}
        index = -1
        fields: dict[str, list] = {}
        for line in output.splitlines():
            kind, *values = line.split("\t")
            if kind == "begin":
                index = int(values[0])
                fields = {"sources": [], "providers": [], "packages": [], "declarations": [], "bindings": []}
            elif kind == "end":
                finished[index] = Resolution(
                    sources=tuple(sorted(spell(path) for path in fields["sources"])),
                    providers=tuple(sorted(fields["providers"])),
                    packages=tuple(sorted(fields["packages"])),
                    declarations=tuple(sorted(fields["declarations"])),
                    bindings=tuple(sorted(fields["bindings"])),
                )
            elif kind == "source":
                fields["sources"].append(values[0])
            elif kind == "provider":
                fields["providers"].append((spell(values[0]), spell(values[1])))
            elif kind == "package":
                fields["packages"].append(values[0])
            elif kind == "declaration":
                package, declared, value, detail, language, standard, modules = values
                fields["declarations"].append(
                    (
                        package,
                        declared,
                        spell(value) if declared in PATH_KINDS else value,
                        detail,
                        language,
                        standard,
                        ",".join(sorted(spell(module) for module in filter(None, modules.split(",")))),
                    )
                )
            elif kind == "binding":
                package, module, header, language, standard, symbols = values
                fields["bindings"].append(
                    (
                        package,
                        spell(module),
                        spell(header),
                        language,
                        standard,
                        ",".join(sorted(filter(None, symbols.split(",")))),
                    )
                )
            else:
                raise AssertionError(f"unexpected driver line {line!r}")
        return finished


class MatrixClassifier:
    """Classify one row's resolutions into foreign, missing and portable records."""

    def __init__(self, workspace: Path) -> None:
        self.bases = {"repo": REPO, "work": workspace}

    @staticmethod
    def platforms(segments: tuple[str, ...]) -> frozenset[str]:
        """The operating systems that directory segments name (package-manifest.md's platform directories)."""

        return frozenset(segment.lower() for segment in segments if segment.lower() in OPERATING_SYSTEMS)

    def segments(self, spelled: str) -> tuple[str, ...]:
        """The directories of a spelled path below the package that owns it, if any does."""

        base, _, relative = spelled.partition(":")
        if base not in self.bases:
            return ()
        root = self.bases[base]
        directory = root.joinpath(*relative.split("/")[:-1])
        owner = next(
            (candidate for candidate in (directory, *directory.parents) if (candidate / "btrc.toml").is_file()),
            None,
        )
        return () if owner is None else directory.relative_to(owner).parts

    def foreign(self, label: str, kind: str, paths: tuple[str, ...], language: str, name: str) -> str | None:
        """Why one selected record is foreign to the row, or None when it is portable."""

        row = ROWS[label]
        for spelled in paths:
            platforms = self.platforms(self.segments(spelled))
            if platforms and platforms != {row.operating_system}:
                return f"{kind} {spelled} lives under a {'/'.join(sorted(platforms))} directory"
        if kind == "framework" and not row.frameworks:
            return f"framework {name} on a row without frameworks"
        if kind == "pkg-config" and row.operating_system in {"ios", "android"}:
            return f"pkg-config {name} on {row.operating_system}"
        if language in OBJECTIVE_C and not row.objective_c:
            return f"{language} {kind} {paths[0] if paths else name} on a row without Objective-C"
        return None

    def classify(self, label: str, results: dict[str, Resolution]) -> MatrixRow:
        classified = MatrixRow(label)
        for key, resolution in sorted(results.items()):
            if resolution.missing is not None:
                classified.missing.add(key)
                continue
            if resolution.refused is not None:
                classified.refused.add(key)
                continue
            records: list[tuple[tuple[str, ...], str, tuple[str, ...], str, str]] = [
                (("provider", module, implementation), "provider", (implementation,), "", "")
                for module, implementation in resolution.providers
            ]
            for declaration in resolution.declarations:
                _package, kind, value, _detail, language, _standard, modules = declaration
                paths = ((value,) if kind in PATH_KINDS else ()) + tuple(filter(None, modules.split(",")))
                records.append((declaration, kind, paths, language, value))
            records.extend(
                (binding, "binding", (binding[1], binding[2]), binding[3], "") for binding in resolution.bindings
            )
            for identity, kind, paths, language, name in records:
                reason = self.foreign(label, kind, paths, language, name)
                if reason is None:
                    classified.portable.add(identity)
                else:
                    classified.foreign.append(f"{key}: {reason}")
        return classified


class InventoryCells:
    """The P0 inventory's stdlib cells (docs/design/platform-inventory.toml)."""

    @staticmethod
    def implementations() -> dict[tuple[str, str], str]:
        """Each stdlib cell's implementation state, by (operation id, slice)."""

        document = tomllib.loads(INVENTORY.read_text(encoding="utf-8"))
        return {
            (row["id"], name): row[name]["implementation"]
            for row in document["rows"]
            if row["id"].startswith("Library.")
            for name in SLICE_ROWS
        }


PROBE_MANIFEST = """manifest-version = 1

[package]
name = "foreignProbe"

# The module is not under a platform directory, so no manifest rule ties the
# binding to macOS, but its header is.
[[native.bindings]]
module = "Api"
header = "MacOS/Api.h"
language = "c"
standard = "c11"
symbols = ["probeValue"]

[[native.headers]]
path = "Portable.h"
modules = ["Api"]
"""
# The probe's foreign records by row.
PROBE_FOREIGN = {
    "linux-x86_64": ["binding work:packages/probe/MacOS/Api.h lives under a macos directory"],
    "macos-aarch64": [],
    "ios-aarch64": ["binding work:packages/probe/MacOS/Api.h lives under a macos directory"],
}


def foreign_probe(root: Path) -> tuple[MatrixWorkspace, MatrixProgram]:
    """A package whose binding reads a macOS header on every row, beside a portable header."""

    package = root / "packages" / "probe"
    (package / "MacOS").mkdir(parents=True)
    (package / "src").mkdir()
    (package / "btrc.toml").write_text(PROBE_MANIFEST, encoding="utf-8")
    (package / "MacOS" / "Api.h").write_text("int probeValue(void);\n", encoding="utf-8")
    (package / "Portable.h").write_text("int probeValue(void);\n", encoding="utf-8")
    (package / "src" / "Api.btrc").write_text("// The probe's native module.\n", encoding="utf-8")
    program = MatrixProgram("package:probe/src/Api.btrc", "packages/probe/src/Api.btrc")
    return MatrixWorkspace(root), program
