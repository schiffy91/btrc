"""Audit what the standard library links, bundles, loads and launches, per target.

The rule (`stdlib-dependencies.toml`): a stdlib module may require first-party
code and what its target's operating system supplies. wgpu-native is the one
third-party exception. Anything else is a finding that names the module, the
target and the dependency.

Four sources are read, none of which needs a compiler or a toolchain:

- every package manifest's link records (`pkg-config`, `libraries`,
  `frameworks`);
- the system headers that each bound header, native source and `.btrc`
  module includes, followed through first-party `#include "…"` lines;
- literal run-time loads (`dlopen`, `LoadLibrary`) and literal process
  launches;
- source that carries someone else's copyright notice (bundled code).

`binary` reads a built ELF, PE or Mach-O file's own import list and classifies
it by the same policy, so a test can prove what a program really links.

A third-party requirement that is known and awaiting removal is a `pending`
row in the policy. `check` fails on a finding with no row and on a row with no
finding, so the list can only shrink as replacements land.
"""

from __future__ import annotations

import argparse
import fnmatch
import re
import struct
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from src.compiler.python.abi.generated import TARGET_ROWS

REPO = Path(__file__).resolve().parents[2]
STDLIB = REPO / "src/stdlib"
RUNTIME = REPO / "src/runtime"
POLICY = Path(__file__).with_name("stdlib-dependencies.toml")
REPORT = REPO / "docs/design/stdlib-dependencies.md"

C_FAMILY = (".c", ".h", ".m", ".mm", ".cpp", ".hpp")
SYSTEM_INCLUDE = re.compile(r"^[ \t]*#[ \t]*(?:include|import)[ \t]*<([^>\n]+)>", re.MULTILINE)
LOCAL_INCLUDE = re.compile(r"^[ \t]*#[ \t]*(?:include|import)[ \t]*\"([^\"\n]+)\"", re.MULTILINE)
RUNTIME_LOAD = re.compile(r"\b(?:dlopen|LoadLibrary(?:Ex)?[AW]?)\s*\(\s*L?\"([^\"]+)\"")
BTRC_LAUNCH = re.compile(
    r"\b(?:ChildProcess\.run|BackgroundProcess\.start|Process\.(?:run|start|pipe)|PipeProcess)\s*\(\s*\"([^\"]+)\""
)
C_LAUNCH = re.compile(r"\b(?:execl[pe]?|execv[pe]?|system|popen|_popen)\s*\(\s*L?\"([^\"\s]+)")
JAVA_IMPORT = re.compile(r"^[ \t]*import[ \t]+(?:static[ \t]+)?([A-Za-z_][\w.]*)\s*(?:\.\*)?;", re.MULTILINE)
NOTICE = re.compile(r"Copyright\s+(?:\(c\)|©|[12][0-9]{3})|SPDX-License-Identifier", re.IGNORECASE)
NOTICE_FILES = ("COPYRIGHT", "COPYING", "LICENSE", "LICENCE", "NOTICE")
# A directory named for an operating system holds that system's code.
DIRECTORY_SYSTEMS = {
    "linux": ("linux",),
    "macos": ("macos",),
    "ios": ("ios",),
    "android": ("android",),
    "windows": ("windows",),
    "apple": ("macos", "ios"),
    "unix": ("linux", "macos", "ios", "android"),
}


@dataclass(frozen=True, order=True)
class Requirement:
    """One thing one module needs on one target."""

    module: str
    target: str
    dependency: str
    kind: str
    name: str
    evidence: str

    @property
    def operating_system(self) -> str:
        return self.target.split("-", 1)[0]


