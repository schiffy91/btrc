"""Reproducible, invocation-scoped package resolution for btrc.

A package is a directory containing a ``btrc.toml`` manifest and modules under
``src/`` (or at its root). Dependencies are declared by path or Git and pinned
in ``btrc.lock``. Resolving a source file returns an immutable
``ResolvedPackages`` value; no package selection is installed in process or
task-global state.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, replace
from types import MappingProxyType


class IncludeResolutionError(Exception):
    """Include/import resolution failed before lexing."""


class LockfileError(ValueError):
    """A present lockfile is corrupt or violates its declared schema."""


class LockfileVersionError(LockfileError):
    """A lockfile was written by an unsupported schema version."""


LOCK_SCHEMA = 2
PACKAGE_GRAPH_LOCK_SCHEMA = 3
PACKAGE_MANIFEST_VERSION = 1
NATIVE_LINK_PLAN_SCHEMA = 1

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MODULE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_NATIVE_NAME = re.compile(r"^[A-Za-z0-9_.+-]+$")
_NATIVE_SYMBOL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*$")
_OBJECTIVE_C_SYMBOL = re.compile(
    r"^[+-]\[[A-Za-z_][A-Za-z0-9_]* (?:[A-Za-z_][A-Za-z0-9_]*|(?:[A-Za-z_][A-Za-z0-9_]*:)+)\]$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TARGET_OPERATING_SYSTEMS = frozenset({"linux", "macos", "windows"})
_TARGET_ARCHITECTURES = frozenset({"x86_64", "aarch64"})
_SOURCE_STANDARDS = MappingProxyType(
    {
        "c": frozenset({"c11"}),
        "c++": frozenset({"c++17", "c++20"}),
        "objective-c": frozenset({"c11"}),
        "objective-c++": frozenset({"c++17", "c++20"}),
    }
)


class PackageFileStore:
    """Own bounded metadata reads and atomic package-state publication."""

    def open_regular_binary(self, path: str, *, follow_symlinks: bool = False):
        flags = (
            os.O_RDONLY
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOINHERIT", 0)
            | getattr(os, "O_NONBLOCK", 0)
        )
        if not follow_symlinks:
            flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                descriptor = -1
                return None
            file = os.fdopen(descriptor, "rb")
            descriptor = -1
            return file
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)

    def read_json(self, path: str):
        """Read one regular JSON file, letting the OS bound what fits."""

        try:
            file = self.open_regular_binary(path)
            if file is None:
                return None
            with file:
                encoded = file.read()
            return json.loads(encoded.decode("utf-8"), parse_constant=self._reject_json_constant)
        except (OSError, MemoryError, UnicodeError, ValueError, TypeError, RecursionError):
            return None

    def write_json(self, path: str, payload, *, file_mode: int | None = None) -> None:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary_path = tempfile.mkstemp(prefix=".btrc-package-", dir=directory)
        try:
            if file_mode is not None:
                fchmod = getattr(os, "fchmod", None)
                if fchmod is not None:
                    fchmod(descriptor, file_mode)
                else:
                    os.chmod(temporary_path, file_mode)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                descriptor = -1
                file.write(encoded)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_path, path)
            self._sync_parent(path)
        finally:
            if descriptor >= 0:
                with suppress(OSError):
                    os.close(descriptor)
            with suppress(FileNotFoundError):
                os.remove(temporary_path)

    @staticmethod
    def _sync_parent(path: str) -> None:
        directory = os.path.dirname(os.path.abspath(path))
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError:
            return
        try:
            with suppress(OSError):
                os.fsync(descriptor)
        finally:
            with suppress(OSError):
                os.close(descriptor)

    @staticmethod
    def _reject_json_constant(value: str):
        raise ValueError(f"invalid JSON constant: {value}")


@dataclass(frozen=True, order=True)
class PackageTarget:
    """One normalized native-plan target."""

    operating_system: str
    architecture: str

    @classmethod
    def parse(cls, value: str | None) -> PackageTarget:
        if value is None:
            system = platform.system().lower()
            operating_system = {"darwin": "macos", "linux": "linux", "windows": "windows"}.get(system)
            machine = platform.machine().lower()
            architecture = {
                "amd64": "x86_64",
                "x86_64": "x86_64",
                "arm64": "aarch64",
                "aarch64": "aarch64",
            }.get(machine)
            if operating_system is None or architecture is None:
                raise ValueError(f"cannot infer a supported package target from {system}-{machine}")
            return cls(operating_system, architecture)
        if not isinstance(value, str) or not value:
            raise ValueError("package target must be OS-ARCH")
        operating_system, separator, raw_architecture = value.partition("-")
        architecture = {"x64": "x86_64", "arm64": "aarch64"}.get(raw_architecture, raw_architecture)
        if (
            not separator
            or operating_system not in _TARGET_OPERATING_SYSTEMS
            or architecture not in _TARGET_ARCHITECTURES
        ):
            raise ValueError(
                f"unsupported package target {value!r}; expected linux, macos, or windows with x86_64 or aarch64"
            )
        return cls(operating_system, architecture)

    @classmethod
    def coerce(cls, value: str | PackageTarget | None) -> PackageTarget:
        """One target from either spelling, inferring the host when unset."""
        return value if isinstance(value, PackageTarget) else cls.parse(value)

    def as_dict(self) -> dict[str, str]:
        return {"arch": self.architecture, "os": self.operating_system}


@dataclass(frozen=True, order=True)
class NativeDeclaration:
    """One validated native manifest declaration before target filtering."""

    kind: str
    package: str
    value: str
    detail: str = ""
    language: str = ""
    standard: str = ""
    operating_systems: tuple[str, ...] = ()
    architectures: tuple[str, ...] = ()
    modules: tuple[str, ...] = ()

    def selected_for(self, target: PackageTarget) -> bool:
        return (not self.operating_systems or target.operating_system in self.operating_systems) and (
            not self.architectures or target.architecture in self.architectures
        )

    def same_identity(self, other: NativeDeclaration) -> bool:
        """Whether two declarations would emit the same native plan record."""

        return (
            self.kind,
            self.package,
            self.value,
            self.detail,
            self.language,
            self.standard,
            self.operating_systems,
            self.architectures,
        ) == (
            other.kind,
            other.package,
            other.value,
            other.detail,
            other.language,
            other.standard,
            other.operating_systems,
            other.architectures,
        )


@dataclass(frozen=True)
class ModuleProvider:
    """One target-selected source dependency of an ordinary package module."""

    module: str
    implementation: str
    operating_systems: tuple[str, ...]
    architectures: tuple[str, ...]

    def selected_for(self, target: PackageTarget) -> bool:
        return (not self.operating_systems or target.operating_system in self.operating_systems) and (
            not self.architectures or target.architecture in self.architectures
        )

    def overlaps(self, other: ModuleProvider) -> bool:
        return (
            self.module == other.module
            and (
                not self.operating_systems
                or not other.operating_systems
                or bool(set(self.operating_systems) & set(other.operating_systems))
            )
            and (
                not self.architectures
                or not other.architectures
                or bool(set(self.architectures) & set(other.architectures))
            )
        )


@dataclass(frozen=True)
class NativeCallbackTable:
    """A unique SDK record of callbacks that BTRC implements through one receiver."""

    name: str
    interface: str
    context: str
    context_index: int
    methods: tuple[tuple[str, str], ...]
    label: str = ""
    reopen: str = ""
    release: str = ""


@dataclass(frozen=True)
class NativeResourceBinding:
    """Missing ownership facts for one header-declared native resource."""

    name: str
    ownership: str
    retain: str
    release: str
    release_consumption: str = ""
    cleanup_status: str = ""
    type_query: str = ""
    type_tag: str = ""
    storage: str = ""
    alias: str = ""
    constructor: str = ""
    owner: str = ""
    methods: tuple[str, ...] = ()
    table: NativeCallbackTable | None = None


@dataclass(frozen=True)
class NativeInitializerBinding:
    """Initialize one zeroed inline resource, optionally retaining copied bytes."""

    function: str
    resource: str
    parameter: str
    result: str
    success: str
    copied_input: str = ""
    length: str = ""
    status_field: str = ""


@dataclass(frozen=True)
class NativeRealtimeCallbackBinding:
    """A stored SDK callback record with registration-bound native operations."""

    name: str
    record: str
    size: str
    owner: str
    invocation: str
    operations: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class NativeCallbackBinding:
    """Foreign lifetime and context facts for a typed receiver projection."""

    parameter: str
    contexts: tuple[str, ...]
    context_indices: tuple[int, ...]
    interface: str
    lifetime: str
    failure: str
    executor: str
    unregister: str = ""
    activation_failure: str = ""
    methods: tuple[str, ...] = ()
    slot_getter: str = ""
    action_setter: str = ""
    action_getter: str = ""
    owned_arguments: tuple[int, ...] = ()
    field: str = ""
    realtime: NativeRealtimeCallbackBinding | None = None


@dataclass(frozen=True)
class NativeStringViewBinding:
    """Borrowed byte-counted native text copied into an ordinary BTRC string."""

    name: str
    data: str
    length: str
    null_length: str


@dataclass(frozen=True)
class NativeVariadicBinding:
    """One fixed C variadic shape selected by an SDK opcode constant."""

    parameter: str
    value: str
    arguments: tuple[str, ...]


@dataclass(frozen=True)
class NativeResourceOutputBinding:
    """Named, sized erased RC output projection alongside the raw SDK entry."""

    resource: str
    size_parameter: str
    alias: str


@dataclass(frozen=True)
class NativeRecordSnapshotBinding:
    """Owning values copied from checked field paths of an admitted resource."""

    result: str
    owner: str
    name: str
    fields: tuple[tuple[str, str], ...]
    byte_plane: tuple[str, str, str, str, str] = ()
    guard: tuple[str, str] = ()
    strings: tuple[tuple[str, str], ...] = ()
    byte_span: tuple[str, str, str] = ()


@dataclass(frozen=True)
class NativeBinding:
    """A header import owned by one BTRC module, not a handwritten ABI."""

    package: str
    module: str
    header: str
    language: str
    standard: str
    symbols: tuple[str, ...]
    operating_systems: tuple[str, ...] = ()
    architectures: tuple[str, ...] = ()
    read_only_borrows: tuple[str, ...] = ()
    realtime_safe: tuple[str, ...] = ()
    owned_records: tuple[str, ...] = ()
    record_inputs: tuple[str, ...] = ()
    object_fields: tuple[tuple[str, str], ...] = ()
    resources: tuple[NativeResourceBinding, ...] = ()
    owned_results: tuple[str, ...] = ()
    borrowed_parameters: tuple[str, ...] = ()
    callbacks: tuple[NativeCallbackBinding, ...] = ()
    main_thread_globals: tuple[str, ...] = ()
    string_views: tuple[NativeStringViewBinding, ...] = ()
    record_outputs: tuple[str, ...] = ()
    owned_output_fields: tuple[str, ...] = ()
    null_output_fields: tuple[str, ...] = ()
    borrowed_results: tuple[tuple[str, str], ...] = ()
    static_globals: tuple[str, ...] = ()
    resource_parameters: tuple[tuple[str, str], ...] = ()
    resource_results: tuple[tuple[str, str], ...] = ()
    owned_outputs: tuple[tuple[str, str], ...] = ()
    variadic_calls: tuple[NativeVariadicBinding, ...] = ()
    output_offsets: tuple[tuple[str, str, str, str], ...] = ()
    copied_results: tuple[tuple[str, str, str, str, tuple[str, ...]], ...] = ()
    owned_output_resources: tuple[tuple[str, NativeResourceOutputBinding], ...] = ()
    record_snapshots: tuple[NativeRecordSnapshotBinding, ...] = ()
    initializers: tuple[NativeInitializerBinding, ...] = ()
    copied_inputs: tuple[tuple[str, str, str], ...] = ()

    def selected_for(self, target: PackageTarget) -> bool:
        return (not self.operating_systems or target.operating_system in self.operating_systems) and (
            not self.architectures or target.architecture in self.architectures
        )

    def overlaps(self, other: NativeBinding) -> bool:
        return (
            self.module == other.module
            and bool(set(self.symbols) & set(other.symbols))
            and (
                not self.operating_systems
                or not other.operating_systems
                or bool(set(self.operating_systems) & set(other.operating_systems))
            )
            and (
                not self.architectures
                or not other.architectures
                or bool(set(self.architectures) & set(other.architectures))
            )
        )


@dataclass(frozen=True)
class PackageNode:
    """One package identity with dependency-local aliases."""

    name: str
    root: str
    dependencies: Mapping[str, str]
    source: Mapping[str, str]
    manifest_hash: str
    native: tuple[NativeDeclaration, ...] = ()
    bindings: tuple[NativeBinding, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dependencies", MappingProxyType(dict(self.dependencies)))
        object.__setattr__(self, "source", MappingProxyType(dict(self.source)))


@dataclass(frozen=True)
class NativeGeneratedUnit:
    """Compiler-emitted adapter text, never a file inside a source package."""

    name: str
    language: str
    standard: str
    memory_management: str
    source: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "language": self.language,
            "standard": self.standard,
            "memory-management": self.memory_management,
            "source": self.source,
        }


@dataclass(frozen=True)
class NativeLinkPlan:
    """Canonical, target-filtered native build requirements."""

    target: PackageTarget
    packages: tuple[PackageNode, ...] = ()
    declarations: tuple[NativeDeclaration, ...] = ()
    generated_units: tuple[NativeGeneratedUnit, ...] = ()
    # Ordered absolute paths of secondary compiler outputs (schema 4).
    emitted_units: tuple[str, ...] = ()

    @property
    def bindings(self) -> tuple[NativeBinding, ...]:
        """Compiler-only imports; these are not linker units or schema-1 records."""
        return tuple(
            binding
            for package in sorted(self.packages, key=lambda package: package.name)
            for binding in package.bindings
            if binding.selected_for(self.target)
        )

    def require_resolved_bindings(self) -> None:
        if self.bindings:
            binding = self.bindings[0]
            raise IncludeResolutionError(
                f"native binding for module {binding.module!r} requires BTRC_NATIVE_HEADER_READER for typed header imports"
            )

    def input_paths(self) -> tuple[str, ...]:
        """Known package/native inputs that generated output must not replace."""
        paths = {
            os.path.join(package.root, filename) for package in self.packages for filename in ("btrc.toml", "btrc.lock")
        }
        paths.update(
            item.value
            for item in self.declarations
            if item.kind in {"source", "header"} and item.selected_for(self.target)
        )
        paths.update(binding.header for binding in self.bindings)
        return tuple(sorted(paths))

    @classmethod
    def empty(cls, target: PackageTarget | None = None) -> NativeLinkPlan:
        return cls(target or PackageTarget.parse(None))

    @property
    def linker_language(self) -> str:
        return (
            "c++"
            if any(unit.language in {"c++", "objective-c++"} for unit in self.generated_units)
            or any(
                item.selected_for(self.target) and item.kind == "source" and item.language in {"c++", "objective-c++"}
                for item in self.declarations
            )
            else "c"
        )

    @staticmethod
    def _path_record(item: NativeDeclaration) -> dict[str, str]:
        return {"package": item.package, "path": item.value}

    @staticmethod
    def _name_record(item: NativeDeclaration) -> dict[str, str]:
        return {"name": item.value, "package": item.package}

    def as_dict(self) -> dict:
        selected = tuple(item for item in self.declarations if item.selected_for(self.target))
        sources = [
            {
                "language": item.language,
                "package": item.package,
                "path": item.value,
                "standard": item.standard,
            }
            for item in selected
            if item.kind == "source"
        ]
        defines = [
            {"name": item.value, "package": item.package, "value": item.detail}
            for item in selected
            if item.kind == "define"
        ]
        result = {
            "defines": sorted(defines, key=lambda item: (item["package"], item["name"], item["value"])),
            "frameworks": sorted(
                (self._name_record(item) for item in selected if item.kind == "framework"),
                key=lambda item: (item["package"], item["name"]),
            ),
            "headers": sorted(
                (self._path_record(item) for item in selected if item.kind == "header"),
                key=lambda item: (item["package"], item["path"]),
            ),
            "include-directories": sorted(
                (self._path_record(item) for item in selected if item.kind == "include-directory"),
                key=lambda item: (item["package"], item["path"]),
            ),
            "linker-language": self.linker_language,
            "packages": [
                {
                    "dependencies": dict(sorted(package.dependencies.items())),
                    "name": package.name,
                    "root": package.root,
                }
                for package in sorted(self.packages, key=lambda package: package.name)
            ],
            "pkg-config": sorted(
                (self._name_record(item) for item in selected if item.kind == "pkg-config"),
                key=lambda item: (item["package"], item["name"]),
            ),
            "schema": NATIVE_LINK_PLAN_SCHEMA,
            "target": self.target.as_dict(),
            "units": sorted(sources, key=lambda item: (item["package"], item["path"], item["language"])),
        }
        if self.generated_units:
            result["schema"] = 2
            result["generated-units"] = [
                unit.as_dict() for unit in sorted(self.generated_units, key=lambda unit: unit.name)
            ]
        if self.emitted_units:
            result["schema"] = 4
            result["emitted-units"] = list(self.emitted_units)
        return result

    def canonical_json(self) -> str:
        return (
            json.dumps(
                self.as_dict(),
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        )

    @staticmethod
    def output_prefix(prefix: str) -> str:
        """Resolve the destination directory without following the output file.

        Resolve a complete output name first: prefixes ending in '/', '.' or
        '..' name files only after their unit suffix has been appended.
        """
        suffix = ".unit-1.c"
        directory, filename = os.path.split(prefix + suffix)
        return os.path.join(os.path.realpath(directory or "."), filename).removesuffix(suffix)

    def with_emitted_units(self, prefix: str | None, count: int) -> NativeLinkPlan:
        """Name secondary outputs independently of the primary C destination."""
        if type(count) is not int or count < 0 or (count and not prefix):
            raise ValueError("emitted units require a nonnegative count and an output prefix")
        absolute_prefix = self.output_prefix(prefix) if count else ""
        return replace(
            self,
            emitted_units=tuple(f"{absolute_prefix}.unit-{index}.c" for index in range(1, count + 1)),
        )

    def with_cached_artifacts(
        self, serialized: str, emitted_units: int, units_prefix: str | None = None
    ) -> NativeLinkPlan | None:
        """Restore generated adapters only when all resolved plan facts match."""
        if type(emitted_units) is not int or emitted_units < 0:
            return None
        try:
            document = json.loads(serialized)
            if not isinstance(document, dict):
                return None
            records = document.get("generated-units", [])
            if not isinstance(records, list):
                return None
            units = []
            for record in records:
                if (
                    not isinstance(record, dict)
                    or set(record) != {"name", "language", "standard", "memory-management", "source"}
                    or not all(isinstance(value, str) and value and "\0" not in value for value in record.values())
                ):
                    return None
                language = record["language"]
                memory = "arc" if language.startswith("objective-c") else "raii" if language == "c++" else "manual"
                if (
                    not _IDENTIFIER.fullmatch(record["name"])
                    or record["standard"] not in _SOURCE_STANDARDS.get(language, ())
                    or record["memory-management"] != memory
                ):
                    return None
                units.append(
                    NativeGeneratedUnit(record["name"], language, record["standard"], memory, record["source"])
                )
            if len({unit.name for unit in units}) != len(units):
                return None
            restored = replace(self, generated_units=tuple(units)).with_emitted_units(units_prefix, emitted_units)
            # Canonical equality rejects unknown/duplicate fields, wrong unit
            # count, stale package roots/flags/target, and changed schema/order.
            return restored if restored.canonical_json() == serialized else None
        except (ValueError, RecursionError):
            return None

    @staticmethod
    def _source_identity(path: str) -> str:
        return os.path.normcase(os.path.realpath(os.path.abspath(path)))

    @classmethod
    def reached_packages(cls, packages: Sequence[PackageNode], sources: Iterable[str]) -> frozenset[str]:
        """Names of the packages whose root owns one of the sources (deepest root wins)."""

        source_identities = frozenset(cls._source_identity(path) for path in sources)
        package_roots = {package.name: cls._source_identity(package.root) for package in packages}
        reached: set[str] = set()
        for source in source_identities:
            owners = []
            for package in packages:
                try:
                    if os.path.commonpath((source, package_roots[package.name])) == package_roots[package.name]:
                        owners.append(package)
                except ValueError:
                    continue
            owner = max(owners, key=lambda package: len(package_roots[package.name]), default=None)
            if owner is not None:
                reached.add(owner.name)
        return frozenset(reached)

    def for_sources(self, sources: Iterable[str]) -> NativeLinkPlan:
        """Project this resolved package graph to loaded source owners."""

        sources = tuple(sources)
        source_identities = frozenset(self._source_identity(path) for path in sources)
        reached_packages = self.reached_packages(self.packages, sources)

        packages = tuple(
            PackageNode(
                package.name,
                package.root,
                {alias: target for alias, target in package.dependencies.items() if target in reached_packages},
                package.source,
                package.manifest_hash,
                package.native,
                tuple(
                    binding
                    for binding in package.bindings
                    if self._source_identity(binding.module) in source_identities
                ),
            )
            for package in self.packages
            if package.name in reached_packages
        )
        declarations = tuple(
            declaration
            for declaration in self.declarations
            if declaration.package in reached_packages
            and (
                not declaration.modules
                or any(self._source_identity(module) in source_identities for module in declaration.modules)
            )
        )
        return NativeLinkPlan(self.target, packages, declarations, self.generated_units)

    STDLIB_PACKAGE_PREFIX = "btrc_stdlib_"

    def with_stdlib(self, stdlib_directory: str, sources: Iterable[str]) -> NativeLinkPlan:
        """Compose compiler-owned native metadata through the ordinary manifest graph.

        The stdlib root manifest names ``btrc_stdlib_runtime`` and depends only
        on path packages inside the stdlib tree, one per group folder; every
        package in that graph carries a reserved ``btrc_stdlib_`` identity and
        keeps its native metadata beside the modules it describes.
        """
        root = os.path.realpath(stdlib_directory)
        path = os.path.join(root, "btrc.toml")
        if not os.path.exists(path):
            return self
        sources = tuple(sources)
        try:
            packages = self._stdlib_packages(root, path, sources)
        except (OSError, ValueError) as error:
            raise IncludeResolutionError(f"stdlib native manifest: {error}") from error
        native = tuple(declaration for package in packages for declaration in package.native)
        selected = NativeLinkPlan(self.target, tuple(packages), native).for_sources(sources)
        if not selected.declarations and not selected.bindings:
            return self
        known = {package.name: package for package in packages}
        for existing in self.packages:
            if not existing.name.startswith(self.STDLIB_PACKAGE_PREFIX):
                continue
            package = known.get(existing.name)
            if (
                package is not None
                and self._source_identity(existing.root) == self._source_identity(package.root)
                and existing.manifest_hash == package.manifest_hash
            ):
                return self
            raise IncludeResolutionError(
                f"package identity {existing.name!r} is reserved for compiler-owned stdlib runtimes"
            )
        return NativeLinkPlan(
            self.target,
            self.packages + selected.packages,
            self.declarations + selected.declarations,
            self.generated_units,
        )

    def _stdlib_packages(self, root: str, path: str, sources: Iterable[str]) -> tuple[PackageNode, ...]:
        """Load the stdlib root manifest and every path dependency beneath the stdlib root.

        Every manifest is read and its identity and dependencies validated, but
        native blocks and bindings finish only for packages whose root owns one
        of the program's sources: ``for_sources`` drops the rest anyway, and the
        self-hosted compiler finishes them lazily the same way, so a program
        that never reaches a stdlib group pays for its manifest parse only.
        """
        reader = PackageManifestReader()
        validator = PackageManifestValidator()
        packages: list[PackageNode] = []
        manifests: dict[str, tuple[dict, str, str]] = {}
        names_by_root: dict[str, str] = {}
        loading: list[str] = []

        def load(manifest_path: str, alias: str | None) -> str:
            package_root = os.path.dirname(manifest_path)
            if package_root in loading:
                raise ValueError(f"stdlib package dependency cycle through {manifest_path!r}")
            loading.append(package_root)
            manifest, encoded = reader.read_document(manifest_path)
            name = validator.validate_identity(manifest, manifest_path)
            if alias is None and name != "btrc_stdlib_runtime":
                raise ValueError("stdlib manifest must declare btrc_stdlib_runtime")
            if alias is not None and not name.startswith(self.STDLIB_PACKAGE_PREFIX):
                raise ValueError(f"stdlib group {alias!r} must declare a {self.STDLIB_PACKAGE_PREFIX} package identity")
            if name in {package.name for package in packages}:
                raise ValueError(f"duplicate stdlib package identity {name!r}")
            dependencies: dict[str, str] = {}
            for dependency_alias, specification in validator.dependencies(manifest, manifest_path).items():
                if "path" not in specification:
                    raise ValueError(f"stdlib dependency {dependency_alias!r} must be a path package inside the stdlib")
                target_root = os.path.realpath(os.path.join(package_root, specification["path"]))
                if os.path.commonpath((root, target_root)) != root or target_root == root:
                    raise ValueError(f"stdlib dependency {dependency_alias!r} must stay inside the stdlib tree")
                target_name = names_by_root.get(target_root) or load(
                    os.path.join(target_root, "btrc.toml"), dependency_alias
                )
                dependencies[dependency_alias] = target_name
            packages.append(
                PackageNode(
                    name,
                    package_root,
                    dependencies,
                    {"path": package_root},
                    hashlib.sha256(encoded).hexdigest(),
                    (),
                    (),
                )
            )
            manifests[name] = (manifest, package_root, manifest_path)
            names_by_root[package_root] = name
            loading.pop()
            return name

        load(path, None)
        reached = self.reached_packages(packages, sources)
        finished: list[PackageNode] = []
        for package in packages:
            if package.name not in reached:
                finished.append(package)
                continue
            manifest, package_root, manifest_path = manifests[package.name]
            finished.append(
                replace(
                    package,
                    native=validator.native(manifest, package_root, package.name, manifest_path),
                    bindings=validator.bindings(manifest, package_root, package.name, manifest_path),
                )
            )
        return tuple(finished)


@dataclass(frozen=True)
class ResolvedPackages:
    """Immutable dependency universe governing one compiler invocation."""

    manifest_path: str | None
    entries: Mapping[str, Mapping[str, str]]
    nodes: Mapping[str, PackageNode] | None = None
    root_package: str = ""
    native_plan: NativeLinkPlan | None = None

    def __post_init__(self) -> None:
        frozen = {name: MappingProxyType(dict(entry)) for name, entry in self.entries.items()}
        object.__setattr__(self, "entries", MappingProxyType(frozen))
        object.__setattr__(self, "nodes", MappingProxyType(dict(self.nodes or {})))
        if self.native_plan is None:
            object.__setattr__(self, "native_plan", NativeLinkPlan.empty())

    @classmethod
    def empty(cls, target: PackageTarget | None = None) -> ResolvedPackages:
        return cls(manifest_path=None, entries={}, native_plan=NativeLinkPlan.empty(target))

    def _owner_for(self, source_path: str | None) -> PackageNode | None:
        if not source_path or not self.nodes:
            return None
        source = os.path.realpath(source_path)
        matches = []
        for package in self.nodes.values():
            try:
                if os.path.commonpath((source, package.root)) == package.root:
                    matches.append(package)
            except ValueError:
                continue
        return max(matches, key=lambda package: len(package.root), default=None)

    def paths_for_import(self, spec: str, source_path: str | None = None) -> tuple[str, ...]:
        """Resolve a package import, or return empty when its head is local."""

        spec = spec.strip()
        head, _, rest = spec.partition(".")
        owner = self._owner_for(source_path)
        target = owner.dependencies.get(head) if owner is not None else None
        node = self.nodes.get(target) if target is not None else None
        package = self.entries.get(head) if node is None else {"path": node.root}
        if package is None:
            return ()
        root = package["path"]
        module = rest if rest else (node.name if node is not None else head)
        relative = module.replace(".", "/")
        for candidate in (
            os.path.join(root, "src", relative + ".btrc"),
            os.path.join(root, relative + ".btrc"),
        ):
            if os.path.exists(candidate):
                return (os.path.abspath(candidate),)
        raise IncludeResolutionError(
            f"package import '{spec}' not found in dependency '{head}'\n  package root: {root}"
        )


class PackageImportPolicy:
    """Invocation-local package boundaries, checked before import de-duplication."""

    def __init__(self, target: PackageTarget | None = None) -> None:
        self._target = target
        self._owners: dict[str, str | None] = {}
        self._exports: dict[str, tuple[str, frozenset[str] | None]] = {}
        self._providers: dict[str, dict[str, list[ModuleProvider]]] = {}

    def provider_for(self, source: str) -> tuple[str, ...]:
        identity = os.path.normcase(os.path.realpath(source))
        manifest_path = self._manifest_for(identity)
        if manifest_path is None:
            return ()
        if manifest_path not in self._providers:
            try:
                manifest = PackageManifestReader().read(manifest_path)
                providers: dict[str, list[ModuleProvider]] = {}
                if "manifest-version" in manifest:
                    validator = PackageManifestValidator()
                    validator.validate_identity(manifest, manifest_path)
                    for provider in validator.providers(manifest, manifest_path):
                        providers.setdefault(os.path.normcase(provider.module), []).append(provider)
                self._providers[manifest_path] = providers
            except (OSError, ValueError) as error:
                raise IncludeResolutionError(str(error)) from error
        candidates = self._providers[manifest_path].get(identity, ())
        if not candidates:
            return ()
        if self._target is None:
            raise IncludeResolutionError(f"module {source!r} requires a compilation target for provider selection")
        for provider in candidates:
            if provider.selected_for(self._target):
                return (provider.implementation,)
        raise IncludeResolutionError(
            f"module {source!r} has no provider for target {self._target.operating_system}-{self._target.architecture}"
        )

    def _manifest_for(self, source: str) -> str | None:
        directory = os.path.dirname(os.path.normcase(os.path.abspath(source)))
        visited = []
        while directory not in self._owners:
            visited.append(directory)
            candidate = os.path.join(directory, "btrc.toml")
            if os.path.exists(candidate):
                self._owners[directory] = os.path.normcase(os.path.realpath(candidate))
                break
            parent = os.path.dirname(directory)
            if parent == directory:
                self._owners[directory] = None
                break
            directory = parent
        owner = self._owners[directory]
        for path in visited:
            self._owners[path] = owner
        return owner

    def check(self, source: str, target: str) -> None:
        self._check_owner(source, target)
        self._check_owner(os.path.realpath(source), os.path.realpath(target))

    def _check_owner(self, source: str, target: str) -> None:
        name = self._private_owner(source, target)
        if name is not None:
            raise IncludeResolutionError(f"module {target!r} is private to package {name!r}; import an exported module")

    def permits_reference(self, source: str, target: str) -> bool:
        """Transitive imports do not re-export private implementation names."""

        return (
            self._private_owner(source, target) is None
            and self._private_owner(os.path.realpath(source), os.path.realpath(target)) is None
        )

    def _private_owner(self, source: str, target: str) -> str | None:
        manifest_path = self._manifest_for(target)
        if manifest_path is None or manifest_path == self._manifest_for(source):
            return
        if manifest_path not in self._exports:
            try:
                manifest = PackageManifestReader().read(manifest_path)
                if "manifest-version" not in manifest:
                    self._exports[manifest_path] = ("", None)
                else:
                    validator = PackageManifestValidator()
                    name = validator.validate_identity(manifest, manifest_path)
                    exports = validator.exported_modules(manifest, manifest_path)
                    self._exports[manifest_path] = (
                        name,
                        None if exports is None else frozenset(os.path.normcase(path) for path in exports),
                    )
            except (OSError, ValueError) as error:
                raise IncludeResolutionError(str(error)) from error
        name, exports = self._exports[manifest_path]
        if exports is not None and os.path.normcase(os.path.realpath(target)) not in exports:
            return name
        return None


class PackageManifestReader:
    """Own UTF-8 TOML reads for package resolution."""

    def __init__(
        self,
        *,
        file_store: PackageFileStore | None = None,
    ) -> None:
        self.file_store = file_store or PackageFileStore()

    def read_document(self, path: str) -> tuple[dict, bytes]:
        """Load and parse one manifest while retaining the exact hashed bytes."""
        manifest_file = self.file_store.open_regular_binary(
            path,
            follow_symlinks=True,
        )
        if manifest_file is None:
            raise ValueError(f"package manifest '{path}' is not a regular file")
        try:
            with manifest_file:
                encoded = manifest_file.read()
        except (OSError, MemoryError) as error:
            raise ValueError(f"cannot read package manifest '{path}': {error}") from error
        try:
            text = encoded.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"package manifest '{path}' is not valid UTF-8 at byte {error.start}") from error
        try:
            manifest = tomllib.loads(text)
        except (tomllib.TOMLDecodeError, RecursionError) as error:
            raise ValueError(f"cannot parse package manifest '{path}': {error}") from error
        if not isinstance(manifest, dict):
            raise ValueError(f"package manifest '{path}' must contain a TOML table")
        return manifest, encoded

    def read(self, path: str) -> dict:
        """Load one regular manifest without unbounded input allocation."""

        manifest, _ = self.read_document(path)
        return manifest


class PackageManifestValidator:
    """Validate the closed version-1 manifest model."""

    _TOP_LEVEL_FIELDS = frozenset({"manifest-version", "package", "dependencies", "native"})
    _NATIVE_FIELDS = frozenset(
        {"sources", "headers", "include-directories", "defines", "frameworks", "pkg-config", "bindings"}
    )

    @staticmethod
    def _reject_unknown(value: Mapping, allowed: frozenset[str], context: str) -> None:
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"{context} contains unexpected field {unknown[0]!r}")

    @staticmethod
    def _identifier(value, context: str) -> str:
        if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"{context} must be an ASCII identifier")
        return value

    @staticmethod
    def _target_values(entry: Mapping, field: str, allowed: frozenset[str], context: str) -> tuple[str, ...]:
        value = entry.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{context}.{field} must be an array of strings")
        if len(set(value)) != len(value):
            raise ValueError(f"{context}.{field} contains a duplicate value")
        invalid = sorted(set(value) - allowed)
        if invalid:
            raise ValueError(f"{context}.{field} contains unsupported value {invalid[0]!r}")
        return tuple(sorted(value))

    @staticmethod
    def _inside_path(root: str, relative, context: str, *, directory: bool) -> str:
        if not isinstance(relative, str) or not relative or os.path.isabs(relative):
            raise ValueError(f"{context} must be a non-empty package-relative path")
        root = os.path.realpath(root)
        candidate = os.path.realpath(os.path.join(root, relative))
        try:
            inside = os.path.commonpath((root, candidate)) == root
        except ValueError:
            inside = False
        if not inside:
            raise ValueError(f"{context} escapes package root {root!r}")
        present = os.path.isdir(candidate) if directory else os.path.isfile(candidate)
        if not present:
            kind = "directory" if directory else "file"
            raise ValueError(f"{context} does not name a {kind}: {relative!r}")
        return candidate

    @staticmethod
    def _module_paths(
        root: str, entry: Mapping, context: str, *, field: str = "modules", allow_empty: bool = False
    ) -> tuple[str, ...]:
        if field not in entry:
            return ()
        modules = entry[field]
        if not isinstance(modules, list) or not all(isinstance(module, str) for module in modules):
            raise ValueError(f"{context}.{field} must be an array of strings")
        if not modules and not allow_empty:
            raise ValueError(f"{context}.{field} must not be empty")
        if len(set(modules)) != len(modules):
            raise ValueError(f"{context}.{field} contains a duplicate value")
        resolved = []
        canonical_root = os.path.realpath(root)
        for module in sorted(modules):
            if _MODULE_NAME.fullmatch(module) is None:
                raise ValueError(f"{context}.{field} contains invalid module {module!r}")
            relative = module.replace(".", os.sep) + ".btrc"
            candidates = (os.path.join(root, "src", relative), os.path.join(root, relative))
            selected = next((candidate for candidate in candidates if os.path.isfile(candidate)), None)
            if selected is None:
                raise ValueError(f"{context}.{field} names unknown module {module!r}")
            canonical = os.path.realpath(selected)
            try:
                inside = os.path.commonpath((canonical_root, canonical)) == canonical_root
            except ValueError:
                inside = False
            if not inside:
                raise ValueError(f"{context}.{field} module {module!r} escapes package root {canonical_root!r}")
            resolved.append(canonical)
        return tuple(resolved)

    def validate_identity(self, manifest: Mapping, path: str) -> str:
        self._reject_unknown(manifest, self._TOP_LEVEL_FIELDS, f"package manifest {path!r}")
        if manifest.get("manifest-version") != PACKAGE_MANIFEST_VERSION:
            raise ValueError(
                f"package manifest {path!r} must declare integer manifest-version = {PACKAGE_MANIFEST_VERSION}"
            )
        package = manifest.get("package")
        if not isinstance(package, dict):
            raise ValueError(f"package manifest {path!r} must contain a [package] table")
        self._reject_unknown(
            package, frozenset({"name", "exports", "providers"}), f"package manifest {path!r} [package]"
        )
        self.exported_modules(manifest, path)
        self.providers(manifest, path)
        return self._identifier(package.get("name"), f"package manifest {path!r} package.name")

    def providers(self, manifest: Mapping, path: str) -> tuple[ModuleProvider, ...]:
        entries = manifest.get("package", {}).get("providers", [])
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError(f"package manifest {path!r} package.providers must be an array of tables")
        providers = []
        root = os.path.dirname(path)
        for entry in entries:
            context = f"package manifest {path!r} package.providers"
            self._reject_unknown(entry, frozenset({"module", "implementation", "os", "arch"}), context)
            paths = []
            for field in ("module", "implementation"):
                value = entry.get(field)
                if not isinstance(value, str) or _MODULE_NAME.fullmatch(value) is None:
                    raise ValueError(f"{context}.{field} must be a dotted module name")
                paths.append(self._module_paths(root, {"modules": [value]}, context)[0])
            if paths[0] == paths[1]:
                raise ValueError(f"{context} cannot select its own module as implementation")
            provider = ModuleProvider(
                *paths,
                self._target_values(entry, "os", _TARGET_OPERATING_SYSTEMS, context),
                self._target_values(entry, "arch", _TARGET_ARCHITECTURES, context),
            )
            if any(provider.overlaps(previous) for previous in providers):
                raise ValueError(f"{context} overlaps a provider for the same module and target")
            providers.append(provider)
        return tuple(providers)

    def exported_modules(self, manifest: Mapping, path: str) -> tuple[str, ...] | None:
        package = manifest.get("package", {})
        if "exports" not in package:
            return None
        return self._module_paths(
            os.path.dirname(path), package, f"package manifest {path!r} package", field="exports", allow_empty=True
        )

    def dependencies(self, manifest: Mapping, path: str) -> dict[str, Mapping]:
        dependencies = manifest.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ValueError(f"package manifest {path!r} [dependencies] must be a table")
        validated = {}
        for alias, specification in dependencies.items():
            self._identifier(alias, f"package manifest {path!r} dependency alias")
            if not isinstance(specification, dict):
                raise ValueError(f"dependency {alias!r} in {path!r} must be an inline table")
            source_fields = set(specification) & {"path", "git"}
            if len(source_fields) != 1:
                raise ValueError(f"dependency {alias!r} in {path!r} must specify exactly one of path or git")
            if "path" in specification:
                self._reject_unknown(specification, frozenset({"path"}), f"dependency {alias!r} in {path!r}")
                value = specification["path"]
                if not isinstance(value, str) or not value:
                    raise ValueError(f"dependency {alias!r} in {path!r} path must be non-empty text")
                if os.path.isabs(value):
                    raise ValueError(f"dependency {alias!r} in {path!r} path must be relative")
            else:
                self._reject_unknown(
                    specification,
                    frozenset({"git", "rev", "tag", "branch"}),
                    f"dependency {alias!r} in {path!r}",
                )
                if not isinstance(specification["git"], str) or not specification["git"]:
                    raise ValueError(f"dependency {alias!r} in {path!r} git must be non-empty text")
                refs = [field for field in ("rev", "tag", "branch") if field in specification]
                if len(refs) > 1:
                    raise ValueError(f"dependency {alias!r} in {path!r} may specify only one Git ref")
                if refs and (not isinstance(specification[refs[0]], str) or not specification[refs[0]]):
                    raise ValueError(f"dependency {alias!r} in {path!r} Git ref must be non-empty text")
            validated[alias] = specification
        return validated

    def native(self, manifest: Mapping, root: str, package: str, path: str) -> tuple[NativeDeclaration, ...]:
        native = manifest.get("native", {})
        if not isinstance(native, dict):
            raise ValueError(f"package manifest {path!r} [native] must be a table")
        self._reject_unknown(native, self._NATIVE_FIELDS, f"package manifest {path!r} [native]")
        declarations: list[NativeDeclaration] = []
        for field in sorted(self._NATIVE_FIELDS - {"bindings"}):
            entries = native.get(field, [])
            if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
                raise ValueError(f"package manifest {path!r} native.{field} must be an array of tables")
            for index, entry in enumerate(entries):
                context = f"package manifest {path!r} native.{field}[{index}]"
                operating_systems = self._target_values(entry, "os", _TARGET_OPERATING_SYSTEMS, context)
                architectures = self._target_values(entry, "arch", _TARGET_ARCHITECTURES, context)
                modules = self._module_paths(root, entry, context)
                predicate_fields = frozenset({"os", "arch", "modules"})
                if field == "sources":
                    self._reject_unknown(
                        entry,
                        predicate_fields | {"path", "language", "standard"},
                        context,
                    )
                    language = entry.get("language")
                    standard = entry.get("standard")
                    if language not in _SOURCE_STANDARDS:
                        raise ValueError(f"{context}.language is unsupported")
                    if standard not in _SOURCE_STANDARDS[language]:
                        raise ValueError(f"{context}.standard is unsupported for {language}")
                    value = self._inside_path(root, entry.get("path"), f"{context}.path", directory=False)
                    declaration = NativeDeclaration(
                        "source",
                        package,
                        value,
                        language=language,
                        standard=standard,
                        operating_systems=operating_systems,
                        architectures=architectures,
                        modules=modules,
                    )
                elif field in {"headers", "include-directories"}:
                    self._reject_unknown(entry, predicate_fields | {"path"}, context)
                    kind = "header" if field == "headers" else "include-directory"
                    value = self._inside_path(
                        root,
                        entry.get("path"),
                        f"{context}.path",
                        directory=field == "include-directories",
                    )
                    declaration = NativeDeclaration(
                        kind,
                        package,
                        value,
                        operating_systems=operating_systems,
                        architectures=architectures,
                        modules=modules,
                    )
                elif field == "defines":
                    self._reject_unknown(entry, predicate_fields | {"name", "value"}, context)
                    name = self._identifier(entry.get("name"), f"{context}.name")
                    value = entry.get("value")
                    if not isinstance(value, str):
                        raise ValueError(f"{context}.value must be text")
                    declaration = NativeDeclaration(
                        "define",
                        package,
                        name,
                        detail=value,
                        operating_systems=operating_systems,
                        architectures=architectures,
                        modules=modules,
                    )
                else:
                    self._reject_unknown(entry, predicate_fields | {"name"}, context)
                    name = entry.get("name")
                    if not isinstance(name, str) or _NATIVE_NAME.fullmatch(name) is None:
                        raise ValueError(f"{context}.name contains unsupported characters")
                    declaration = NativeDeclaration(
                        "framework" if field == "frameworks" else "pkg-config",
                        package,
                        name,
                        operating_systems=operating_systems,
                        architectures=architectures,
                        modules=modules,
                    )
                if any(declaration.same_identity(existing) for existing in declarations):
                    raise ValueError(f"{context} duplicates an earlier native declaration")
                declarations.append(declaration)
        return tuple(sorted(declarations))

    def _callback_bindings(self, values, symbols, context, language) -> tuple[NativeCallbackBinding, ...]:
        if not isinstance(values, dict):
            raise ValueError(f"{context}.callbacks must map function.parameter names to callback facts")
        callbacks = []
        for parameter, value in sorted(values.items()):
            self._resource_functions([parameter], symbols, context, "callbacks", parameters=True)
            location = f"{context}.callbacks.{parameter}"
            if not isinstance(value, dict):
                raise ValueError(f"{location} must be a callback declaration")
            self._reject_unknown(
                value,
                frozenset(
                    {
                        "context",
                        "context-index",
                        "interface",
                        "lifetime",
                        "failure",
                        "executor",
                        "unregister",
                        "activation-failure",
                        "cancellation",
                        "methods",
                        "slot-getter",
                        "action-setter",
                        "action-getter",
                        "owned-arguments",
                        "field",
                        "name",
                        "record",
                        "size",
                        "owner",
                        "invocation",
                        "operations",
                    }
                ),
                location,
            )
            has_context = "context" in value or "context-index" in value
            context_names = value.get("context", [])
            if not isinstance(context_names, list):
                context_names = [context_names]
            context_names = tuple(sorted(self._identifier(name, f"{location}.context") for name in context_names))
            interface = self._identifier(value.get("interface"), f"{location}.interface")
            indices = value.get("context-index", [])
            if not isinstance(indices, list):
                indices = [indices]
            if any(type(index) is not int or index < 0 or index > 999999999 for index in indices):
                raise ValueError(f"{location}.context-index must be a nonnegative native parameter index")
            if (
                len(context_names) != len(indices)
                or len(set(context_names)) != len(context_names)
                or len(set(indices)) != len(indices)
                or ((has_context or language == "c") and not indices)
            ):
                raise ValueError(f"{location}: context/context-index require equally sized nonempty distinct slots")
            lifetime = value.get("lifetime")
            if lifetime not in {"call", "stored", "one-shot"}:
                raise ValueError(f"{location}.lifetime requires call, stored or one-shot")
            realtime = self._realtime_callback_binding(value, symbols, location, language, lifetime)
            callback_field = self._identifier(value["field"], f"{location}.field") if "field" in value else ""
            if callback_field and (language != "c" or (lifetime != "one-shot" and realtime is None)):
                raise ValueError(f"{location}.field requires a C one-shot callback")
            if len(indices) > 1 and not callback_field:
                raise ValueError(f"{location}: multiple context slots require a callback field")
            owned_arguments = value.get("owned-arguments", [])
            if "owned-arguments" in value and (language != "c" or lifetime != "one-shot"):
                raise ValueError(f"{location}.owned-arguments requires a C one-shot callback")
            if (
                not isinstance(owned_arguments, list)
                or any(type(index) is not int or index < 0 or index > 999999999 for index in owned_arguments)
                or len(set(owned_arguments)) != len(owned_arguments)
            ):
                raise ValueError(f"{location}.owned-arguments requires distinct nonnegative native parameter indices")
            unregister = value.get("unregister", "")
            activation_failure = value.get("activation-failure", "")
            methods = value.get("methods", [])
            slot_getter = value.get("slot-getter", "")
            action_setter = value.get("action-setter", "")
            action_getter = value.get("action-getter", "")
            action = "action-setter" in value or "action-getter" in value
            if "methods" in value or "slot-getter" in value or action:
                if lifetime != "stored" or language != "objective-c" or has_context:
                    raise ValueError(f"{location}: delegate methods require a stored Objective-C callback")
                if action:
                    if "methods" in value or any(
                        not isinstance(operation, str) or operation not in symbols
                        for operation in (action_setter, action_getter)
                    ):
                        raise ValueError(
                            f"{location}: actions require selected action-setter/action-getter and no methods"
                        )
                elif (
                    not isinstance(methods, list)
                    or not methods
                    or any(not isinstance(method, str) or method not in symbols for method in methods)
                ):
                    raise ValueError(f"{location}.methods must name selected native methods")
                if len(set(methods)) != len(methods):
                    raise ValueError(f"{location}.methods contains duplicate methods")
                if not isinstance(slot_getter, str) or slot_getter not in symbols:
                    raise ValueError(f"{location}.slot-getter must name a selected native method")
                if unregister != parameter.rsplit(".", 1)[0] or activation_failure != "abort":
                    raise ValueError(
                        f"{location}: delegate cancellation requires its setter and activation-failure abort"
                    )
            if lifetime == "stored":
                if language != "objective-c" and realtime is None:
                    raise ValueError(f"{location}: stored callbacks currently require Objective-C blocks")
                if not isinstance(unregister, str) or unregister not in symbols:
                    raise ValueError(f"{location}.unregister must name a selected native method")
                if not isinstance(activation_failure, str) or activation_failure not in {"unpublished", "abort"}:
                    raise ValueError(f"{location}.activation-failure requires unpublished or abort")
                if value.get("cancellation") != "entry-barrier":
                    raise ValueError(f"{location}.cancellation requires entry-barrier")
            elif lifetime == "one-shot":
                if "unregister" in value or (language == "objective-c" and has_context):
                    raise ValueError(f"{location}: one-shot requires an Objective-C block without unregister/context")
                if not isinstance(activation_failure, str) or activation_failure not in {"unpublished", "abort"}:
                    raise ValueError(f"{location}.activation-failure requires unpublished or abort")
                if value.get("cancellation") != "abandon":
                    raise ValueError(f"{location}: one-shot cancellation requires abandon")
            elif any(key in value for key in ("unregister", "activation-failure", "cancellation")):
                raise ValueError(f"{location}: cancellation facts require a stored callback")
            if value.get("failure") != "abort":
                raise ValueError(f"{location}.failure currently requires abort")
            if value.get("executor") != "caller" and realtime is None:
                raise ValueError(f"{location}.executor currently requires caller")
            if interface in symbols:
                raise ValueError(f"{location}.interface conflicts with another imported name")
            callbacks.append(
                NativeCallbackBinding(
                    parameter,
                    context_names,
                    tuple(sorted(indices)),
                    interface,
                    lifetime,
                    "abort",
                    value["executor"],
                    unregister,
                    activation_failure,
                    tuple(sorted(methods)),
                    slot_getter,
                    action_setter,
                    action_getter,
                    tuple(sorted(owned_arguments)),
                    callback_field,
                    realtime,
                )
            )
        return tuple(callbacks)

    def _realtime_callback_binding(self, value, symbols, location, language, lifetime):
        fields = {"name", "record", "size", "owner", "invocation", "operations"}
        if value.get("executor") != "realtime":
            if fields.intersection(value):
                raise ValueError(f"{location}: callback operation facts require executor realtime")
            return None
        if (
            language != "c"
            or lifetime != "stored"
            or not fields.issubset(value)
            or not value.get("field")
            or value.get("activation-failure") != "abort"
            or any(
                key in value for key in ("methods", "slot-getter", "action-setter", "action-getter", "owned-arguments")
            )
        ):
            raise ValueError(
                f"{location}: realtime requires a stored C callback record, owner, invocation and operations"
            )
        selected = {field: self._identifier(value[field], f"{location}.{field}") for field in fields - {"operations"}}
        if (
            selected["record"] not in symbols
            or selected["name"] in symbols
            or selected["invocation"] in symbols
            or len({selected["name"], selected["invocation"], value.get("interface")}) != 3
            or selected["size"] == selected["owner"]
        ):
            raise ValueError(f"{location}: realtime callback names or selected record conflict")
        operations = value["operations"]
        if not isinstance(operations, dict) or not operations:
            raise ValueError(f"{location}.operations requires named selected function.parameter pairs")
        for name, parameter in operations.items():
            self._identifier(name, f"{location}.operations")
            self._resource_functions([parameter], symbols, location, "operations", parameters=True)
        return NativeRealtimeCallbackBinding(**selected, operations=tuple(sorted(operations.items())))

    def _string_view_bindings(self, values, symbols, context, language):
        if not isinstance(values, dict) or (values and language != "c"):
            raise ValueError(f"{context}.string-views must map selected C records to text facts")
        bindings = []
        for name, value in sorted(values.items()):
            self._identifier(name, f"{context}.string-views")
            if name not in symbols or not isinstance(value, dict):
                raise ValueError(f"{context}.string-views must map selected C records to text facts")
            location = f"{context}.string-views.{name}"
            self._reject_unknown(value, frozenset({"data", "length", "null-length"}), location)
            data = self._identifier(value.get("data"), f"{location}.data")
            length = self._identifier(value.get("length"), f"{location}.length")
            if data == length or value.get("null-length") not in {"zero", "zero-or-max"}:
                raise ValueError(
                    f"{location}: string views require distinct fields and null-length zero or zero-or-max"
                )
            bindings.append(NativeStringViewBinding(name, data, length, value["null-length"]))
        return tuple(bindings)

    def _resource_bindings(self, values, symbols, context, language="c") -> tuple[NativeResourceBinding, ...]:
        if not isinstance(values, dict):
            raise ValueError(f"{context}.resources must map selected typedefs to ownership declarations")
        resources = []
        operations = set()
        aliases = set()
        for name, value in sorted(values.items()):
            if language == "c++":
                location = f"{context}.resources.{name}"
                if name not in symbols or not _NATIVE_SYMBOL.fullmatch(name) or not isinstance(value, dict):
                    raise ValueError(f"{location}: C++ resources require selected SDK classes")
                ownership = value.get("ownership")
                required = {"name", "ownership", "methods"}
                required |= {"constructor", "release"} if ownership == "unique" else {"owner"}
                if ownership not in {"unique", "owner-bound-value"} or set(value) != required:
                    raise ValueError(
                        f"{location}: C++ resources require unique/default/delete or owner-bound-value facts"
                    )
                alias = self._identifier(value["name"], f"{location}.name")
                if alias in aliases or alias in symbols:
                    raise ValueError(f"{location}: C++ resource aliases must be distinct")
                methods = value["methods"]
                if (
                    not isinstance(methods, list)
                    or any(
                        not isinstance(method, str)
                        or not _IDENTIFIER.fullmatch(method.removesuffix("()"))
                        or method.removesuffix("()") in {"create", "close"}
                        for method in methods
                    )
                    or len(methods) != len({method.removesuffix("()") for method in methods})
                ):
                    raise ValueError(f"{location}.methods requires distinct unambiguous public method names")
                constructor, release, owner = (
                    value.get("constructor", ""),
                    value.get("release", ""),
                    value.get("owner", ""),
                )
                if ownership == "unique" and (constructor != "default" or release != "delete"):
                    raise ValueError(f"{location}: C++ unique construction/destruction requires default/delete")
                if ownership == "owner-bound-value" and (
                    not isinstance(owner, str)
                    or owner == name
                    or owner not in values
                    or not isinstance(values[owner], dict)
                    or values[owner].get("ownership") != "unique"
                ):
                    raise ValueError(f"{location}: owner-bound values require a selected unique originating document")
                aliases.add(alias)
                resources.append(
                    NativeResourceBinding(
                        name,
                        ownership,
                        "",
                        release,
                        alias=alias,
                        constructor=constructor,
                        owner=owner,
                        methods=tuple(sorted(methods)),
                    )
                )
                continue
            if (
                name not in symbols
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None
                or not isinstance(value, dict)
            ):
                raise ValueError(f"{context}.resources must map selected typedefs to ownership declarations")
            location = f"{context}.resources.{name}"
            self._reject_unknown(
                value,
                frozenset(
                    {
                        "ownership",
                        "retain",
                        "release",
                        "release-consumption",
                        "cleanup-status",
                        "type-query",
                        "type-tag",
                        "storage",
                        "table",
                    }
                ),
                location,
            )
            ownership = value.get("ownership")
            if ownership not in {"reference-counted", "unique"}:
                raise ValueError(f"{location}.ownership requires reference-counted or unique")
            if ownership == "unique" and "retain" in value:
                raise ValueError(f"{location}: unique resources must not declare retain")
            storage = value.get("storage", "")
            if "storage" in value and (storage != "inline" or ownership != "unique"):
                raise ValueError(f"{location}: storage requires inline unique ownership")
            consumption = value.get("release-consumption", "")
            cleanup = value.get("cleanup-status", "")
            if storage and consumption == "success-or-indeterminate":
                raise ValueError(f"{location}: inline storage does not support indeterminate destruction")
            if "release-consumption" in value or "cleanup-status" in value:
                if ownership != "unique" or (consumption, cleanup) not in {
                    ("always", "discard"),
                    ("success-or-indeterminate", "abort"),
                }:
                    raise ValueError(
                        f"{location}: status release requires unique and matching release-consumption/cleanup-status: always/discard or success-or-indeterminate/abort"
                    )
            retain, release = value.get("retain", ""), value.get("release")
            for operation in (release,) if ownership == "unique" else (retain, release):
                if (
                    not isinstance(operation, str)
                    or operation not in symbols
                    or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", operation) is None
                ):
                    raise ValueError(f"{location}: retain/release must name selected functions")
                operations.add(operation)
            if retain == release:
                raise ValueError(f"{location}: lifetime operations must be distinct")
            query, tag = value.get("type-query", ""), value.get("type-tag", "")
            if "type-query" in value or "type-tag" in value:
                if ownership != "reference-counted" or query not in symbols or tag not in symbols or query == tag:
                    raise ValueError(
                        f"{location}: type-query/type-tag require distinct selected functions on a reference-counted resource"
                    )
            table = self._callback_table(value, symbols, location, ownership, storage) if "table" in value else None
            resources.append(
                NativeResourceBinding(
                    name, ownership, retain, release, consumption, cleanup, query, tag, storage, table=table
                )
            )
        if operations.intersection(values):
            raise ValueError(f"{context}: lifetime operations must be distinct from resource types")
        return tuple(resources)

    def _callback_table(self, value, symbols, location, ownership, storage):
        table = value["table"]
        location = f"{location}.table"
        if ownership != "unique" or storage or not isinstance(table, dict):
            raise ValueError(f"{location} requires a unique pointer resource and a table declaration")
        self._reject_unknown(
            table,
            frozenset(
                {
                    "name",
                    "interface",
                    "context",
                    "context-index",
                    "executor",
                    "failure",
                    "methods",
                    "label",
                    "reopen",
                    "release",
                }
            ),
            location,
        )
        for key in ("name", "interface", "context", "methods", "executor", "failure"):
            if key not in table:
                raise ValueError(f"{location} requires name, interface, context, methods, executor and failure")
        name = self._identifier(table["name"], f"{location}.name")
        interface = self._identifier(table["interface"], f"{location}.interface")
        context = self._identifier(table["context"], f"{location}.context")
        index = table.get("context-index", 0)
        if type(index) is not int or index < 0 or index > 999999999:
            raise ValueError(f"{location}.context-index must be a nonnegative native parameter index")
        if table["executor"] != "caller":
            raise ValueError(f"{location}.executor currently requires caller")
        if table["failure"] != "abort":
            raise ValueError(f"{location}.failure currently requires abort")
        methods = table["methods"]
        if not isinstance(methods, dict) or not methods:
            raise ValueError(f"{location}.methods must map BTRC method names to callback fields")
        projected = tuple(
            (self._identifier(method, f"{location}.methods"), self._identifier(field, f"{location}.methods.{method}"))
            for method, field in sorted(methods.items())
        )
        optional = {
            key: self._identifier(table[key], f"{location}.{key}") if key in table else ""
            for key in ("label", "reopen", "release")
        }
        fields = [context, *(field for _, field in projected), *(field for field in optional.values() if field)]
        if len(set(fields)) != len(fields):
            raise ValueError(f"{location}: context, method, label, reopen and release fields must be distinct")
        if optional["reopen"] and not optional["label"]:
            raise ValueError(f"{location}.reopen requires a label field to answer")
        if name in symbols or interface in symbols or name == interface:
            raise ValueError(f"{location}: name and interface must be distinct from selected symbols")
        if any(method in {"close", "isOpen"} for method, _ in projected):
            raise ValueError(f"{location}.methods cannot shadow resource operations")
        return NativeCallbackTable(name, interface, context, index, projected, **optional)

    def _initializer_bindings(self, values, binding, context):
        if not isinstance(values, dict):
            raise ValueError(f"{context}.initializers requires selected function tables")
        resources = {resource.name: resource for resource in binding.resources}
        results, owners, projections = set(), set(), []
        for function, value in sorted(values.items()):
            self._resource_functions([function], binding.symbols, context, "initializers")
            if binding.language == "c++":
                if not isinstance(value, dict) or set(value) != {
                    "resource",
                    "result",
                    "success",
                    "status-field",
                    "failure",
                }:
                    raise ValueError("C++ initializer requires resource, result, success, status-field and failure")
                resource, result, success = value["resource"], value["result"], value["success"]
                self._identifier(result, "C++ initializer result")
                self._identifier(value["status-field"], "C++ initializer status-field")
                if (
                    not isinstance(resource, str)
                    or resource not in resources
                    or resources[resource].ownership != "unique"
                    or not function.startswith(resource + "::")
                    or value["failure"] != "destroy"
                ):
                    raise ValueError("C++ initializer requires its unique SDK receiver and failure = destroy")
                if (
                    not isinstance(success, str)
                    or success not in binding.symbols
                    or resource in owners
                    or result in results
                    or result in binding.symbols
                    or result in {item.alias for item in resources.values()}
                ):
                    raise ValueError(
                        "C++ initializer requires one factory per owner, a distinct result and selected success constant"
                    )
                if function.removeprefix(resource + "::") in {
                    method.removesuffix("()") for method in resources[resource].methods
                }:
                    raise ValueError("C++ initialization cannot also expose an instance mutation method")
                projections.append(
                    NativeInitializerBinding(
                        function, resource, "", result, success, status_field=value["status-field"]
                    )
                )
                results.add(result)
                owners.add(resource)
                continue
            if not isinstance(value, dict) or set(value) - {"copied-inputs"} not in (
                {"resource", "parameter", "result", "success", "failure"},
                {"resource", "parameter", "result", "success-nonzero", "failure"},
            ):
                raise ValueError(f"{context}.initializers requires resource, parameter, result, success and failure")
            for field in ("resource", "parameter", "result"):
                self._identifier(value[field], f"{context}.initializers.{field}")
            resource, parameter, result = (value[field] for field in ("resource", "parameter", "result"))
            success = value.get("success", "")
            if "success" in value:
                self._identifier(success, f"{context}.initializers.success")
            elif value["success-nonzero"] is not True:
                raise ValueError("initializer success-nonzero requires true")
            if resource not in resources or resources[resource].storage != "inline" or binding.language != "c":
                raise ValueError("initializers requires a declared inline C resource")
            if value["failure"] != "rolled-back":
                raise ValueError("initializers requires fully rolled-back SDK failure")
            if (
                result in results
                or result in binding.symbols
                or resource in owners
                or (success and success not in binding.symbols)
            ):
                raise ValueError(
                    "initializers requires one initializer per resource, a distinct result and selected success constant"
                )
            if (
                function in {entry.split(".", 1)[0] for entry, _ in binding.owned_outputs}
                or function in binding.owned_results
            ):
                raise ValueError("initializers cannot combine other owned outputs/results")
            copies = value.get("copied-inputs", {})
            if not isinstance(copies, dict) or len(copies) > 1:
                raise ValueError("initializers currently supports at most one immutable copied input")
            copied_input, length = "", ""
            for copied_input, copy in copies.items():
                self._identifier(copied_input, "initializer copied input")
                if not isinstance(copy, dict) or set(copy) != {"length"}:
                    raise ValueError("initializer copied-inputs requires only length")
                length = copy["length"]
                self._identifier(length, "initializer copied input length")
                if len({parameter, copied_input, length}) != 3:
                    raise ValueError("initializer storage, copied input and length must be distinct")
            results.add(result)
            owners.add(resource)
            projections.append(
                NativeInitializerBinding(function, resource, parameter, result, success, copied_input, length)
            )
        if binding.language == "c++":
            if {resource.name for resource in resources.values() if resource.ownership == "unique"} != owners:
                raise ValueError("every C++ unique resource requires one checked initialization factory")
        elif {resource.name for resource in resources.values() if resource.storage} != owners:
            raise ValueError("every inline resource requires one checked initializer")
        return tuple(projections)

    def _copied_input_bindings(self, values, binding, context):
        if not isinstance(values, dict):
            raise ValueError("copied-inputs requires selected function.parameter tables")
        owners, copies = set(), []
        for parameter, shape in sorted(values.items()):
            self._resource_functions([parameter], binding.symbols, context, "copied-inputs", parameters=True)
            if (
                not isinstance(shape, dict)
                or set(shape) != {"owner", "length", "assignment"}
                or shape["assignment"] != "once"
            ):
                raise ValueError("copied-inputs requires owner, length and assignment = once")
            owner, length = shape["owner"], shape["length"]
            self._identifier(owner, "copied-inputs owner")
            self._identifier(length, "copied-inputs length")
            function, input_name = parameter.split(".", 1)
            if (
                len({owner, length, input_name}) != 3
                or f"{function}.{owner}" not in binding.borrowed_parameters
                or parameter not in binding.read_only_borrows
            ):
                raise ValueError(
                    "copied-inputs requires distinct declared resource-owner and read-only byte parameters"
                )
            if function in owners:
                raise ValueError("copied-inputs requires one copied span per SDK setter")
            owners.add(function)
            copies.append((parameter, owner, length))
        return tuple(copies)

    def _resource_functions(self, values, symbols, context, field, *, parameters=False) -> tuple[str, ...]:
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"{context}.{field} must be an array of selected names")
        for value in values:
            parts = value.split(".")
            if (
                len(parts) != (2 if parameters else 1)
                or parts[0] not in symbols
                or (parameters and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", parts[1]) is None)
            ):
                raise ValueError(
                    f"{context}.{field} must name selected {'function.parameter pairs' if parameters else 'functions'}"
                )
        if len(set(values)) != len(values):
            raise ValueError(f"{context}.{field} contains a duplicate value")
        return tuple(sorted(values))

    def _owned_output_bindings(self, values, symbols, context):
        if not isinstance(values, dict):
            raise ValueError(f"{context}.owned-outputs must map function.parameter names to result classes")
        outputs = []
        functions = set()
        results = set()
        for parameter, value in sorted(values.items()):
            self._resource_functions([parameter], symbols, context, "owned-outputs", parameters=True)
            if not isinstance(value, dict) or set(value) not in ({"result"}, {"result", "resource", "size", "name"}):
                raise ValueError(f"{context}.owned-outputs requires only a result class; adoption is unconditional")
            result = value["result"]
            self._identifier(result, f"{context}.owned-outputs result")
            function = parameter.split(".", 1)[0]
            if function in functions or result in results or result in symbols:
                raise ValueError(
                    f"{context}.owned-outputs requires one output per function and distinct result classes"
                )
            functions.add(function)
            results.add(result)
            outputs.append((parameter, result))
        return tuple(outputs)

    def _owned_output_resource_bindings(self, values, binding, context):
        projections = []
        aliases = set()
        resources = {resource.name: resource for resource in binding.resources}
        output_names = dict(binding.owned_outputs)
        for parameter, value in sorted(values.items()):
            if "resource" not in value:
                continue
            for field in ("resource", "size", "name"):
                self._identifier(value[field], f"{context}.owned-outputs.{parameter}.{field}")
            resource, size, alias = value["resource"], value["size"], value["name"]
            if resource not in resources or resources[resource].ownership != "reference-counted":
                raise ValueError("erased owned-outputs requires a declared reference-counted resource")
            if (
                alias in binding.symbols
                or alias in aliases
                or alias in output_names.values()
                or size == parameter.split(".", 1)[1]
            ):
                raise ValueError("erased owned-outputs requires distinct alias, result and output parameters")
            if any(offset[0].split(".", 1)[0] == parameter.split(".", 1)[0] for offset in binding.output_offsets):
                raise ValueError("erased owned-outputs cannot combine output-offsets")
            aliases.add(alias)
            projections.append((parameter, NativeResourceOutputBinding(resource, size, alias)))
        return tuple(projections)

    def _copied_result_bindings(self, values, symbols, context):
        if not isinstance(values, dict):
            raise ValueError(f"{context}.copied-results requires function mappings")
        results = []
        for function, value in sorted(values.items()):
            self._resource_functions([function], symbols, context, "copied-results")
            if not isinstance(value, dict) or value.get("kind") not in {"string", "bytes"}:
                raise ValueError(f"{context}.copied-results kind requires string or bytes")
            kind = value["kind"]
            owner = value.get("owner", "")
            if owner:
                self._identifier(owner, f"{context}.copied-results owner")
            if kind == "string":
                if (set(value) != {"kind", "owner"} or not owner) and (
                    set(value) != {"kind", "lifetime"} or value.get("lifetime") != "static"
                ):
                    raise ValueError(f"{context}.copied-results string requires an owner or explicit static lifetime")
                results.append((function, kind, owner, "", ()))
                continue
            if (
                set(value) != {"kind", "owner", "length-function", "length-arguments", "length-preserves-result"}
                or not owner
                or value.get("length-preserves-result") is not True
            ):
                raise ValueError(f"{context}.copied-results bytes requires owner and length-preserves-result = true")
            length_function = value["length-function"]
            self._resource_functions([length_function], symbols, context, "copied-results length-function")
            arguments = value["length-arguments"]
            if not isinstance(arguments, list) or not arguments:
                raise ValueError(f"{context}.copied-results length-arguments requires parameter names")
            for argument in arguments:
                self._identifier(argument, f"{context}.copied-results length argument")
            results.append((function, kind, owner, length_function, tuple(arguments)))
        return tuple(results)

    def _output_offset_bindings(self, values, symbols, outputs, context):
        if not isinstance(values, dict):
            raise ValueError(f"{context}.output-offsets must map function.parameter paths to bounded offsets")
        offsets = []
        functions = set()
        owners = {parameter.split(".", 1)[0] for parameter, _ in outputs}
        for parameter, value in sorted(values.items()):
            self._resource_functions([parameter], symbols, context, "output-offsets", parameters=True)
            if not isinstance(value, dict) or set(value) != {"input", "length", "field"}:
                raise ValueError(f"{context}.output-offsets requires input, length, and field")
            for key in ("input", "length", "field"):
                self._identifier(value[key], f"{context}.output-offsets {key}")
            function, output = parameter.split(".", 1)
            if function not in owners or function in functions:
                raise ValueError(f"{context}.output-offsets requires one offset alongside an owned output")
            if len({output, value["input"], value["length"]}) != 3 or value["field"] in {"status", "value"}:
                raise ValueError(f"{context}.output-offsets requires distinct parameters and a fresh result field")
            functions.add(function)
            offsets.append((parameter, value["input"], value["length"], value["field"]))
        return tuple(offsets)

    def _variadic_bindings(self, values, symbols, context, language):
        if not isinstance(values, dict) or (values and language != "c"):
            raise ValueError(f"{context}.variadic-calls requires selected C call shapes")
        calls = []
        functions = set()
        promoted = {"int", "unsigned int", "long", "unsigned long", "long long", "unsigned long long", "double"}
        pointees = promoted | {"char", "signed char", "unsigned char", "short", "unsigned short", "float"}
        for parameter, value in sorted(values.items()):
            self._resource_functions([parameter], symbols, context, "variadic-calls", parameters=True)
            if not isinstance(value, dict) or set(value) != {"value", "arguments"}:
                raise ValueError(f"{context}.variadic-calls requires value and arguments")
            constant = value["value"]
            arguments = value["arguments"]
            if not isinstance(constant, str) or constant not in symbols:
                raise ValueError(f"{context}.variadic-calls value must name a selected SDK constant")
            if (
                not isinstance(arguments, list)
                or not arguments
                or any(not isinstance(argument, str) for argument in arguments)
            ):
                raise ValueError(f"{context}.variadic-calls arguments must be a nonempty native scalar type list")
            for argument in arguments:
                pointee = argument[:-1].removeprefix("const ") if argument.endswith("*") else ""
                if argument not in promoted and pointee not in pointees:
                    raise ValueError(f"{context}.variadic-calls requires promoted scalars or scalar pointers")
            function = parameter.split(".", 1)[0]
            if function in functions:
                raise ValueError(f"{context}.variadic-calls selects exactly one shape per function")
            functions.add(function)
            calls.append(NativeVariadicBinding(parameter, constant, tuple(arguments)))
        return tuple(calls)

    def _record_snapshot_bindings(self, values, binding, context):
        if not isinstance(values, dict):
            raise ValueError(f"{context}.record-snapshots must be a table")
        if values and binding.language != "c":
            raise ValueError(f"{context}.record-snapshots requires C")
        resources = {resource.name for resource in binding.resources}
        names = set(binding.symbols)
        snapshots = []
        for result, value in sorted(values.items()):
            if not _IDENTIFIER.fullmatch(result) or result in names or not isinstance(value, dict):
                raise ValueError(f"{context}.record-snapshots requires distinct result class names")
            if not {"owner", "name", "fields"} <= value.keys() or value.keys() - {
                "owner",
                "name",
                "fields",
                "byte-plane",
                "guard",
                "strings",
                "byte-span",
            }:
                raise ValueError(f"{context}.record-snapshots requires owner, name, fields and optional byte-plane")
            owner, name, fields = value["owner"], value["name"], value["fields"]
            if (
                not isinstance(owner, str)
                or owner not in resources
                or not isinstance(name, str)
                or not _IDENTIFIER.fullmatch(name)
                or name in names
                or name == result
            ):
                raise ValueError(f"{context}.record-snapshots requires a selected resource and distinct function name")
            if not isinstance(fields, dict) or any(
                not _IDENTIFIER.fullmatch(alias) or not isinstance(path, str) or not _MODULE_NAME.fullmatch(path)
                for alias, path in fields.items()
            ):
                raise ValueError(f"{context}.record-snapshots fields must map aliases to dotted SDK field paths")
            plane = value.get("byte-plane", {})
            if not isinstance(plane, dict) or (
                "byte-plane" in value and set(plane) != {"field", "pointer", "width", "rows", "pitch"}
            ):
                raise ValueError(
                    f"{context}.record-snapshots byte-plane requires field, pointer, width, rows and pitch"
                )
            if plane and (
                any(not isinstance(item, str) for item in plane.values())
                or not _IDENTIFIER.fullmatch(plane["field"])
                or plane["field"] in fields
                or any(not _MODULE_NAME.fullmatch(plane[key]) for key in ("pointer", "width", "rows", "pitch"))
            ):
                raise ValueError(
                    f"{context}.record-snapshots byte-plane requires a distinct field and dotted SDK paths"
                )
            guard = value.get("guard", {})
            if not isinstance(guard, dict) or ("guard" in value and set(guard) != {"field", "equals"}):
                raise ValueError(f"{context}.record-snapshots guard requires field and equals")
            if guard and (
                not isinstance(guard["field"], str)
                or not _MODULE_NAME.fullmatch(guard["field"])
                or guard["equals"] not in binding.symbols
            ):
                raise ValueError(f"{context}.record-snapshots guard requires an SDK path and selected constant")
            strings = value.get("strings", {})
            if not isinstance(strings, dict) or any(
                not _IDENTIFIER.fullmatch(alias)
                or alias in fields
                or not isinstance(path, str)
                or not _MODULE_NAME.fullmatch(path)
                for alias, path in strings.items()
            ):
                raise ValueError(f"{context}.record-snapshots strings requires distinct aliases and SDK paths")
            span = value.get("byte-span", {})
            if not isinstance(span, dict) or ("byte-span" in value and set(span) != {"field", "pointer", "length"}):
                raise ValueError(f"{context}.record-snapshots byte-span requires field, pointer and length")
            if span and (
                plane
                or any(not isinstance(item, str) for item in span.values())
                or not _IDENTIFIER.fullmatch(span["field"])
                or span["field"] in fields
                or span["field"] in strings
                or any(not _MODULE_NAME.fullmatch(span[key]) for key in ("pointer", "length"))
            ):
                raise ValueError(
                    f"{context}.record-snapshots byte-span requires a distinct byte field and cannot combine byte-plane"
                )
            if plane and plane["field"] in strings:
                raise ValueError(f"{context}.record-snapshots requires distinct copied fields")
            if not fields and not plane and not strings and not span:
                raise ValueError(f"{context}.record-snapshots requires copied fields")
            names.update((name, result))
            snapshots.append(
                NativeRecordSnapshotBinding(
                    result,
                    owner,
                    name,
                    tuple(sorted(fields.items())),
                    tuple(plane[key] for key in ("field", "pointer", "width", "rows", "pitch")) if plane else (),
                    tuple(guard[key] for key in ("field", "equals")) if guard else (),
                    tuple(sorted(strings.items())),
                    tuple(span[key] for key in ("field", "pointer", "length")) if span else (),
                )
            )
        return tuple(snapshots)

    def bindings(self, manifest: Mapping, root: str, package: str, path: str) -> tuple[NativeBinding, ...]:
        entries = manifest.get("native", {}).get("bindings", [])
        if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
            raise ValueError(f"package manifest {path!r} native.bindings must be an array of tables")
        bindings: list[NativeBinding] = []
        for index, entry in enumerate(entries):
            context = f"package manifest {path!r} native.bindings[{index}]"
            self._reject_unknown(
                entry,
                frozenset(
                    {
                        "module",
                        "header",
                        "symbols",
                        "language",
                        "standard",
                        "os",
                        "arch",
                        "read-only-borrows",
                        "realtime-safe",
                        "owned-records",
                        "record-snapshots",
                        "record-inputs",
                        "object-fields",
                        "resources",
                        "owned-results",
                        "owned-outputs",
                        "variadic-calls",
                        "output-offsets",
                        "copied-results",
                        "initializers",
                        "copied-inputs",
                        "borrowed-results",
                        "borrowed-parameters",
                        "callbacks",
                        "main-thread-globals",
                        "static-globals",
                        "resource-parameters",
                        "resource-results",
                        "string-views",
                        "record-outputs",
                        "owned-output-fields",
                        "null-output-fields",
                    }
                ),
                context,
            )
            module = entry.get("module")
            if not isinstance(module, str) or _MODULE_NAME.fullmatch(module) is None:
                raise ValueError(f"{context}.module must be a dotted module name")
            (module_path,) = self._module_paths(root, {"modules": [module]}, context)
            header = self._inside_path(root, entry.get("header"), f"{context}.header", directory=False)
            symbols = entry.get("symbols")
            if (
                not isinstance(symbols, list)
                or not symbols
                or not all(
                    isinstance(symbol, str)
                    and (
                        _NATIVE_SYMBOL.fullmatch(symbol)
                        or (
                            entry.get("language") in ("objective-c", "objective-c++")
                            and _OBJECTIVE_C_SYMBOL.fullmatch(symbol)
                        )
                    )
                    for symbol in symbols
                )
            ):
                raise ValueError(f"{context}.symbols must be a non-empty array of qualified native names")
            if len(set(symbols)) != len(symbols):
                raise ValueError(f"{context}.symbols contains a duplicate value")
            language = entry.get("language")
            standard = entry.get("standard")
            if not isinstance(language, str) or language not in _SOURCE_STANDARDS:
                raise ValueError(f"{context}.language is unsupported")
            if not isinstance(standard, str) or standard not in _SOURCE_STANDARDS[language]:
                raise ValueError(f"{context}.standard is unsupported for {language}")
            borrows = entry.get("read-only-borrows", [])
            if not isinstance(borrows, list) or not all(
                isinstance(value, str)
                and value.count(".") == 1
                and value.rsplit(".", 1)[0] in symbols
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value.rsplit(".", 1)[1])
                for value in borrows
            ):
                raise ValueError(f"{context}.read-only-borrows must be an array of selected function.parameter pairs")
            if len(set(borrows)) != len(borrows):
                raise ValueError(f"{context}.read-only-borrows contains a duplicate value")
            realtime = entry.get("realtime-safe", [])
            if not isinstance(realtime, list) or not all(
                isinstance(value, str) and value in symbols for value in realtime
            ):
                raise ValueError(f"{context}.realtime-safe must be an array of selected function names")
            if len(set(realtime)) != len(realtime):
                raise ValueError(f"{context}.realtime-safe contains a duplicate value")
            records = entry.get("owned-records", [])
            if (
                not isinstance(records, list)
                or not all(
                    isinstance(value, str)
                    and value in symbols
                    and (
                        bool(_NATIVE_SYMBOL.fullmatch(value))
                        if language == "c++"
                        else bool(_IDENTIFIER.fullmatch(value))
                    )
                    for value in records
                )
                or len(set(records)) != len(records)
            ):
                raise ValueError(f"{context}.owned-records must name distinct selected records")
            inputs = entry.get("record-inputs", [])
            if (
                not isinstance(inputs, list)
                or not all(
                    isinstance(value, str)
                    and value.count(".") == 1
                    and value.split(".")[0] in symbols
                    and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value.split(".")[1])
                    for value in inputs
                )
                or len(set(inputs)) != len(inputs)
            ):
                raise ValueError(f"{context}.record-inputs must name distinct selected function.parameter pairs")
            object_fields = entry.get("object-fields", {})
            if not isinstance(object_fields, dict) or not all(
                isinstance(key, str)
                and key.count(".") == 1
                and key.split(".")[0] in records
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.split(".")[1])
                and isinstance(value, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\??", value)
                for key, value in object_fields.items()
            ):
                raise ValueError(f"{context}.object-fields must map selected record.field names to object types")
            if (records and language not in {"c", "c++"}) or ((inputs or object_fields) and language != "c"):
                raise ValueError(f"{context}: record input projections currently require a C binding")
            resources = self._resource_bindings(entry.get("resources", {}), symbols, context, language)
            owned_results = self._resource_functions(entry.get("owned-results", []), symbols, context, "owned-results")
            borrowed_parameters = self._resource_functions(
                entry.get("borrowed-parameters", []), symbols, context, "borrowed-parameters", parameters=True
            )
            borrowed_results = entry.get("borrowed-results", {})
            if not isinstance(borrowed_results, dict) or not all(
                isinstance(function, str)
                and function in symbols
                and isinstance(owner, str)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", owner)
                and f"{function}.{owner}" in borrowed_parameters
                for function, owner in borrowed_results.items()
            ):
                raise ValueError(
                    f"{context}.borrowed-results must map selected functions to declared borrowed owner parameters"
                )
            if set(borrowed_results) & set(owned_results):
                raise ValueError(f"{context}: owned-results and borrowed-results must be distinct")
            resource_projections = []
            for field, parameters in (("resource-parameters", True), ("resource-results", False)):
                mappings = entry.get(field, {})
                if not isinstance(mappings, dict) or any(
                    not isinstance(value, str) or value not in {resource.name for resource in resources}
                    for value in mappings.values()
                ):
                    raise ValueError(f"{context}.{field} must map selected native positions to declared resources")
                self._resource_functions(list(mappings), symbols, context, field, parameters=parameters)
                resource_projections.append(tuple(sorted(mappings.items())))
            callbacks = self._callback_bindings(entry.get("callbacks", {}), symbols, context, language)
            outputs = self._resource_functions(
                entry.get("record-outputs", []), symbols, context, "record-outputs", parameters=True
            )
            if outputs and language != "c":
                raise ValueError("record-outputs currently requires C")
            if set(outputs) & set(inputs):
                raise ValueError("record input/output parameters must be distinct")
            output_fields = []
            for field in ("owned-output-fields", "null-output-fields"):
                values = entry.get(field, [])
                if (
                    not isinstance(values, list)
                    or any(
                        not isinstance(value, str)
                        or value.count(".") != 2
                        or value.rsplit(".", 1)[0] not in outputs
                        or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value.rsplit(".", 1)[1]) is None
                        for value in values
                    )
                    or len(set(values)) != len(values)
                ):
                    raise ValueError(f"{context}.{field} requires distinct declared function.parameter.field names")
                output_fields.append(tuple(sorted(values)))
            if set(output_fields[0]) & set(output_fields[1]):
                raise ValueError("owned/null output fields must be distinct")
            if callbacks and language not in {"c", "objective-c"}:
                raise ValueError(f"{context}: callback mappings currently require C or Objective-C")
            if resources or owned_results or borrowed_parameters or borrowed_results:
                if language not in {"c", "c++"}:
                    raise ValueError(f"{context}: resource bindings require C or C++")
                if language == "c++" and (owned_results or borrowed_parameters or borrowed_results):
                    raise ValueError(f"{context}: C++ resource methods carry ownership through their receiver")
                if not resources:
                    raise ValueError(f"{context}: resource ownership requires declared resources")
                operations = {operation for resource in resources for operation in (resource.retain, resource.release)}
                if operations.intersection(owned_results) or any(
                    value.split(".")[0] in operations for value in borrowed_parameters
                ):
                    raise ValueError(f"{context}: resource lifetime operations are reserved")
            main_thread_globals = entry.get("main-thread-globals", [])
            if (
                not isinstance(main_thread_globals, list)
                or any(not isinstance(name, str) or name not in symbols for name in main_thread_globals)
                or len(set(main_thread_globals)) != len(main_thread_globals)
                or (main_thread_globals and language != "objective-c")
            ):
                raise ValueError(
                    f"{context}.main-thread-globals must name distinct selected Objective-C object globals"
                )
            binding = NativeBinding(
                package,
                module_path,
                header,
                language,
                standard,
                tuple(sorted(symbols)),
                self._target_values(entry, "os", _TARGET_OPERATING_SYSTEMS, context),
                self._target_values(entry, "arch", _TARGET_ARCHITECTURES, context),
                tuple(sorted(borrows)),
                tuple(sorted(realtime)),
                tuple(sorted(records)),
                tuple(sorted(inputs)),
                tuple(sorted(object_fields.items())),
                resources,
                owned_results,
                borrowed_parameters,
                callbacks,
                tuple(sorted(main_thread_globals)),
                self._string_view_bindings(entry.get("string-views", {}), symbols, context, language),
                outputs,
                *output_fields,
                tuple(sorted(borrowed_results.items())),
                self._resource_functions(entry.get("static-globals", []), symbols, context, "static-globals"),
                *resource_projections,
                self._owned_output_bindings(entry.get("owned-outputs", {}), symbols, context),
            )
            if binding.owned_outputs and (language != "c" or not resources):
                raise ValueError(f"{context}: owned-outputs requires declared C resources")
            binding = replace(
                binding,
                variadic_calls=self._variadic_bindings(entry.get("variadic-calls", {}), symbols, context, language),
            )
            binding = replace(
                binding,
                output_offsets=self._output_offset_bindings(
                    entry.get("output-offsets", {}), symbols, binding.owned_outputs, context
                ),
                copied_results=self._copied_result_bindings(
                    entry.get("copied-results", {}),
                    symbols
                    + [
                        f"{resource.name}::{method.removesuffix('()')}"
                        for resource in resources
                        if language == "c++"
                        for method in resource.methods
                    ],
                    context,
                ),
            )
            if binding.copied_results and language not in {"c", "c++"}:
                raise ValueError(f"{context}: copied-results requires C functions or C++ methods")
            if language == "c++" and any(
                kind != "string"
                or owner != "self"
                or function
                not in {
                    f"{resource.name}::{method.removesuffix('()')}"
                    for resource in resources
                    for method in resource.methods
                }
                for function, kind, owner, _, _ in binding.copied_results
            ):
                raise ValueError("C++ copied-results requires selected instance strings with owner = self")
            binding = replace(
                binding,
                owned_output_resources=self._owned_output_resource_bindings(
                    entry.get("owned-outputs", {}), binding, context
                ),
            )
            binding = replace(
                binding,
                record_snapshots=self._record_snapshot_bindings(entry.get("record-snapshots", {}), binding, context),
            )
            binding = replace(
                binding, initializers=self._initializer_bindings(entry.get("initializers", {}), binding, context)
            )
            binding = replace(
                binding, copied_inputs=self._copied_input_bindings(entry.get("copied-inputs", {}), binding, context)
            )
            if binding.static_globals and (language != "c" or not resources):
                raise ValueError(f"{context}: static-globals requires declared C resources")
            if any(binding.overlaps(previous) for previous in bindings):
                raise ValueError(f"{context} overlaps a native binding for the same module and target")
            bindings.append(binding)
        return tuple(
            sorted(
                bindings,
                key=lambda binding: (
                    binding.module,
                    binding.header,
                    binding.symbols,
                    binding.operating_systems,
                    binding.architectures,
                ),
            )
        )


class PackageUniverse:
    """Own manifest discovery, lockfile policy, and dependency materialization."""

    def __init__(
        self,
        git_dependencies: GitDependencyCache | None = None,
        *,
        manifest_reader: PackageManifestReader | None = None,
        file_store: PackageFileStore | None = None,
        manifest_validator: PackageManifestValidator | None = None,
    ) -> None:
        owned_store = file_store
        if owned_store is None and git_dependencies is not None:
            owned_store = git_dependencies.file_store
        if owned_store is None and manifest_reader is not None:
            owned_store = manifest_reader.file_store
        self.file_store = owned_store or PackageFileStore()
        if git_dependencies is not None and git_dependencies.file_store is not self.file_store:
            raise ValueError("PackageUniverse and Git cache must share one file store")
        if manifest_reader is not None and manifest_reader.file_store is not self.file_store:
            raise ValueError("PackageUniverse and manifest reader must share one file store")
        self.git_dependencies = git_dependencies or GitDependencyCache(file_store=self.file_store)
        self.manifest_reader = manifest_reader or PackageManifestReader(file_store=self.file_store)
        self.manifest_validator = manifest_validator or PackageManifestValidator()

    @staticmethod
    def find_manifest(start_directory: str) -> str | None:
        """Walk upward from a directory to the nearest ``btrc.toml``."""

        directory = os.path.abspath(start_directory)
        while True:
            candidate = os.path.join(directory, "btrc.toml")
            if os.path.exists(candidate):
                return candidate
            parent = os.path.dirname(directory)
            if parent == directory:
                return None
            directory = parent

    def resolve_for(
        self,
        input_path: str,
        *,
        refresh: bool = False,
        target: str | PackageTarget | None = None,
    ) -> ResolvedPackages:
        """Resolve the dependencies governing one input file."""

        selected_target = PackageTarget.coerce(target)
        manifest = self.find_manifest(os.path.dirname(os.path.abspath(input_path)))
        if manifest is None:
            return ResolvedPackages.empty(selected_target)
        try:
            return self.resolve_manifest(manifest, refresh=refresh, target=target)
        except (subprocess.SubprocessError, ValueError, OSError) as error:
            detail = (getattr(error, "stderr", None) or "").strip()
            message = f"package resolution failed: {error}"
            if detail:
                message = f"{message}\n  {detail}"
            raise IncludeResolutionError(message) from error

    def resolve_manifest(
        self,
        manifest_path: str,
        *,
        refresh: bool = False,
        target: str | PackageTarget | None = None,
    ) -> ResolvedPackages:
        """Resolve one manifest, using its lock when current."""

        manifest_path = os.path.abspath(manifest_path)
        manifest_directory = os.path.dirname(manifest_path)
        lock_path = os.path.join(manifest_directory, "btrc.lock")
        manifest = self.manifest_reader.read(manifest_path)
        selected_target = PackageTarget.coerce(target)
        if "manifest-version" in manifest:
            return self._resolve_version_one(
                manifest_path,
                manifest,
                selected_target,
                refresh=refresh,
            )
        dependencies = manifest.get("dependencies", {})
        if not isinstance(dependencies, dict):
            raise ValueError("manifest 'dependencies' must be a table")
        dependencies_hash = self.dependencies_hash(dependencies)

        if not refresh and os.path.exists(lock_path):
            locked = self._load_lock(
                lock_path,
                dependencies_hash,
                manifest_directory,
            )
            if locked is not None:
                return ResolvedPackages(manifest_path, locked, native_plan=NativeLinkPlan.empty(selected_target))

        resolved = {
            name: self._resolve_dependency(
                name,
                specification,
                manifest_directory,
                refresh=refresh,
            )
            for name, specification in dependencies.items()
        }
        self._write_lock(
            lock_path,
            dependencies_hash,
            resolved,
            manifest_directory,
        )
        return ResolvedPackages(manifest_path, resolved, native_plan=NativeLinkPlan.empty(selected_target))

    def _strict_lock(self, path: str) -> dict | None:
        if not os.path.exists(path):
            return None
        lock = self.file_store.read_json(path)
        if not isinstance(lock, dict):
            raise LockfileError(f"cannot parse strict package lock {path!r} as UTF-8 JSON")
        schema = lock.get("schema")
        if schema in (1, LOCK_SCHEMA):
            return None
        if schema != PACKAGE_GRAPH_LOCK_SCHEMA:
            raise LockfileVersionError(
                f"unsupported btrc.lock schema {schema!r} in {path!r} "
                f"(this compiler supports schema {PACKAGE_GRAPH_LOCK_SCHEMA} for version-1 manifests)"
            )
        if set(lock) != {"manifest-hash", "packages", "root", "schema"}:
            raise LockfileError(f"invalid schema-{PACKAGE_GRAPH_LOCK_SCHEMA} lockfile {path!r}: unexpected fields")
        if (
            not isinstance(lock["manifest-hash"], str)
            or _SHA256.fullmatch(lock["manifest-hash"]) is None
            or not isinstance(lock["root"], str)
            or _IDENTIFIER.fullmatch(lock["root"]) is None
            or not isinstance(lock["packages"], list)
        ):
            raise LockfileError(f"invalid schema-{PACKAGE_GRAPH_LOCK_SCHEMA} lockfile {path!r}")
        names: set[str] = set()
        dependency_targets: list[str] = []
        for entry in lock["packages"]:
            if not isinstance(entry, dict) or set(entry) != {
                "dependencies",
                "manifest-hash",
                "name",
                "source",
            }:
                raise LockfileError(f"invalid schema-{PACKAGE_GRAPH_LOCK_SCHEMA} package in {path!r}")
            if (
                not isinstance(entry["name"], str)
                or not isinstance(entry["manifest-hash"], str)
                or not isinstance(entry["dependencies"], dict)
                or not isinstance(entry["source"], dict)
            ):
                raise LockfileError(f"invalid schema-{PACKAGE_GRAPH_LOCK_SCHEMA} package in {path!r}")
            name = entry["name"]
            dependencies = entry["dependencies"]
            source = entry["source"]
            valid_dependencies = all(
                isinstance(alias, str)
                and _IDENTIFIER.fullmatch(alias) is not None
                and isinstance(target, str)
                and _IDENTIFIER.fullmatch(target) is not None
                for alias, target in dependencies.items()
            )
            valid_path_source = (
                set(source) == {"path"}
                and isinstance(source["path"], str)
                and bool(source["path"])
                and not os.path.isabs(source["path"])
            )
            valid_git_source = (
                set(source) == {"commit", "git", "rev"}
                and isinstance(source["commit"], str)
                and _GIT_COMMIT.fullmatch(source["commit"]) is not None
                and isinstance(source["git"], str)
                and bool(source["git"])
                and isinstance(source["rev"], str)
                and bool(source["rev"])
                and not source["rev"].startswith("-")
            )
            if (
                _IDENTIFIER.fullmatch(name) is None
                or name in names
                or _SHA256.fullmatch(entry["manifest-hash"]) is None
                or not valid_dependencies
                or not (valid_path_source or valid_git_source)
            ):
                raise LockfileError(f"invalid schema-{PACKAGE_GRAPH_LOCK_SCHEMA} package in {path!r}")
            names.add(name)
            dependency_targets.extend(dependencies.values())
        if lock["root"] not in names or any(target not in names for target in dependency_targets):
            raise LockfileError(f"invalid schema-{PACKAGE_GRAPH_LOCK_SCHEMA} package graph in {path!r}")
        return lock

    @staticmethod
    def _pinned_commits(lock: dict | None) -> dict[tuple[str, str], str]:
        pinned = {}
        for package in () if lock is None else lock["packages"]:
            source = package["source"]
            if set(source) == {"commit", "git", "rev"}:
                pinned[(source["git"], source["rev"])] = source["commit"]
        return pinned

    def _strict_dependency_source(
        self,
        alias: str,
        specification: Mapping,
        manifest_directory: str,
        pinned: Mapping[tuple[str, str], str],
        *,
        refresh: bool,
    ) -> tuple[str, dict[str, str]]:
        if "path" in specification:
            root = os.path.realpath(os.path.join(manifest_directory, specification["path"]))
            if not os.path.isdir(root):
                raise ValueError(f"path dependency {alias!r} does not name a directory: {specification['path']!r}")
            return root, {"path": root}
        revision = next(
            (specification[field] for field in ("rev", "tag", "branch") if field in specification),
            "HEAD",
        )
        pinned_commit = None if refresh else pinned.get((specification["git"], revision))
        root = self.git_dependencies.resolve(
            alias,
            specification["git"],
            revision,
            refresh=refresh,
            pinned_commit=pinned_commit,
        )
        return os.path.realpath(root), {
            "commit": self.git_dependencies.resolved_commit(root),
            "git": specification["git"],
            "rev": revision,
        }

    def _resolve_strict_node(
        self,
        root: str,
        source: Mapping[str, str],
        nodes_by_root: dict[str, PackageNode],
        roots_by_name: dict[str, str],
        visiting: list[str],
        pinned: Mapping[tuple[str, str], str],
        *,
        refresh: bool,
    ) -> str:
        root = os.path.realpath(root)
        if root in nodes_by_root:
            return nodes_by_root[root].name
        if root in visiting:
            start = visiting.index(root)
            cycle_roots = visiting[start:] + [root]
            cycle = " -> ".join(os.path.basename(path) or path for path in cycle_roots)
            raise ValueError(f"package dependency cycle: {cycle}")
        manifest_path = os.path.join(root, "btrc.toml")
        if not os.path.isfile(manifest_path):
            raise ValueError(f"package dependency root {root!r} is missing btrc.toml")
        manifest, manifest_bytes = self.manifest_reader.read_document(manifest_path)
        name = self.manifest_validator.validate_identity(manifest, manifest_path)
        previous_root = roots_by_name.get(name)
        if previous_root is not None and previous_root != root:
            raise ValueError(f"package name {name!r} resolves to both {previous_root!r} and {root!r}")
        roots_by_name[name] = root
        visiting.append(root)
        aliases = {}
        for alias, specification in sorted(self.manifest_validator.dependencies(manifest, manifest_path).items()):
            dependency_root, dependency_source = self._strict_dependency_source(
                alias,
                specification,
                root,
                pinned,
                refresh=refresh,
            )
            aliases[alias] = self._resolve_strict_node(
                dependency_root,
                dependency_source,
                nodes_by_root,
                roots_by_name,
                visiting,
                pinned,
                refresh=refresh,
            )
        visiting.pop()
        manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
        node = PackageNode(
            name=name,
            root=root,
            dependencies=aliases,
            source=source,
            manifest_hash=manifest_hash,
            native=self.manifest_validator.native(manifest, root, name, manifest_path),
            bindings=self.manifest_validator.bindings(manifest, root, name, manifest_path),
        )
        nodes_by_root[root] = node
        return name

    @staticmethod
    def _strict_lock_payload(
        root: str,
        root_package: str,
        nodes: Mapping[str, PackageNode],
    ) -> dict:
        packages = []
        for package in sorted(nodes.values(), key=lambda item: item.name):
            source = dict(package.source)
            if "path" in source:
                source["path"] = os.path.relpath(source["path"], root)
            packages.append(
                {
                    "dependencies": dict(sorted(package.dependencies.items())),
                    "manifest-hash": package.manifest_hash,
                    "name": package.name,
                    "source": source,
                }
            )
        graph_hash = hashlib.sha256(
            json.dumps(packages, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "manifest-hash": graph_hash,
            "packages": packages,
            "root": root_package,
            "schema": PACKAGE_GRAPH_LOCK_SCHEMA,
        }

    def _resolve_version_one(
        self,
        manifest_path: str,
        manifest: Mapping,
        target: PackageTarget,
        *,
        refresh: bool,
    ) -> ResolvedPackages:
        root = os.path.realpath(os.path.dirname(manifest_path))
        lock_path = os.path.join(root, "btrc.lock")
        lock = self._strict_lock(lock_path)
        nodes_by_root: dict[str, PackageNode] = {}
        root_package = self._resolve_strict_node(
            root,
            {"path": root},
            nodes_by_root,
            {},
            [],
            self._pinned_commits(lock),
            refresh=refresh,
        )
        nodes = {node.name: node for node in nodes_by_root.values()}
        payload = self._strict_lock_payload(root, root_package, nodes)
        if lock != payload:
            self.file_store.write_json(lock_path, payload, file_mode=0o644)
        root_node = nodes[root_package]
        entries = {alias: {"path": nodes[package].root} for alias, package in root_node.dependencies.items()}
        declarations = tuple(
            declaration
            for package in sorted(nodes.values(), key=lambda item: item.name)
            for declaration in package.native
        )
        return ResolvedPackages(
            manifest_path,
            entries,
            nodes=nodes,
            root_package=root_package,
            native_plan=NativeLinkPlan(target, tuple(nodes.values()), declarations),
        )

    @staticmethod
    def dependencies_hash(dependencies: Mapping) -> str:
        """Return the lock staleness stamp for a dependency table."""

        canonical = json.dumps(dependencies, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    def _resolve_dependency(
        self,
        name: str,
        specification,
        manifest_directory: str,
        *,
        refresh: bool = False,
    ) -> dict[str, str]:
        if isinstance(specification, str):
            if not specification:
                raise ValueError(f"dependency '{name}' has an empty path")
            path = specification
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(manifest_directory, path))
            return {"path": path}
        if not isinstance(specification, dict):
            raise ValueError(f"dependency '{name}' must be a path string or dependency table")
        if "path" in specification:
            path = specification["path"]
            if not isinstance(path, str) or not path:
                raise ValueError(f"dependency '{name}' must specify a non-empty path")
            if not os.path.isabs(path):
                path = os.path.normpath(os.path.join(manifest_directory, path))
            return {"path": path}
        if "git" in specification:
            revision = specification.get("rev") or specification.get("tag") or specification.get("branch") or "HEAD"
            path = self.git_dependencies.resolve(
                name,
                specification["git"],
                revision,
                refresh=refresh,
            )
            return {
                "commit": self.git_dependencies.resolved_commit(path),
                "git": specification["git"],
                "path": path,
                "rev": revision,
            }
        raise ValueError(f"dependency '{name}' must specify a path or git source")

    def _load_lock(
        self,
        lock_path: str,
        dependencies_hash: str,
        manifest_directory: str,
    ) -> dict[str, dict[str, str]] | None:
        """Return a schema-v2 resolution, or ``None`` for stale data."""

        lock = self.file_store.read_json(lock_path)
        if lock is None:
            if not os.path.exists(lock_path):
                return None
            raise LockfileError(f"cannot parse '{lock_path}' as a bounded UTF-8 JSON lockfile")
        if not isinstance(lock, dict):
            raise LockfileError(f"invalid '{lock_path}': lockfile root must be an object")
        schema = lock.get("schema")
        if schema is None:
            if set(lock) <= {"manifest_hash", "packages"} and "packages" in lock:
                return None
            raise LockfileError(f"invalid legacy lockfile '{lock_path}'")
        if schema != LOCK_SCHEMA:
            if schema == 1:
                return None
            raise LockfileVersionError(
                f"unsupported btrc.lock schema {schema!r} in '{lock_path}' "
                f"(this compiler supports schema {LOCK_SCHEMA})"
            )
        if set(lock) != {"manifest_hash", "packages", "schema"}:
            raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': unexpected fields")
        if not isinstance(lock["manifest_hash"], str):
            raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': manifest hash must be text")
        if lock["manifest_hash"] != dependencies_hash:
            return None
        locked_packages = lock["packages"]
        if not isinstance(locked_packages, dict):
            raise LockfileError(f"invalid schema-{LOCK_SCHEMA} lockfile '{lock_path}': packages must be an object")
        self._validate_locked_packages(locked_packages, lock_path)

        packages: dict[str, dict[str, str]] = {}
        for name, value in locked_packages.items():
            entry = dict(value)
            if "git" in entry:
                entry["commit"] = entry["commit"].lower()
                entry["path"] = self.git_dependencies.resolve(
                    name,
                    entry["git"],
                    entry["rev"],
                    pinned_commit=entry["commit"],
                )
            elif not os.path.isabs(entry["path"]):
                entry["path"] = os.path.normpath(os.path.join(manifest_directory, entry["path"]))
            packages[name] = entry
        return packages

    def _validate_locked_packages(
        self,
        locked_packages: dict,
        lock_path: str,
    ) -> None:
        for name, entry in locked_packages.items():
            if not isinstance(name, str) or not name or not isinstance(entry, dict):
                raise LockfileError(f"invalid schema-{LOCK_SCHEMA} package entry in '{lock_path}'")
            if "git" in entry:
                valid = (
                    set(entry) == {"commit", "git", "rev"}
                    and isinstance(entry["git"], str)
                    and bool(entry["git"])
                    and isinstance(entry["rev"], str)
                    and bool(entry["rev"])
                    and not entry["rev"].startswith("-")
                    and self.git_dependencies.is_commit_sha(entry["commit"])
                )
                if not valid:
                    raise LockfileError(f"invalid locked Git dependency '{name}' in '{lock_path}'")
            elif not (set(entry) == {"path"} and isinstance(entry["path"], str) and bool(entry["path"])):
                raise LockfileError(f"invalid locked path dependency '{name}' in '{lock_path}'")

    def _write_lock(
        self,
        lock_path: str,
        dependencies_hash: str,
        resolved: Mapping[str, Mapping[str, str]],
        manifest_directory: str,
    ) -> None:
        """Atomically record portable paths and immutable Git resolutions."""

        packages = {}
        for name, entry in resolved.items():
            if "git" in entry:
                packages[name] = {
                    "commit": entry["commit"],
                    "git": entry["git"],
                    "rev": entry["rev"],
                }
            else:
                packages[name] = {"path": os.path.relpath(entry["path"], manifest_directory)}
        self.file_store.write_json(
            lock_path,
            {
                "manifest_hash": dependencies_hash,
                "packages": packages,
                "schema": LOCK_SCHEMA,
            },
            file_mode=0o644,
        )


class GitDependencyCache:
    """Own Git execution, ref pinning, and immutable checkout publication."""

    REF_RECORD_SCHEMA = 1
    GIT_TIMEOUT_SECONDS = 300

    def __init__(
        self,
        cache_directory: str | None = None,
        *,
        file_store: PackageFileStore | None = None,
    ) -> None:
        self._configured_cache_directory = cache_directory
        self.file_store = file_store or PackageFileStore()

    def resolve(
        self,
        name: str,
        url: str,
        revision: str,
        refresh: bool = False,
        *,
        pinned_commit: str | None = None,
    ) -> str:
        """Return an immutable checkout for ``url`` at an exact commit."""

        self._validate_source(name, url, revision)
        immutable_commit = pinned_commit or (revision if self.is_commit_sha(revision) else None)
        if immutable_commit is not None:
            if not isinstance(immutable_commit, str):
                raise ValueError(f"git dependency '{name}' has an invalid pinned commit")
            commit = immutable_commit.lower()
            if not self.is_commit_sha(commit):
                raise ValueError(f"git dependency '{name}' has an invalid pinned commit")
            return self._ensure_commit_checkout(
                name,
                url,
                revision,
                commit,
            )

        record_path = self._ref_record_path(name, url, revision)
        if not refresh:
            record = self.file_store.read_json(record_path)
            if self._valid_ref_record(record, name, url, revision):
                return self._ensure_commit_checkout(
                    name,
                    url,
                    revision,
                    record["commit"],
                )

        checkout, commit = self._clone_requested_ref(name, url, revision)
        self._publish_ref_record(record_path, name, url, revision, commit)
        return checkout

    def resolved_commit(self, checkout: str) -> str:
        """Read and validate the exact commit checked out at ``checkout``."""

        commit = self._git(["-C", checkout, "rev-parse", "--verify", "HEAD"]).stdout.strip().lower()
        if not self.is_commit_sha(commit):
            raise ValueError(f"git checkout '{checkout}' did not resolve to a full commit SHA")
        return commit

    def cache_identity(self, name: str, url: str, revision: str) -> str:
        """Return collision-resistant identity over the exact source tuple."""

        digest = hashlib.sha256()
        for part in (name, url, revision):
            encoded = part.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()

    def is_commit_sha(self, value: str) -> bool:
        """Return whether value is a complete SHA-1 or SHA-256 object id."""

        return (
            isinstance(value, str)
            and len(value) in (40, 64)
            and all(character in "0123456789abcdef" for character in value.lower())
        )

    def _validate_source(self, name: str, url: str, revision: str) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError("git dependency name must be a non-empty string")
        if not isinstance(url, str) or not url:
            raise ValueError(f"git dependency '{name}' must specify a non-empty URL")
        if not isinstance(revision, str) or not revision or revision.startswith("-"):
            raise ValueError(f"git dependency '{name}' has an invalid revision")

    def _cache_directory(self) -> str:
        directory = self._configured_cache_directory or os.environ.get("BTRC_PKG_CACHE")
        directory = directory or os.path.expanduser("~/.btrc/pkgs")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _safe_label(self, name: str, revision: str) -> str:
        label = "".join(
            character if character.isalnum() or character in "-._" else "_" for character in f"{name}-{revision}"
        )
        return (label or "dependency")[:64]

    def _ref_record_path(self, name: str, url: str, revision: str) -> str:
        identity = self.cache_identity(name, url, revision)
        return os.path.join(
            self._cache_directory(),
            f".{self._safe_label(name, revision)}-{identity}.ref.json",
        )

    def _checkout_path(
        self,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> str:
        identity = self.cache_identity(name, url, revision)
        return os.path.join(
            self._cache_directory(),
            f"{self._safe_label(name, revision)}-{identity}-{commit}",
        )

    def _valid_ref_record(
        self,
        record,
        name: str,
        url: str,
        revision: str,
    ) -> bool:
        return (
            isinstance(record, dict)
            and set(record) == {"commit", "git", "name", "rev", "schema"}
            and record["schema"] == self.REF_RECORD_SCHEMA
            and record["name"] == name
            and record["git"] == url
            and record["rev"] == revision
            and self.is_commit_sha(record["commit"])
        )

    def _publish_ref_record(
        self,
        path: str,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> None:
        self.file_store.write_json(
            path,
            {
                "commit": commit,
                "git": url,
                "name": name,
                "rev": revision,
                "schema": self.REF_RECORD_SCHEMA,
            },
        )

    def _clone_requested_ref(
        self,
        name: str,
        url: str,
        revision: str,
    ) -> tuple[str, str]:
        temporary = self._clone_to_temporary(name, url, revision)
        try:
            self._checkout(temporary, revision)
            commit = self.resolved_commit(temporary)
            destination = self._checkout_path(name, url, revision, commit)
            return self._publish_checkout(temporary, destination, commit), commit
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _ensure_commit_checkout(
        self,
        name: str,
        url: str,
        revision: str,
        commit: str,
    ) -> str:
        destination = self._checkout_path(name, url, revision, commit)
        if self._checkout_matches(destination, commit):
            return os.path.abspath(destination)
        self._remove_cache_entry(destination)
        temporary = self._clone_to_temporary(name, url, revision)
        try:
            self._checkout(temporary, commit)
            actual = self.resolved_commit(temporary)
            if actual != commit:
                raise ValueError(f"git dependency '{name}' resolved pinned commit {commit} to {actual}")
            return self._publish_checkout(temporary, destination, commit)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _clone_to_temporary(self, name: str, url: str, revision: str) -> str:
        prefix = f".{self._safe_label(name, revision)}-{self.cache_identity(name, url, revision)[:16]}-"
        temporary = tempfile.mkdtemp(
            prefix=prefix,
            dir=self._cache_directory(),
        )
        try:
            self._git(["clone", "--quiet", "--", url, temporary])
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return temporary

    def _publish_checkout(
        self,
        temporary: str,
        destination: str,
        commit: str,
    ) -> str:
        try:
            os.rename(temporary, destination)
        except OSError:
            if not self._checkout_matches(destination, commit):
                raise
        return os.path.abspath(destination)

    def _checkout_matches(self, path: str, commit: str) -> bool:
        if not os.path.isdir(os.path.join(path, ".git")):
            return False
        try:
            return self.resolved_commit(path) == commit
        except (OSError, ValueError, subprocess.CalledProcessError):
            return False

    def _remove_cache_entry(self, path: str) -> None:
        if not os.path.lexists(path):
            return
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)

    def _git(self, arguments: list[str]) -> subprocess.CompletedProcess:
        return self._run_git(arguments, check=True)

    def _run_git(
        self,
        arguments: list[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess:
        """Run Git noninteractively with a finite network bound."""

        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        environment["GCM_INTERACTIVE"] = "Never"
        return subprocess.run(
            ["git", *arguments],
            check=check,
            capture_output=True,
            text=True,
            timeout=self.GIT_TIMEOUT_SECONDS,
            env=environment,
        )

    def _checkout(self, destination: str, revision: str) -> None:
        for target in (f"origin/{revision}", revision):
            result = self._run_git(
                ["-C", destination, "checkout", "--quiet", "--detach", target],
                check=False,
            )
            if result.returncode == 0:
                return
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )


__all__ = (
    "LOCK_SCHEMA",
    "GitDependencyCache",
    "IncludeResolutionError",
    "LockfileError",
    "LockfileVersionError",
    "PackageFileStore",
    "PackageManifestReader",
    "PackageUniverse",
    "ResolvedPackages",
)