class DependencyPolicy:
    """What each operating system supplies, the exception, and the pending removals."""

    KINDS = ("pkg-config", "libraries", "frameworks", "headers", "loads", "programs", "binaries", "classes")

    def __init__(self, path: Path = POLICY) -> None:
        self.path = path
        document = tomllib.loads(path.read_text())
        if document.get("schema") != 1:
            raise ValueError(f"{path}: unsupported schema")
        self.supplied: dict[str, dict[str, tuple[str, ...]]] = {
            system: {kind: tuple(table.get(kind, ())) for kind in self.KINDS}
            for system, table in document.get("supplied", {}).items()
        }
        self.operating_systems = tuple(sorted({row.operating_system for row in TARGET_ROWS}))
        for system in self.operating_systems:
            if system not in self.supplied:
                raise ValueError(f"{path}: no [supplied.{system}] table")
        self.exceptions = tuple(document.get("exceptions", ()))
        self.dependencies = tuple(document.get("dependencies", ()))
        self.bundled = tuple(document.get("bundled", ()))
        self.pending = tuple(document.get("pending", ()))
        self.decisions = tuple(document.get("decisions", ()))
        for row in self.pending:
            for key in ("dependency", "module", "os", "resolution"):
                if key not in row:
                    raise ValueError(f"{path}: a pending row lacks {key!r}: {row}")

    @staticmethod
    def _matches(name: str, patterns: tuple[str, ...] | list[str]) -> bool:
        return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)

    def supplied_by(self, system: str, kind: str, name: str) -> bool:
        """True when the target's own system (or ISO C, for headers) provides it."""
        folded = name.lower() if kind in ("loads", "binaries") else name
        for table in (self.supplied.get("common", {}), self.supplied[system]):
            patterns = table.get(kind, ())
            if kind in ("loads", "binaries"):
                patterns = tuple(pattern.lower() for pattern in patterns)
            if self._matches(folded, patterns):
                return True
        return False

    def supplied_somewhere(self, kind: str, name: str) -> bool:
        return any(self.supplied_by(system, kind, name) for system in self.operating_systems)

    def excepted(self, kind: str, name: str) -> str | None:
        for row in self.exceptions:
            if self._matches(name, row.get(kind, ())):
                return row["dependency"]
        return None

    def dependency(self, kind: str, name: str) -> str:
        """The readable name of what a raw record belongs to."""
        for row in self.dependencies:
            if self._matches(name, row.get(kind, ())):
                return row["name"]
        return name

    def classify(self, system: str, kind: str, name: str) -> tuple[str, str]:
        """(class, dependency): class is `os`, `exception` or `third-party`."""
        if excepted := self.excepted(kind, name):
            return "exception", excepted
        if self.supplied_by(system, kind, name):
            return "os", name
        return "third-party", self.dependency(kind, name)


class BinaryImports:
    """The libraries a built program names in its own import tables."""

    @classmethod
    def read(cls, path: Path) -> tuple[str, ...]:
        data = path.read_bytes()
        if data[:4] == b"\x7fELF":
            return cls._elf(data)
        if data[:2] == b"MZ":
            return cls._pe(data)
        if data[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"):
            return cls._macho(data, 0)
        if data[:4] in (b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"):
            return cls._fat(data)
        raise ValueError(f"{path}: not an ELF, PE or Mach-O file")

    @staticmethod
    def _string(data: bytes, offset: int) -> str:
        end = data.index(b"\0", offset)
        return data[offset:end].decode("utf-8", "replace")

    @classmethod
    def _elf(cls, data: bytes) -> tuple[str, ...]:
        wide = data[4] == 2
        order = "<" if data[5] == 1 else ">"
        if wide:
            (section_offset,) = struct.unpack_from(order + "Q", data, 0x28)
            entry_size, count = struct.unpack_from(order + "HH", data, 0x3A)
        else:
            (section_offset,) = struct.unpack_from(order + "I", data, 0x20)
            entry_size, count = struct.unpack_from(order + "HH", data, 0x2E)
        sections = []
        for index in range(count):
            base = section_offset + index * entry_size
            if wide:
                _, kind, _, _, offset, size, link = struct.unpack_from(order + "IIQQQQI", data, base)
            else:
                _, kind, _, _, offset, size, link = struct.unpack_from(order + "IIIIIII", data, base)
            sections.append((kind, offset, size, link))
        names: list[str] = []
        for kind, offset, size, link in sections:
            if kind != 6:  # SHT_DYNAMIC
                continue
            strings = sections[link][1]
            step = 16 if wide else 8
            for entry in range(offset, offset + size, step):
                tag, value = struct.unpack_from(order + ("qQ" if wide else "iI"), data, entry)
                if tag == 0:
                    break
                if tag == 1:  # DT_NEEDED
                    names.append(cls._string(data, strings + value))
        return tuple(names)

    @classmethod
    def _pe(cls, data: bytes) -> tuple[str, ...]:
        (header,) = struct.unpack_from("<I", data, 0x3C)
        if data[header : header + 4] != b"PE\0\0":
            raise ValueError("not a PE file")
        (section_count,) = struct.unpack_from("<H", data, header + 6)
        (optional_size,) = struct.unpack_from("<H", data, header + 20)
        optional = header + 24
        (magic,) = struct.unpack_from("<H", data, optional)
        directories = optional + (112 if magic == 0x20B else 96)
        table = optional + optional_size
        sections = [struct.unpack_from("<8sIIII", data, table + index * 40) for index in range(section_count)]

        def offset(address: int) -> int | None:
            for _, virtual_size, virtual_address, raw_size, raw_offset in sections:
                if virtual_address <= address < virtual_address + max(virtual_size, raw_size):
                    return raw_offset + address - virtual_address
            return None

        names: list[str] = []
        # Directory 1 is the import table, 13 the delay-load table; both hold
        # the library's name at a fixed field of each fixed-size row.
        for directory, row_size, name_field in ((1, 20, 12), (13, 32, 4)):
            address, size = struct.unpack_from("<II", data, directories + directory * 8)
            start = offset(address) if address and size else None
            if start is None:
                continue
            for row in range(start, start + size, row_size):
                (name_address,) = struct.unpack_from("<I", data, row + name_field)
                if name_address == 0:
                    break
                if (name := offset(name_address)) is not None:
                    names.append(cls._string(data, name))
        return tuple(names)

    @classmethod
    def _macho(cls, data: bytes, base: int) -> tuple[str, ...]:
        order = "<"
        wide = data[base : base + 4] == b"\xcf\xfa\xed\xfe"
        (count,) = struct.unpack_from(order + "I", data, base + 16)
        cursor = base + (32 if wide else 28)
        names: list[str] = []
        for _ in range(count):
            command, size = struct.unpack_from(order + "II", data, cursor)
            # LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB, LC_LAZY_LOAD_DYLIB, LC_LOAD_UPWARD_DYLIB
            if command in (0xC, 0x80000018, 0x8000001F, 0x20, 0x80000023):
                (name,) = struct.unpack_from(order + "I", data, cursor + 8)
                names.append(cls._string(data, cursor + name))
            cursor += size
        return tuple(names)

    @classmethod
    def _fat(cls, data: bytes) -> tuple[str, ...]:
        wide = data[:4] == b"\xca\xfe\xba\xbf"
        (count,) = struct.unpack_from(">I", data, 4)
        names: list[str] = []
        for index in range(count):
            if wide:
                (offset,) = struct.unpack_from(">Q", data, 8 + index * 32 + 8)
            else:
                (offset,) = struct.unpack_from(">I", data, 8 + index * 20 + 8)
            names.extend(name for name in cls._macho(data, offset) if name not in names)
        return tuple(names)


class DependencyAudit:
    """Every requirement of every stdlib module, classified by the policy."""

    def __init__(self, policy: DependencyPolicy | None = None, stdlib: Path = STDLIB, runtime: Path = RUNTIME) -> None:
        self.policy = policy if policy is not None else DependencyPolicy()
        self.stdlib = stdlib.resolve()
        self.runtime = runtime.resolve()
        self.root = self.stdlib.parents[1]
        self.targets = tuple(
            (row.label, row.operating_system, row.architecture, row.environment) for row in TARGET_ROWS
        )
        self._claimed: set[Path] = set()
        self._reached: dict[str, frozenset[Path]] = {}
        self._inventory = None

    # ── target and module names ────────────────────────────────────────────

    def _selected(self, record: dict, systems: tuple[str, ...] | None = None) -> tuple[str, ...]:
        """Target labels a manifest record's os/arch/env selectors name."""
        wanted_systems = record.get("os") or systems
        return tuple(
            label
            for label, system, architecture, environment in self.targets
            if (not wanted_systems or system in wanted_systems)
            and (not record.get("arch") or architecture in record["arch"])
            and (not record.get("env") or environment in record["env"])
        )

    def _path_systems(self, path: Path) -> tuple[str, ...] | None:
        """The systems a file's directory names restrict it to, if any."""
        base = self.stdlib if path.is_relative_to(self.stdlib) else self.runtime
        systems: set[str] | None = None
        for segment in path.relative_to(base).parts[:-1]:
            named = DIRECTORY_SYSTEMS.get(segment.lower())
            if named is not None:
                systems = set(named) if systems is None else systems & set(named)
        return None if systems is None else tuple(sorted(systems))

    def _name(self, path: Path) -> str:
        if path.is_relative_to(self.stdlib):
            relative = path.relative_to(self.stdlib)
            return relative.with_suffix("").as_posix() if path.suffix == ".btrc" else relative.as_posix()
        return path.relative_to(self.root / "src").as_posix()

    @staticmethod
    def _module(package: Path, module: str) -> str:
        return (package / Path(*module.split("."))).as_posix().removeprefix("./")

    def _reachable(self, target: str) -> frozenset[Path]:
        """The modules a program for `target` can reach: every export, and what each imports there.

        A module no manifest exports is private to its package. It counts
        only on the targets where an export, or the provider a manifest
        selects for one, imports it.
        """
        if target not in self._reached:
            # Imported here: the inventory pulls in the whole reference compiler.
            from src.compiler.python.frontend.packages import PackageTarget
            from tools.qualification.stdlib import StdlibInventory

            if self._inventory is None:
                self._inventory = StdlibInventory(self.stdlib, runtime_root=self.runtime / "c")
            inventory = self._inventory
            selected = PackageTarget.parse(target)
            pending: list[Path] = []
            for manifest in sorted(self.stdlib.rglob("btrc.toml")):
                package = tomllib.loads(manifest.read_text()).get("package", {})
                for export in package.get("exports", ()):
                    pending.append((manifest.parent / Path(*export.split("."))).with_suffix(".btrc").resolve())
            reached: set[Path] = set()
            while pending:
                module = pending.pop()
                if module in reached or not module.is_file() or inventory.restriction(module, selected) is not None:
                    continue
                reached.add(module)
                pending.extend(inventory.dependencies(module, selected))
            self._reached[target] = frozenset(reached)
        return self._reached[target]

    # ── the four sources ───────────────────────────────────────────────────

    def requirements(self) -> list[Requirement]:
        found: set[Requirement] = set()
        self._claimed.clear()
        for manifest in sorted(self.stdlib.rglob("btrc.toml")):
            found.update(self._manifest(manifest))
        for path in sorted([*self.stdlib.rglob("*"), *self.runtime.rglob("*")]):
            if not path.is_file():
                continue
            if path.suffix in (".btrc", ".java") or (path.suffix in C_FAMILY and path not in self._claimed):
                modules = (self._name(path),)
                targets = self._selected({}, self._path_systems(path))
                if path.suffix == ".btrc" and path.is_relative_to(self.stdlib):
                    targets = tuple(target for target in targets if path in self._reachable(target))
                found.update(self._file(path, modules, targets, frozenset(), set()))
        found.update(self._bundled())
        return sorted(found)

    def _manifest(self, manifest: Path) -> list[Requirement]:
        document = tomllib.loads(manifest.read_text())
        native = document.get("native", {})
        package = manifest.parent.relative_to(self.stdlib)
        where = manifest.relative_to(self.stdlib).as_posix()
        found: list[Requirement] = []
        for kind in ("pkg-config", "libraries", "frameworks"):
            for record in native.get(kind, ()):
                modules = [self._module(package, module) for module in record.get("modules", ())] or [
                    package.as_posix()
                ]
                found.extend(
                    self._require(module, target, kind, record["name"], f"{kind} record in {where}")
                    for module in modules
                    for target in self._selected(record)
                )
        files: dict[Path, tuple[set[str], set[str], set[str]]] = {}
        for record in native.get("bindings", ()):
            self._bind(files, manifest.parent / record["header"], [self._module(package, record["module"])], record)
        for record in native.get("sources", ()):
            modules = [self._module(package, module) for module in record.get("modules", ())] or [package.as_posix()]
            self._bind(files, manifest.parent / record["path"], modules, record)
        for path, (modules, targets, explicit) in files.items():
            if path.is_file():
                found.extend(
                    self._file(
                        path.resolve(), tuple(sorted(modules)), tuple(sorted(targets)), frozenset(explicit), set()
                    )
                )
        return found

    def _bind(self, files: dict, path: Path, modules: list[str], record: dict) -> None:
        bound_modules, bound_targets, explicit = files.setdefault(path, (set(), set(), set()))
        bound_modules.update(modules)
        bound_targets.update(self._selected(record))
        explicit.update(record.get("os", ()))

    def _require(self, module: str, target: str, kind: str, name: str, evidence: str) -> Requirement:
        _, dependency = self.policy.classify(target.split("-", 1)[0], kind, name)
        return Requirement(module, target, dependency, kind, name, evidence)

    def _conditional(self, system: str, kind: str, name: str, explicit: frozenset[str]) -> bool:
        """True for another system's name in a source several systems share.

        Such a source reaches it only under that system's conditional; the
        strict stdlib check compiles every target and would refuse it
        otherwise. A name the policy knows as a third-party dependency still
        counts wherever a manifest record selects the system by name.
        """
        if self.policy.supplied_by(system, kind, name) or self.policy.excepted(kind, name):
            return False
        if not self.policy.supplied_somewhere(kind, name):
            return False
        return system not in explicit or self.policy.dependency(kind, name) == name

    def _file(
        self, path: Path, modules: tuple[str, ...], targets: tuple[str, ...], explicit: frozenset[str], seen: set[Path]
    ) -> list[Requirement]:
        """A source's own system headers, loads and launches, and those of what it includes."""
        if path in seen:
            return []
        seen.add(path)
        self._claimed.add(path)
        text = path.read_text(errors="replace")
        where = self._name(path) if path.suffix != ".btrc" else self._name(path) + ".btrc"
        narrowed = self._path_systems(path)
        if narrowed is not None:
            targets = tuple(target for target in targets if target.split("-", 1)[0] in narrowed)
            if len(narrowed) == 1:
                explicit = explicit | frozenset(narrowed)
        found: list[Requirement] = []
        scans = [("headers", SYSTEM_INCLUDE, "includes"), ("loads", RUNTIME_LOAD, "loads at run time")]
        scans.append(("programs", BTRC_LAUNCH if path.suffix == ".btrc" else C_LAUNCH, "launches"))
        if path.suffix == ".java":
            scans = [("classes", JAVA_IMPORT, "imports")]
        for kind, pattern, verb in scans:
            for name in sorted(set(pattern.findall(text))):
                for target in targets:
                    system = target.split("-", 1)[0]
                    if self._conditional(system, kind, name, explicit):
                        continue
                    found.extend(self._require(module, target, kind, name, f"{where} {verb} it") for module in modules)
        if path.suffix in C_FAMILY:
            for name in LOCAL_INCLUDE.findall(text):
                for base in (path.parent, self.runtime / "c", self.runtime / "windows", self.runtime / "gpu"):
                    included = (base / name).resolve()
                    if included.is_file() and (
                        included.is_relative_to(self.stdlib) or included.is_relative_to(self.runtime)
                    ):
                        found.extend(self._file(included, modules, targets, explicit, seen))
                        break
        return found

    def _bundled(self) -> list[Requirement]:
        """Source in the tree under someone else's copyright."""
        found: list[Requirement] = []
        for base in (self.stdlib, self.runtime):
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.suffix in (".md", ".toml", ".lock", ".symbols"):
                    continue
                noticed = path.name.upper().startswith(NOTICE_FILES) or NOTICE.search(path.read_text(errors="replace"))
                if not noticed:
                    continue
                relative = path.relative_to(self.root).as_posix()
                row = next((row for row in self.policy.bundled if relative.startswith(row["path"])), None)
                if row is None:
                    found.extend(
                        Requirement(
                            self._name(path),
                            label,
                            f"bundled source {relative}",
                            "bundled",
                            relative,
                            "carries a copyright notice no policy row attributes",
                        )
                        for label in self._selected({}, self._path_systems(path))
                    )
                    continue
                found.extend(
                    Requirement(
                        module, label, row["dependency"], "bundled", row["path"], f"{row['path']} is bundled source"
                    )
                    for module in row["modules"]
                    for label in self._selected(row)
                )
        return found

    # ── classification ─────────────────────────────────────────────────────

    def third_party(self) -> list[Requirement]:
        return [item for item in self.requirements() if self._class(item) == "third-party"]

    def _class(self, item: Requirement) -> str:
        if item.kind == "bundled":
            return "third-party"
        return self.policy.classify(item.operating_system, item.kind, item.name)[0]

    def check(self) -> list[str]:
        """Problems, each naming module, target and dependency; empty when the policy holds."""
        problems: list[str] = []
        findings = self.third_party()
        pending = {(row["dependency"], row["module"], system) for row in self.policy.pending for system in row["os"]}
        seen: set[tuple[str, str, str]] = set()
        for item in findings:
            key = (item.dependency, item.module, item.operating_system)
            seen.add(key)
            if key not in pending:
                problems.append(
                    f"third-party requirement: module {item.module} on target {item.target} requires "
                    f"{item.dependency} ({item.kind} {item.name}: {item.evidence})"
                )
        for dependency, module, system in sorted(pending - seen):
            problems.append(
                f"stale pending row: module {module} no longer requires {dependency} on {system}; "
                f"remove it from {self.policy.path.name}"
            )
        return problems

    def binary_problems(self, path: Path, target: str, *, toolchain: bool = True) -> list[str]:
        """Imports of a built program that its target's system does not supply."""
        system = target.split("-", 1)[0]
        problems = []
        for name in BinaryImports.read(path):
            if toolchain and self.policy.supplied_by("toolchain", "binaries", name.rsplit("/", 1)[-1]):
                continue
            leaf = name if system in ("macos", "ios") else name.rsplit("/", 1)[-1]
            kind, dependency = self.policy.classify(system, "binaries", leaf)
            if kind == "third-party":
                problems.append(f"third-party requirement: {path.name} on target {target} imports {dependency}")
        return problems

    # ── the audit document ─────────────────────────────────────────────────

    def report(self) -> str:
        requirements = self.requirements()
        by_class: dict[str, dict[tuple[str, str], dict[str, set[str]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(set))
        )
        for item in requirements:
            by_class[self._class(item)][(item.dependency, item.module)][item.operating_system].add(
                f"{item.kind} `{item.name}`"
            )
        lines = [
            "# Standard library dependencies",
            "",
            "<!-- Generated by `python -m tools.qualification.dependencies report --write`. Edit",
            "     tools/qualification/stdlib-dependencies.toml, not this file. -->",
            "",
            "The rule: a stdlib module requires first-party code and what its target's operating",
            "system supplies. wgpu-native is the only third-party exception. `python -m",
            "tools.qualification.dependencies check` enforces it on every manifest link record,",
            "every system header a native source or module includes, every literal run-time load",
            "and process launch, and every file that carries someone else's copyright notice. A",
            "failure names the module, the target and the dependency.",
            "",
            "## Third-party requirements awaiting removal",
            "",
        ]
        resolutions = {(row["dependency"], row["module"]): row["resolution"] for row in self.policy.pending}
        third = by_class.get("third-party", {})
        if not third:
            lines += ["None. wgpu-native is the sole third-party requirement.", ""]
        else:
            lines += [
                "| Dependency | Module | Targets | How it is required | Replacement |",
                "| --- | --- | --- | --- | --- |",
            ]
            for (dependency, module), systems in sorted(third.items()):
                how = sorted({entry for entries in systems.values() for entry in entries})
                lines.append(
                    f"| {dependency} | `{module}` | {', '.join(sorted(systems))} | {'; '.join(how)} | "
                    f"{resolutions.get((dependency, module), '**unlisted**')} |"
                )
            lines.append("")
        lines += ["## Owner decisions", ""]
        if not self.policy.decisions:
            lines += ["None open.", ""]
        for row in self.policy.decisions:
            lines += [f"### {row['title']}", "", row["text"].strip(), ""]
        lines += [
            "## The exception",
            "",
            "| Dependency | Module | Targets | How it is required |",
            "| --- | --- | --- | --- |",
        ]
        for (dependency, module), systems in sorted(by_class.get("exception", {}).items()):
            how = sorted({entry for entries in systems.values() for entry in entries})
            lines.append(f"| {dependency} | `{module}` | {', '.join(sorted(systems))} | {'; '.join(how)} |")
        lines += ["", "## What each operating system supplies, as the stdlib uses it", ""]
        used: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for item in requirements:
            if self._class(item) == "os" and item.kind != "headers":
                # A Java class is reported by its package's first two segments.
                name = ".".join(item.name.split(".")[:2]) + ".*" if item.kind == "classes" else item.name
                used[item.operating_system][item.kind].add(name)
        for system in sorted(used):
            parts = [
                f"{kind}: {', '.join(f'`{name}`' for name in sorted(names))}"
                for kind, names in sorted(used[system].items())
            ]
            lines.append(f"- **{system}**: {'; '.join(parts)}")
        lines.append("")
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.qualification.dependencies", description=__doc__.split("\n")[0]
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="fail on any third-party requirement the policy does not list")
    listing = commands.add_parser("list", help="print every requirement with its class")
    listing.add_argument("--third-party", action="store_true")
    report = commands.add_parser("report", help="print, write or verify the audit document")
    report.add_argument("--write", action="store_true")
    report.add_argument("--check", action="store_true")
    binary = commands.add_parser("binary", help="classify the libraries a built program imports")
    binary.add_argument("--target", required=True)
    binary.add_argument("path", type=Path, nargs="+")
    arguments = parser.parse_args(argv)
    audit = DependencyAudit()
    if arguments.command == "check":
        problems = audit.check()
        for problem in problems:
            print(problem, file=sys.stderr)
        if problems:
            return 1
        waiting = sorted({row["dependency"] for row in audit.policy.pending})
        print(
            "stdlib dependencies: no unlisted third-party requirement"
            + (f"; awaiting removal: {', '.join(waiting)}" if waiting else "; wgpu-native is the sole exception")
        )
        return 0
    if arguments.command == "list":
        for item in audit.requirements():
            kind = audit._class(item)
            if not arguments.third_party or kind == "third-party":
                print(
                    f"{kind}\t{item.module}\t{item.target}\t{item.dependency}\t{item.kind} {item.name}\t{item.evidence}"
                )
        return 0
    if arguments.command == "report":
        text = audit.report()
        if arguments.write:
            REPORT.write_text(text)
        elif arguments.check:
            if not REPORT.is_file() or REPORT.read_text() != text:
                print(
                    f"{REPORT.relative_to(REPO)} is stale: run `python -m tools.qualification.dependencies report --write`",
                    file=sys.stderr,
                )
                return 1
        else:
            print(text)
        return 0
    problems = [problem for path in arguments.path for problem in audit.binary_problems(path, arguments.target)]
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
