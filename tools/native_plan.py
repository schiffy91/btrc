"""Validate and realize one compiler-emitted native link plan.

The adapter is intentionally narrower than a general build-command surface:
it accepts no free-form compiler or linker flags, never invokes a shell, and
compiles only the generated C file plus units enumerated by the canonical plan.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.compiler.python.artifacts.publication import ArtifactPublisher

MAX_PLAN_BYTES = 8 * 1024 * 1024
ROOT_FIELDS = frozenset(
    {
        "defines",
        "frameworks",
        "headers",
        "include-directories",
        "linker-language",
        "packages",
        "pkg-config",
        "schema",
        "target",
        "units",
    }
)
TARGET_OPERATING_SYSTEMS = frozenset({"linux", "macos", "windows"})
TARGET_ARCHITECTURES = frozenset({"x86_64", "aarch64"})
SOURCE_STANDARDS = {
    "c": frozenset({"c11"}),
    "c++": frozenset({"c++17", "c++20"}),
    "objective-c": frozenset({"c11"}),
    "objective-c++": frozenset({"c++17", "c++20"}),
}
SOURCE_DRIVERS = {
    "c": "cc",
    "c++": "cxx",
    "objective-c": "cc",
    "objective-c++": "cxx",
}
SOURCE_LANGUAGE_ARGUMENTS = {
    "c": ("-x", "c"),
    "c++": ("-x", "c++"),
    "objective-c": ("-x", "objective-c"),
    "objective-c++": ("-x", "objective-c++"),
}
NATIVE_NAME = re.compile(r"^[A-Za-z0-9_.+-]+$")
DEFINE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class NativePlanError(ValueError):
    """A plan or build input violated the closed adapter contract."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NativePlanError(f"native link plan duplicates JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NativePlanError(f"native link plan contains invalid JSON constant {value!r}")


def _exact_mapping(value: object, fields: frozenset[str], context: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise NativePlanError(f"{context} must contain exactly {', '.join(sorted(fields))}")
    return value


def _text(value: object, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        qualifier = "text" if allow_empty else "non-empty text"
        raise NativePlanError(f"{context} must be {qualifier}")
    if "\0" in value:
        raise NativePlanError(f"{context} must not contain NUL")
    return value


def _array(value: object, context: str) -> list[object]:
    if not isinstance(value, list):
        raise NativePlanError(f"{context} must be an array")
    return value


def _regular_file(path: str, context: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise NativePlanError(f"{context} must be absolute: {path!r}")
    try:
        metadata = candidate.lstat()
    except OSError as error:
        raise NativePlanError(f"{context} is unavailable: {path!r}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise NativePlanError(f"{context} must be a real regular file: {path!r}")
    return candidate


def _real_directory(path: str, context: str) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        raise NativePlanError(f"{context} must be absolute: {path!r}")
    try:
        metadata = candidate.lstat()
    except OSError as error:
        raise NativePlanError(f"{context} is unavailable: {path!r}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise NativePlanError(f"{context} must be a real directory: {path!r}")
    return candidate


def _inside(path: Path, root: Path, context: str) -> None:
    try:
        resolved_path = path.resolve(strict=True)
        resolved_root = root.resolve(strict=True)
        contained = os.path.commonpath((resolved_path, resolved_root)) == str(resolved_root)
    except (OSError, ValueError):
        contained = False
    if not contained:
        raise NativePlanError(f"{context} escapes package root {root}")


@dataclass(frozen=True, slots=True)
class NativeUnit:
    language: str
    package: str
    path: Path
    standard: str


@dataclass(frozen=True, slots=True)
class NativeGeneratedUnit:
    name: str
    language: str
    standard: str
    memory_management: str
    source: str


@dataclass(frozen=True, slots=True)
class NativeBuildPlan:
    """Validated fields needed by the build adapter."""

    operating_system: str
    architecture: str
    linker_language: str
    include_directories: tuple[Path, ...]
    defines: tuple[tuple[str, str], ...]
    frameworks: tuple[str, ...]
    pkg_config: tuple[str, ...]
    units: tuple[NativeUnit, ...]
    generated_units: tuple[NativeGeneratedUnit, ...] = ()
    # Schema 3 supplies only a count; schema 4 names the ordered output paths.
    emitted_units: int = 0
    emitted_paths: tuple[Path, ...] = ()


class NativePlanReader:
    """Own bounded canonical JSON reads and closed schema validation."""

    @contextlib.contextmanager
    def generation(self, path: Path, generated: Path) -> Iterator[NativeBuildPlan]:
        """Lock requested and resolved output directories through the native build.

        Release all locks before expanding the sorted set, then resolve and read
        again: a publisher may move outputs or retarget an alias between attempts.
        Only generated inputs permit leaf symlinks; package inputs stay no-follow.
        This coordinates cooperating publishers, not arbitrary filesystem writers.
        """
        publication = ArtifactPublisher()
        try:
            directories = {path.parent.resolve(strict=True), generated.parent.resolve(strict=True)}
            for _ in range(8):
                with publication.read_directories(tuple(directories)):
                    bindings = {
                        source: self._generated_target(source, context)
                        for source, context in ((path, "native link plan"), (generated, "generated C input"))
                    }
                    required = self._binding_directories(bindings)
                    if required <= directories:
                        # Never read plan bytes before its physical directory is
                        # locked and checked for an interrupted publication.
                        plan = self.read(bindings[path])
                        for source in self.emitted_sources(plan, generated):
                            bindings[source] = self._generated_target(source, "emitted translation unit")
                        required.update(self._binding_directories(bindings))
                        if required <= directories and all(
                            self._generated_target(source, "generated input") == target
                            for source, target in bindings.items()
                        ):
                            yield plan
                            return
                directories.update(required)
        except (OSError, RuntimeError, ValueError) as error:
            if isinstance(error, NativePlanError):
                raise
            raise NativePlanError(str(error)) from error
        raise NativePlanError("native link plan keeps changing its source directories; retry the build")

    def _binding_directories(self, bindings: Mapping[Path, Path]) -> set[Path]:
        return {path.parent.resolve(strict=True) for pair in bindings.items() for path in pair}

    def _generated_target(self, path: Path, context: str) -> Path:
        if not path.is_absolute():
            raise NativePlanError(f"{context} must be absolute: {str(path)!r}")
        try:
            target = path.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise NativePlanError(f"{context} is unavailable: {str(path)!r}: {error}") from error
        return _regular_file(str(target), context)

    def generated_input(self, path: str, context: str) -> Path:
        """Validate the target while retaining quoted-include and debug paths."""
        candidate = Path(path)
        self._generated_target(candidate, context)
        return candidate

    def emitted_sources(self, plan: NativeBuildPlan, generated: Path) -> tuple[Path, ...]:
        """Return the ordered schema-4 paths or the legacy schema-3 filenames."""
        return plan.emitted_paths or tuple(
            self.generated_input(f"{generated}.unit-{index}.c", f"emitted translation unit {index}")
            for index in range(1, plan.emitted_units + 1)
        )

    def read(self, path: Path) -> NativeBuildPlan:
        """Inspect a plan; use generation() to keep build inputs stable."""
        encoded = self._read_regular(path)
        try:
            payload = json.loads(
                encoded.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise NativePlanError(f"cannot parse native link plan {path}: {error}") from error
        schema = payload.get("schema") if isinstance(payload, dict) else None
        fields = ROOT_FIELDS
        if schema == 2:
            fields = ROOT_FIELDS | {"generated-units"}
        elif schema in (3, 4):
            # Adapter units remain optional alongside secondary C outputs.
            fields = ROOT_FIELDS | {"emitted-units"}
            if isinstance(payload, dict) and "generated-units" in payload:
                fields = fields | {"generated-units"}
        root = _exact_mapping(payload, fields, "native link plan")
        canonical = json.dumps(root, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        if encoded != canonical.encode("utf-8"):
            raise NativePlanError("native link plan must use canonical JSON")
        return self._validate(root)

    def _read_regular(self, path: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            raise NativePlanError(f"cannot open native link plan {path}: {error}") from error
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise NativePlanError(f"native link plan must be a regular file: {path}")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                encoded = stream.read(MAX_PLAN_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if len(encoded) > MAX_PLAN_BYTES:
            raise NativePlanError(f"native link plan exceeds {MAX_PLAN_BYTES} bytes: {path}")
        return encoded

    def _validate(self, root: dict[str, object]) -> NativeBuildPlan:
        if type(root["schema"]) is not int or root["schema"] not in (1, 2, 3, 4):
            raise NativePlanError("native link plan schema must be integer 1, 2, 3 or 4")
        target = _exact_mapping(root["target"], frozenset({"arch", "os"}), "native link plan target")
        operating_system = _text(target["os"], "native link plan target.os")
        architecture = _text(target["arch"], "native link plan target.arch")
        if operating_system not in TARGET_OPERATING_SYSTEMS or architecture not in TARGET_ARCHITECTURES:
            raise NativePlanError(f"unsupported native link plan target {operating_system}-{architecture}")

        package_roots = self._packages(root["packages"])
        headers = self._path_records(root["headers"], "headers", package_roots, directory=False)
        include_directories = self._path_records(
            root["include-directories"],
            "include-directories",
            package_roots,
            directory=True,
        )
        del headers  # Header existence/ownership is validated; compilation consumes includes and units.
        defines = self._defines(root["defines"], package_roots)
        frameworks = self._name_records(root["frameworks"], "frameworks", package_roots)
        if frameworks and operating_system != "macos":
            raise NativePlanError("native link plan frameworks require a macos target")
        pkg_config = self._name_records(root["pkg-config"], "pkg-config", package_roots)
        units = self._units(root["units"], package_roots)
        generated_units = (
            self._generated_units(root["generated-units"]) if root["schema"] >= 2 and "generated-units" in root else ()
        )
        emitted_units = 0
        emitted_paths = ()
        if root["schema"] == 3 and "emitted-units" in root:
            emitted_units = root["emitted-units"]
            if type(emitted_units) is not int or not 1 <= emitted_units <= 4096:
                raise NativePlanError("native link plan emitted-units must be an integer from 1 through 4096")
        elif root["schema"] == 4:
            records = _array(root["emitted-units"], "native link plan emitted-units")
            if not records:
                raise NativePlanError("native link plan emitted-units must not be empty")
            emitted_paths = tuple(
                self.generated_input(_text(path, "emitted unit path"), f"emitted translation unit {index}")
                for index, path in enumerate(records, 1)
            )
            identities = [(path.stat().st_dev, path.stat().st_ino) for path in emitted_paths]
            if len(set(identities)) != len(identities):
                raise NativePlanError("native link plan emitted-units must name distinct files")
            emitted_units = len(emitted_paths)
        linker_language = _text(root["linker-language"], "native link plan linker-language")
        expected_linker = (
            "c++" if any(unit.language in {"c++", "objective-c++"} for unit in (*units, *generated_units)) else "c"
        )
        if linker_language != expected_linker:
            raise NativePlanError(
                f"native link plan linker-language must be {expected_linker!r} for its selected units"
            )
        return NativeBuildPlan(
            operating_system,
            architecture,
            linker_language,
            include_directories,
            defines,
            frameworks,
            pkg_config,
            units,
            generated_units,
            emitted_units,
            emitted_paths,
        )

    def _generated_units(self, value: object) -> tuple[NativeGeneratedUnit, ...]:
        units = []
        names = []
        for raw in _array(value, "native link plan generated-units"):
            record = _exact_mapping(
                raw, frozenset({"name", "language", "standard", "memory-management", "source"}), "generated unit"
            )
            name = _text(record["name"], "generated unit name")
            language = _text(record["language"], "generated unit language")
            standard = _text(record["standard"], "generated unit standard")
            memory = _text(record["memory-management"], "generated unit memory-management")
            source = _text(record["source"], "generated unit source")
            if not DEFINE_NAME.fullmatch(name):
                raise NativePlanError("generated unit name must be an identifier")
            if language not in SOURCE_STANDARDS or standard not in SOURCE_STANDARDS[language]:
                raise NativePlanError("generated unit has unsupported language or standard")
            expected_memory = "arc" if language.startswith("objective-c") else "raii" if language == "c++" else "manual"
            if memory != expected_memory:
                raise NativePlanError(f"generated {language} unit requires {expected_memory} memory-management")
            units.append(NativeGeneratedUnit(name, language, standard, memory, source))
            names.append(name)
        if not names or names != sorted(set(names)):
            raise NativePlanError("generated units must be nonempty, sorted and uniquely named")
        return tuple(units)

    def _packages(self, value: object) -> dict[str, Path]:
        packages = _array(value, "native link plan packages")
        roots: dict[str, Path] = {}
        names: list[str] = []
        dependencies: list[tuple[str, Mapping[str, object]]] = []
        for index, raw in enumerate(packages):
            package = _exact_mapping(
                raw,
                frozenset({"dependencies", "name", "root"}),
                f"native link plan packages[{index}]",
            )
            name = _text(package["name"], f"native link plan packages[{index}].name")
            if not DEFINE_NAME.fullmatch(name) or name in roots:
                raise NativePlanError(f"native link plan has invalid or duplicate package {name!r}")
            root = _real_directory(_text(package["root"], f"package {name} root"), f"package {name} root")
            raw_dependencies = package["dependencies"]
            if not isinstance(raw_dependencies, dict):
                raise NativePlanError(f"package {name} dependencies must be an object")
            roots[name] = root
            names.append(name)
            dependencies.append((name, raw_dependencies))
        if names != sorted(names):
            raise NativePlanError("native link plan packages must be sorted by name")
        for name, aliases in dependencies:
            for alias, target in aliases.items():
                if not DEFINE_NAME.fullmatch(alias) or not isinstance(target, str) or target not in roots:
                    raise NativePlanError(f"package {name} has invalid dependency edge {alias!r}")
        return roots

    def _path_records(
        self,
        value: object,
        field: str,
        roots: Mapping[str, Path],
        *,
        directory: bool,
    ) -> tuple[Path, ...]:
        result: list[tuple[str, Path]] = []
        for index, raw in enumerate(_array(value, f"native link plan {field}")):
            record = _exact_mapping(
                raw,
                frozenset({"package", "path"}),
                f"native link plan {field}[{index}]",
            )
            package = _text(record["package"], f"native link plan {field}[{index}].package")
            if package not in roots:
                raise NativePlanError(f"native link plan {field}[{index}] names unknown package {package!r}")
            path_text = _text(record["path"], f"native link plan {field}[{index}].path")
            path = (
                _real_directory(path_text, f"native link plan {field}[{index}].path")
                if directory
                else _regular_file(path_text, f"native link plan {field}[{index}].path")
            )
            _inside(path, roots[package], f"native link plan {field}[{index}].path")
            result.append((package, path))
        if result != sorted(result, key=lambda item: (item[0], str(item[1]))):
            raise NativePlanError(f"native link plan {field} must be sorted")
        if len(result) != len(set(result)):
            raise NativePlanError(f"native link plan {field} contains duplicates")
        return tuple(path for _, path in result)

    def _defines(self, value: object, roots: Mapping[str, Path]) -> tuple[tuple[str, str], ...]:
        result: list[tuple[str, str, str]] = []
        for index, raw in enumerate(_array(value, "native link plan defines")):
            record = _exact_mapping(
                raw,
                frozenset({"name", "package", "value"}),
                f"native link plan defines[{index}]",
            )
            package = _text(record["package"], f"native link plan defines[{index}].package")
            name = _text(record["name"], f"native link plan defines[{index}].name")
            detail = _text(record["value"], f"native link plan defines[{index}].value", allow_empty=True)
            if package not in roots or not DEFINE_NAME.fullmatch(name):
                raise NativePlanError(f"native link plan defines[{index}] is invalid")
            result.append((package, name, detail))
        if result != sorted(result):
            raise NativePlanError("native link plan defines must be sorted")
        if len(result) != len(set(result)):
            raise NativePlanError("native link plan defines contains duplicates")
        return tuple((name, detail) for _, name, detail in result)

    def _name_records(
        self,
        value: object,
        field: str,
        roots: Mapping[str, Path],
    ) -> tuple[str, ...]:
        result: list[tuple[str, str]] = []
        for index, raw in enumerate(_array(value, f"native link plan {field}")):
            record = _exact_mapping(
                raw,
                frozenset({"name", "package"}),
                f"native link plan {field}[{index}]",
            )
            package = _text(record["package"], f"native link plan {field}[{index}].package")
            name = _text(record["name"], f"native link plan {field}[{index}].name")
            if package not in roots or not NATIVE_NAME.fullmatch(name):
                raise NativePlanError(f"native link plan {field}[{index}] is invalid")
            result.append((package, name))
        if result != sorted(result) or len(result) != len(set(result)):
            raise NativePlanError(f"native link plan {field} must be sorted and unique")
        return tuple(name for _, name in result)

    def _units(self, value: object, roots: Mapping[str, Path]) -> tuple[NativeUnit, ...]:
        result: list[NativeUnit] = []
        keys: list[tuple[str, str, str]] = []
        for index, raw in enumerate(_array(value, "native link plan units")):
            record = _exact_mapping(
                raw,
                frozenset({"language", "package", "path", "standard"}),
                f"native link plan units[{index}]",
            )
            package = _text(record["package"], f"native link plan units[{index}].package")
            language = _text(record["language"], f"native link plan units[{index}].language")
            standard = _text(record["standard"], f"native link plan units[{index}].standard")
            if package not in roots or language not in SOURCE_STANDARDS or standard not in SOURCE_STANDARDS[language]:
                raise NativePlanError(f"native link plan units[{index}] has unsupported language or standard")
            path = _regular_file(
                _text(record["path"], f"native link plan units[{index}].path"),
                f"native link plan units[{index}].path",
            )
            _inside(path, roots[package], f"native link plan units[{index}].path")
            result.append(NativeUnit(language, package, path, standard))
            keys.append((package, str(path), language))
        if keys != sorted(keys) or len(keys) != len(set(keys)):
            raise NativePlanError("native link plan units must be sorted and unique")
        return tuple(result)


@dataclass
class NativeCompileResult:
    source: str
    command: list[str]
    cache_status: str = "disabled"
    cache_key: str | None = None
    dependency_scan_s: float = 0.0
    cache_validation_s: float = 0.0
    compile_s: float = 0.0
    publication_s: float = 0.0
    publication_status: str = "not-requested"
    preprocessing_status: str = "not-requested"


@dataclass
class NativeBuildReport:
    """Successful build evidence; per-unit durations may overlap across workers."""

    target: str
    optimization: int
    debug_info: bool
    jobs: int
    emitted_units: int
    native_units: int
    adapter_units: int
    units: list[NativeCompileResult] = field(default_factory=list)
    link_command: list[str] = field(default_factory=list)
    link_s: float = 0.0
    links: int = 0
    link_cache_status: str = "disabled"
    link_validation_s: float = 0.0
    wall_s: float = 0.0
    executable_bytes: int = 0
    preprocessing_s: float = 0.0
    preprocessing_units: int = 0
    preprocessing_hits: int = 0
    adapter_source_status: str = "none"
    debug_object_status: str = "none"

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        misses: dict[str, int] = {}
        for unit in self.units:
            if unit.cache_status not in {"hit", "disabled"}:
                misses[unit.cache_status] = misses.get(unit.cache_status, 0) + 1
        result.update(
            schema=1,
            compiled_units=sum(unit.cache_status != "hit" for unit in self.units),
            reused_units=sum(unit.cache_status == "hit" for unit in self.units),
            cache_misses=misses,
            summed_dependency_scan_s=sum(unit.dependency_scan_s for unit in self.units),
            summed_cache_validation_s=sum(unit.cache_validation_s for unit in self.units),
            summed_compile_s=sum(unit.compile_s for unit in self.units),
        )
        return result

    def write(self, path: Path) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, prefix=".report-", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(self.as_dict(), indent=2) + "\n")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


@dataclass
class _CacheProbe:
    key: str | None = None
    scan_s: float = 0.0
    reason: str = "unreadable-input"
    manifest: dict[str, object] | None = None
    receipt_hit: bool = False


class NativePlanBuilder:
    """Compile and link exactly one validated plan without a command shell."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        reader: NativePlanReader | None = None,
        process_workers: bool = False,
    ) -> None:
        self._runner = runner
        self._reader = reader or NativePlanReader()
        # A guarded process entry point may opt in. Embedded callers and
        # custom capabilities retain their existing in-process execution.
        self._process_workers = process_workers and runner is subprocess.run and reader is None

    def build(
        self,
        *,
        plan_path: Path,
        generated_c: Path,
        output: Path,
        cc: str = "cc",
        cxx: str = "c++",
        pkg_config: str = "pkg-config",
        optimization: int = 2,
        jobs: int | None = None,
        debug_info: bool = False,
        object_cache: Path | None = None,
        report_path: Path | None = None,
    ) -> NativeBuildReport:
        started = time.perf_counter()
        if type(optimization) is not int or optimization not in range(4):
            raise NativePlanError("optimization must be an integer from 0 through 3")
        if jobs is None:
            jobs = os.cpu_count() or 1
        if type(jobs) is not int or jobs < 1:
            raise NativePlanError("jobs must be a positive integer")
        plan_path = plan_path.parent.resolve(strict=True) / plan_path.name
        generated_c = generated_c.parent.resolve(strict=True) / generated_c.name
        with self._reader.generation(plan_path, generated_c) as plan:
            report = NativeBuildReport(
                f"{plan.operating_system}-{plan.architecture}",
                optimization,
                debug_info,
                jobs,
                1 + plan.emitted_units,
                len(plan.units),
                len(plan.generated_units),
            )
            generated = self._reader.generated_input(str(generated_c.absolute()), "generated C input")
            emitted = self._reader.emitted_sources(plan, generated)
            for unit in emitted:
                if unit.samefile(generated) or any(unit.samefile(native.path) for native in plan.units):
                    raise NativePlanError("emitted translation units must differ from primary and native source inputs")
            if not output.is_absolute():
                output = output.absolute()
            parent = _real_directory(str(output.parent), "native output directory")
            inputs = {plan_path.absolute(), generated, *emitted, *(unit.path for unit in plan.units)}
            self._validate_destination(output, inputs, "native output")
            if report_path is not None:
                report_path = report_path.absolute()
                _real_directory(str(report_path.parent), "native report directory")
                self._validate_destination(report_path, (*inputs, output), "native report")
            tools = {"cc": self._tool(cc, "C compiler"), "cxx": self._tool(cxx, "C++ compiler")}
            package_compile, package_link = self._pkg_config(plan, pkg_config)
            includes = [f"-I{path}" for path in plan.include_directories]
            defines = [f"-D{name}={value}" if value else f"-D{name}" for name, value in plan.defines]
            strict = ["-pedantic-errors", "-Wall", "-Wextra", "-Werror"]
            if debug_info:
                strict.append("-g")
            cache = (
                _ObjectCache(
                    object_cache,
                    self._runner,
                    target=f"{plan.operating_system}-{plan.architecture}",
                    drivers=tuple(dict.fromkeys(tools.values())),
                )
                if object_cache is not None
                else None
            )
            with tempfile.TemporaryDirectory(prefix=".btrc-native-", dir=parent) as temporary_text:
                temporary = Path(temporary_text)
                retain_adapters = False
                with contextlib.suppress(OSError):
                    retain_adapters = cache is not None and cache.directory.is_dir()
                adapter_sources, report.adapter_source_status = self._generated_sources(
                    plan, temporary, parent, retain=retain_adapters or debug_info, required=debug_info
                )
                if report_path is not None and any(
                    report_path.resolve().is_relative_to(path.parent.resolve()) for path in adapter_sources.values()
                ):
                    raise NativePlanError("native report must be outside generated adapter directories")
                objects: list[Path] = []
                commands: list[tuple[list[str], Path, Path]] = []
                for index, source in enumerate((generated, *emitted)):
                    generated_object = temporary / ("generated.o" if index == 0 else f"generated-{index}.o")
                    commands.append(
                        (
                            [
                                tools["cc"],
                                "-x",
                                "c",
                                "-std=c11",
                                *strict,
                                *includes,
                                *defines,
                                *package_compile,
                                f"-O{optimization}",
                                "-c",
                                str(source),
                                "-o",
                                str(generated_object),
                            ],
                            Path(source),
                            generated_object,
                        )
                    )
                    objects.append(generated_object)
                for index, unit in enumerate((*plan.units, *plan.generated_units)):
                    object_path = temporary / f"native-{index}.o"
                    policy = []
                    if isinstance(unit, NativeGeneratedUnit):
                        source_path = adapter_sources[unit.name]
                        if unit.memory_management == "arc":
                            policy = [
                                "-fobjc-arc",
                                "-fobjc-exceptions",
                                "-fobjc-arc-exceptions",
                                "-Werror=overriding-method-mismatch",
                            ]
                        elif unit.memory_management == "raii":
                            policy = ["-fexceptions"]
                    else:
                        source_path = unit.path
                    commands.append(
                        (
                            [
                                tools[SOURCE_DRIVERS[unit.language]],
                                *SOURCE_LANGUAGE_ARGUMENTS[unit.language],
                                f"-std={unit.standard}",
                                *strict,
                                *policy,
                                *includes,
                                *defines,
                                *package_compile,
                                f"-O{optimization}",
                                "-c",
                                str(source_path),
                                "-o",
                                str(object_path),
                            ],
                            Path(source_path),
                            object_path,
                        )
                    )
                    objects.append(object_path)
                # Shared receipt validation precedes the bounded compile pool.
                # Only each job's own manifest crosses a process boundary.
                prepared = [None] * len(commands)
                if cache is not None:
                    preparation = time.perf_counter()
                    prepared = cache.prepare([(command, source) for command, source, _ in commands], jobs)
                    report.preprocessing_s = time.perf_counter() - preparation
                work = [(*command, probe) for command, probe in zip(commands, prepared, strict=True)]
                # Fully prepared receipts leave file copying/hashing and native
                # subprocesses, so threads avoid redundant interpreter startup.
                # Ordinary Python validation still uses the process pool.
                compile_one = lambda job: self._compile(cache, *job)  # noqa: E731
                if (
                    self._process_workers
                    and cache is not None
                    and jobs > 1
                    and len(commands) > jobs
                    and any(probe is None for probe in prepared)
                ):
                    from concurrent.futures import ProcessPoolExecutor
                    from concurrent.futures.process import BrokenProcessPool
                    from multiprocessing import get_context

                    # Separate interpreters avoid GIL contention while each
                    # worker reads and hashes its current inputs. Spawn avoids
                    # inheriting the parent's publication locks or thread state.
                    try:
                        with ProcessPoolExecutor(
                            max_workers=jobs,
                            mp_context=get_context("spawn"),
                            initializer=self._initialize_compile_worker,
                        ) as pool:
                            pending = [pool.submit(self._compile, cache, *job) for job in work]
                            report.units.extend(result.result() for result in pending)
                    except BrokenProcessPool as error:
                        raise NativePlanError("native compile worker exited unexpectedly") from error
                elif jobs > 1 and len(commands) > 1:
                    from concurrent.futures import ThreadPoolExecutor

                    with ThreadPoolExecutor(max_workers=min(jobs, len(commands))) as pool:
                        report.units.extend(pool.map(compile_one, work))
                else:
                    for job in work:
                        report.units.append(compile_one(job))
                report.preprocessing_units = sum(
                    unit.preprocessing_status.startswith("receipt-") for unit in report.units
                )
                report.preprocessing_hits = sum(unit.preprocessing_status == "receipt-hit" for unit in report.units)
                if debug_info and plan.operating_system == "macos":
                    objects, report.debug_object_status = self._retain_debug_objects(objects, temporary, parent)
                staged = temporary / output.name
                runtime_libraries = ["-lm"]
                if plan.operating_system != "windows":
                    runtime_libraries.append("-pthread")
                # Group packages may each declare the same framework; link it once.
                framework_flags = [part for name in dict.fromkeys(plan.frameworks) for part in ("-framework", name)]
                report.link_command = [
                    tools["cxx" if plan.linker_language == "c++" else "cc"],
                    *(str(path) for path in objects),
                    *package_link,
                    *framework_flags,
                    *runtime_libraries,
                    "-o",
                    str(staged),
                ]
                self._link(report, objects, staged, output, cache)
            if cache is not None:
                cache.prune()
            report.wall_s = time.perf_counter() - started
            report.executable_bytes = output.stat().st_size
            if report_path is not None:
                report.write(report_path)
            return report

    def _link(
        self, report: NativeBuildReport, objects: list[Path], staged: Path, output: Path, cache: _ObjectCache | None
    ) -> None:
        publication = ArtifactPublisher()
        # A parent lock also serializes differently spelled aliases of the
        # same destination on case-insensitive filesystems.
        with publication.lock(output.parent, "native-link"):
            started = time.perf_counter()
            receipt = None
            context = None
            if cache is not None and sys.platform == "darwin" and report.target.startswith("macos-"):
                receipt = _DarwinLinkReceipt(
                    cache.directory,
                    self._runner,
                    report.link_command.copy(),
                    objects,
                    output,
                    {
                        "target": report.target,
                        "optimization": report.optimization,
                        "debug": report.debug_info,
                        "unit_keys": [
                            unit.cache_key
                            if unit.cache_status == "hit" or unit.publication_status == "stored"
                            else None
                            for unit in report.units
                        ],
                        "sources": [unit.source for unit in report.units],
                    },
                )
                context = receipt.context()
                report.link_cache_status = "unsupported-input" if context is None else "miss"
                if context is not None and receipt.retained(context):
                    report.link_cache_status = "hit"
                    report.link_validation_s = time.perf_counter() - started
                    return
            dependencies_path = staged.parent / "link.dependencies"
            if context is not None:
                report.link_command.extend(["-Xlinker", "-dependency_info", "-Xlinker", str(dependencies_path)])
            report.link_validation_s = time.perf_counter() - started
            link_started = time.perf_counter()
            self._run(report.link_command)
            report.links += 1
            report.link_s += time.perf_counter() - link_started
            qualified = False
            if context is not None:
                started = time.perf_counter()
                try:
                    dependencies = receipt.dependencies(dependencies_path)
                    before = receipt.snapshot(dependencies)
                    ready = receipt.context() == context
                except (OSError, ValueError, TypeError, KeyError):
                    ready = False
                report.link_validation_s += time.perf_counter() - started
                if ready:
                    link_started = time.perf_counter()
                    self._run(report.link_command)
                    report.links += 1
                    report.link_s += time.perf_counter() - link_started
                    started = time.perf_counter()
                    with contextlib.suppress(OSError, ValueError, TypeError, KeyError):
                        qualified = (
                            receipt.dependencies(dependencies_path) == dependencies
                            and receipt.snapshot(dependencies) == before
                            and receipt.context() == context
                        )
                    report.link_validation_s += time.perf_counter() - started
            os.replace(staged, output)
            if qualified:
                report.link_cache_status = (
                    "stored" if receipt.store(context, dependencies, before) else "publication-failed"
                )
            elif context is not None:
                report.link_cache_status = "unverified-inputs"

    def _validate_destination(self, path: Path, inputs: Sequence[Path] | set[Path], subject: str) -> None:
        for candidate in (path, path.resolve()):
            if any(part.startswith(".btrc-debug-") for part in candidate.parts):
                raise NativePlanError(f"{subject} must be outside retained debug object directories: {path}")
            if candidate.name == ".btrc-publications.lock" or (
                candidate.name.startswith(".") and ".publish." in candidate.name
            ):
                raise NativePlanError(f"{subject} must not replace publication control files: {path}")
        for existing in inputs:
            if path.resolve() == existing.resolve() or (
                path.exists() and existing.exists() and path.samefile(existing)
            ):
                raise NativePlanError(f"{subject} must differ from its output, plan and source inputs")

    def _generated_sources(
        self, plan: NativeBuildPlan, temporary: Path, parent: Path, *, retain: bool, required: bool = False
    ) -> tuple[dict[str, Path], str]:
        """Materialize one immutable adapter generation without rewriting paths.

        Both temporary and retained sources sit one directory below the native
        output parent, preserving relative quoted-include lookup. Stable real
        paths are still part of ordinary dependency validation and debug data.
        Retained generations live until their build-output directory is cleaned;
        a builder must not prune files another compiler may still be reading.
        """
        if not plan.generated_units:
            return {}, "none"
        filenames = {
            unit.name: f"adapter-{len(plan.units) + index}.source" for index, unit in enumerate(plan.generated_units)
        }
        contents = {filenames[unit.name]: unit.source.encode("utf-8") for unit in plan.generated_units}
        if retain:
            manifest = {
                "schema": 1,
                "units": [
                    {
                        "name": unit.name,
                        "file": filenames[unit.name],
                        "language": unit.language,
                        "standard": unit.standard,
                        "memory-management": unit.memory_management,
                        "sha256": hashlib.sha256(contents[filenames[unit.name]]).hexdigest(),
                    }
                    for unit in plan.generated_units
                ],
            }
            encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            destination = parent / f".btrc-adapters-v1-{hashlib.sha256(encoded).hexdigest()}"
            expected = {**contents, "manifest.json": encoded}
            try:
                if not destination.exists():
                    staged = temporary / "sources"
                    staged.mkdir()
                    for name, content in expected.items():
                        (staged / name).write_bytes(content)
                    # Atomic directory publication: another caller either sees
                    # the complete generation or verifies its own race winner.
                    staged.rename(destination)
            except OSError:
                pass
            if self._generated_sources_match(destination, expected):
                return {name: destination / filename for name, filename in filenames.items()}, "retained"
            if required:
                # Debug source is an output dependency even without an object
                # cache. Never silently delete it on the fallback path.
                staged = temporary / "private-sources"
                staged.mkdir()
                for name, content in expected.items():
                    (staged / name).write_bytes(content)
                destination = parent / f".btrc-adapters-private-{temporary.name}"
                staged.rename(destination)
                return {name: destination / filename for name, filename in filenames.items()}, "retained-private"
        # Never repair/remove a shared generation in place: another build may
        # have it open. A partial/corrupt/unwritable cache only forfeits reuse.
        for name, content in contents.items():
            (temporary / name).write_bytes(content)
        return {
            name: temporary / filename for name, filename in filenames.items()
        }, "fallback" if retain else "temporary"

    def _generated_sources_match(self, directory: Path, expected: dict[str, bytes]) -> bool:
        try:
            _real_directory(str(directory), "generated adapter directory")
            with os.scandir(directory) as entries:
                if {entry.name for entry in entries} != set(expected):
                    return False
            for name, content in expected.items():
                path = _regular_file(str(directory / name), "generated adapter artifact")
                if self._reader._read_regular(path) != content:
                    return False
        except (OSError, NativePlanError):
            return False
        return True

    def _retain_debug_objects(self, objects: list[Path], temporary: Path, parent: Path) -> tuple[list[Path], str]:
        """Keep Darwin debug-map inputs with the build outputs, not the cache.

        Mach-O stores paths and timestamps of the linked objects instead of
        their DWARF. Immutable generations survive temporary cleanup and cache
        eviction; the build directory owns their lifetime. A fixed timestamp
        lets identical generations remain valid across uncached recompiles.
        """
        hashes = {}
        for path in objects:
            with path.open("rb") as stream:
                hashes[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
        encoded = (json.dumps({"schema": 1, "objects": hashes}, sort_keys=True) + "\n").encode("utf-8")
        destination = parent / f".btrc-debug-v1-{hashlib.sha256(encoded).hexdigest()}"
        if self._debug_objects_match(destination, hashes, encoded):
            return [destination / path.name for path in objects], "retained"
        staged = temporary / "debug-objects"
        staged.mkdir()
        for path in objects:
            target = staged / path.name
            shutil.copyfile(path, target)
            # A nonzero, stable second is representable in Darwin N_OSO records.
            os.utime(target, (1, 1))
        (staged / "manifest.json").write_bytes(encoded)
        status = "retained"
        try:
            if destination.exists():
                raise FileExistsError(destination)
            staged.rename(destination)
        except OSError:
            if self._debug_objects_match(destination, hashes, encoded):
                return [destination / path.name for path in objects], status
            # Never repair a shared generation in place: an older executable
            # or concurrent debugger may still refer to it.
            destination = parent / f".btrc-debug-private-{temporary.name}"
            staged.rename(destination)
            status = "retained-private"
        if not self._debug_objects_match(destination, hashes, encoded):
            raise NativePlanError("retained debug object generation changed during publication")
        return [destination / path.name for path in objects], status

    def _debug_objects_match(self, directory: Path, hashes: dict[str, str], encoded: bytes) -> bool:
        try:
            _real_directory(str(directory), "debug object directory")
            with os.scandir(directory) as entries:
                if {entry.name for entry in entries} != {*hashes, "manifest.json"}:
                    return False
            manifest = _regular_file(str(directory / "manifest.json"), "debug object manifest")
            if self._reader._read_regular(manifest) != encoded:
                return False
            for name, digest in hashes.items():
                path = _regular_file(str(directory / name), "debug object")
                if path.stat().st_mtime_ns != 1_000_000_000:
                    return False
                with path.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                        return False
        except (OSError, NativePlanError):
            return False
        return True

    @staticmethod
    def _initialize_compile_worker() -> None:
        from multiprocessing import parent_process
        from multiprocessing.connection import wait
        from threading import Thread

        parent = parent_process()
        if parent is None:
            raise NativePlanError("native compile worker has no owning process")

        def watch_owner() -> None:
            wait([parent.sentinel])
            # Queue endpoints can keep an orphaned ProcessPoolExecutor worker
            # alive indefinitely. The inherited parent sentinel is an ownership
            # handle, unaffected by PID reuse or whether a job is still active.
            os._exit(1)

        Thread(target=watch_owner, name="native-compile-owner", daemon=True).start()

    def _compile(
        self,
        cache: _ObjectCache | None,
        command: list[str],
        source: Path,
        object_path: Path,
        prepared: _CacheProbe | None = None,
    ) -> NativeCompileResult:
        """Run one compile, or copy the object the cache holds for the same source and command."""
        result = NativeCompileResult(str(source), command)
        if cache is not None:
            started = time.perf_counter()
            probe = prepared if prepared is not None and prepared.key is not None else cache.probe(command, source)
            if probe.key is not None and probe.manifest is not None:
                cache._manifests[probe.key] = probe.manifest
                result.preprocessing_status = "receipt-hit" if probe.receipt_hit else "receipt-captured"
            else:
                result.preprocessing_status = "ordinary"
            result.cache_key = probe.key
            result.dependency_scan_s = probe.scan_s
            result.cache_status = cache.restore(probe.key, object_path) if probe.key is not None else probe.reason
            result.cache_validation_s = time.perf_counter() - started - probe.scan_s
            if result.cache_status == "hit":
                return result
        started = time.perf_counter()
        self._run(command)
        result.compile_s = time.perf_counter() - started
        # A source/header changed while the compiler ran must not publish an
        # object under the earlier inputs. A failed validation leaves the build
        # usable but uncached; normal compiler diagnostics remain authoritative.
        if result.cache_key is not None:
            started = time.perf_counter()
            after = cache.probe(command, source)
            result.dependency_scan_s += after.scan_s
            result.cache_validation_s += time.perf_counter() - started - after.scan_s
            result.publication_status = "inputs-changed"
            if after.key == result.cache_key:
                started = time.perf_counter()
                result.publication_status = "stored" if cache.store(result.cache_key, object_path) else "failed"
                result.publication_s = time.perf_counter() - started
        return result

    def _tool(self, value: str, context: str) -> str:
        _text(value, context)
        resolved = shutil.which(value)
        if resolved is None:
            raise NativePlanError(f"{context} is unavailable: {value!r}")
        return resolved

    def _pkg_config(self, plan: NativeBuildPlan, executable: str) -> tuple[list[str], list[str]]:
        if not plan.pkg_config:
            return [], []
        tool = self._tool(executable, "pkg-config tool")
        return (
            self._pkg_config_arguments(tool, "--cflags", plan.pkg_config),
            self._pkg_config_arguments(tool, "--libs", plan.pkg_config),
        )

    def _pkg_config_arguments(self, tool: str, mode: str, packages: Sequence[str]) -> list[str]:
        completed = self._runner(
            [tool, mode, *packages],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip()
            raise NativePlanError(f"pkg-config {mode} failed for {', '.join(packages)}: {detail}")
        try:
            arguments = shlex.split(completed.stdout, posix=os.name != "nt")
        except ValueError as error:
            raise NativePlanError(f"pkg-config {mode} returned malformed arguments: {error}") from error
        if any("\0" in argument for argument in arguments):
            raise NativePlanError(f"pkg-config {mode} returned an argument containing NUL")
        return arguments

    def _run(self, command: list[str]) -> None:
        completed = self._runner(command, capture_output=True, text=True, check=False, shell=False)
        if completed.returncode != 0:
            rendered = " ".join(shlex.quote(part) for part in command)
            detail = completed.stderr.strip()
            raise NativePlanError(f"native build command failed ({rendered}): {detail}")


class _DarwinLinkReceipt:
    """Prove a retained executable against Darwin's real link dependencies.

    A discovery link establishes the input set. A second link bracketed by
    content/negative-lookup snapshots qualifies the receipt. Later invocations
    validate those inputs and the executable before skipping the linker.
    """

    def __init__(
        self,
        directory: Path,
        runner: Callable[..., subprocess.CompletedProcess[str]],
        command: list[str],
        objects: list[Path],
        output: Path,
        configuration: dict[str, object],
    ) -> None:
        self.directory = directory / "links"
        self.runner = runner
        self.command = command
        self.objects = objects
        self.output = output
        self.configuration = configuration
        self.path = self.directory / ("link-v1-" + hashlib.sha256(str(output).encode()).hexdigest() + ".json")

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return self.runner(command, capture_output=True, text=True, check=False, shell=False)

    def _file(self, path: str | Path) -> dict[str, object]:
        path = Path(path)
        resolved = path.resolve(strict=True)
        with resolved.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("link dependency is not a regular file")
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            after = os.fstat(stream.fileno())
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_mode)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_mode)
            or path.resolve(strict=True) != resolved
            or resolved.stat() != after
        ):
            raise ValueError("link dependency changed while reading")
        return {"path": str(path), "resolved": str(resolved), "sha256": digest, "mode": stat.S_IMODE(after.st_mode)}

    def _tool(self, path: str | Path) -> dict[str, object]:
        path = Path(path)
        identity = self._file(path)
        with path.open("rb") as stream:
            script = stream.read(2) == b"#!"
        if script:
            # Standard Nix wrappers close over immutable store inputs. Retain
            # their support inventory as well as the selected wrapper bytes.
            root = path.resolve().parent.parent
            if root.parent != Path("/nix/store") or not re.fullmatch(r"[0-9a-df-np-sv-z]{32}-.+", root.name):
                raise ValueError("unqualified compiler/linker wrapper")
            support = root / "nix-support"
            if not support.is_dir():
                raise ValueError("missing Nix wrapper support")
            identity["support"] = [self._file(p) for p in sorted(support.iterdir())]
        return identity

    def _traced(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return self.runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            env={**os.environ, "DYLD_PRINT_LIBRARIES": "1"},
        )

    def _images(self, *traces: subprocess.CompletedProcess[str]) -> list[dict[str, object]]:
        images = set()
        for trace in traces:
            for line in trace.stderr.splitlines():
                match = re.fullmatch(r"dyld\[\d+\]: <([0-9A-Fa-f-]{36})> (/.+)", line)
                if match:
                    images.add((match[2], match[1]))
        if not images:
            raise ValueError("toolchain loader identity unavailable")
        identities = []
        for name, uuid in sorted(images):
            path = Path(name)
            if path.exists():
                identities.append({"uuid": uuid, "file": self._file(path)})
            elif name.startswith(("/usr/lib/", "/System/Library/")):
                # These images live in the sealed OS shared cache, not separate
                # files. The loader's actual image UUID identifies that content.
                identities.append({"uuid": uuid, "shared_cache_path": name})
            else:
                raise ValueError("unreadable toolchain image")
        return identities

    def context(self) -> dict[str, object] | None:
        try:
            if os.environ.get("DYLD_DIAGNOSTICS_FILE"):
                return None
            if any(unit is None for unit in self.configuration["unit_keys"]):
                return None
            traced = self._run([*self.command, "-###"])
            if traced.returncode or "clang version" not in traced.stderr:
                return None
            lines = [line.strip() for line in traced.stderr.splitlines() if line.lstrip().startswith('"')]
            if len(lines) != 1:
                return None
            expanded = shlex.split(lines[0])
            linker = self._tool(expanded[0])
            version = self._traced([expanded[0], "-v"])
            if "PROGRAM:ld PROJECT:ld" not in version.stdout + version.stderr:
                return None
            roots = [
                Path("/usr/lib"),
                Path("/usr/local/lib"),
                Path("/Library/Frameworks"),
                Path("/System/Library/Frameworks"),
            ]
            roots.extend(
                Path(line.strip()) for line in (version.stdout + version.stderr).splitlines() if line.startswith("\t/")
            )
            side_inputs = []
            ordinary = {str(p) for p in self.objects}
            index = 1
            no_value = {
                "-demangle",
                "-dynamic",
                "-pie",
                "-no_deduplicate",
                "-search_paths_first",
                "-headerpad_max_install_names",
                "-no_warn_duplicate_libraries",
                "-dead_strip",
                "-ObjC",
            }
            scalar = {"-arch", "-o", "-framework", "-rpath"}
            while index < len(expanded):
                arg = expanded[index]
                if (
                    arg in ordinary
                    or arg in no_value
                    or (
                        arg.startswith("-l")
                        and len(arg) > 2
                        and not arg.startswith(("-lto", "-lazy", "-load", "-link"))
                    )
                ):
                    index += 1
                elif arg in scalar:
                    index += 2
                elif arg == "-platform_version":
                    index += 4
                elif arg == "-mllvm" and expanded[index + 1] == "-enable-linkonceodr-outlining":
                    index += 2
                elif arg in {"-L", "-F", "-syslibroot"}:
                    roots.append(Path(expanded[index + 1]).absolute())
                    index += 2
                elif arg.startswith(("-L", "-F")):
                    roots.append(Path(arg[2:]).absolute())
                    index += 1
                elif arg == "-lto_library":
                    side_inputs.append(self._file(expanded[index + 1]))
                    index += 2
                elif not arg.startswith("-") and Path(arg).suffix in {".a", ".dylib", ".tbd"}:
                    side_inputs.append(self._file(arg))
                    index += 1
                else:
                    return None
            installed = [
                line.removeprefix("InstalledDir: ")
                for line in traced.stderr.splitlines()
                if line.startswith("InstalledDir: ")
            ]
            if len(installed) != 1:
                return None
            compiler = Path(installed[0]) / "clang"
            compiler_version = self._traced([str(compiler), "--version"])
            images = self._images(version, compiler_version)
            object_identities = []
            for path in self.objects:
                identity = self._file(path)
                if self.configuration["debug"]:
                    identity["mtime_ns"] = path.stat().st_mtime_ns
                else:
                    identity.pop("path")
                    identity.pop("resolved")
                object_identities.append(identity)

            def normalized(arguments: Sequence[str]) -> list[object]:
                result = []
                for value in arguments:
                    if value in ordinary:
                        result.append({"object": next(i for i, p in enumerate(self.objects) if str(p) == value)})
                    elif value == self.command[-1]:
                        result.append({"output": str(self.output)})
                    else:
                        result.append(value)
                return result

            return {
                "schema": 1,
                "configuration": self.configuration,
                "command": normalized(self.command),
                "expanded": normalized(expanded),
                "driver": self._tool(self.command[0]),
                "compiler": self._tool(compiler),
                "linker": linker,
                "linker_version": version.stdout
                + "\n".join(line for line in version.stderr.splitlines() if not line.startswith("dyld[")),
                "toolchain_images": images,
                "side_inputs": side_inputs,
                "objects": object_identities,
                "search_roots": [
                    {"path": str(p), "resolved": str(p.resolve()), "directory": p.is_dir()} for p in roots
                ],
                "cwd": str(Path.cwd()),
                "host": list(os.uname()),
                "environment": hashlib.sha256(_ObjectCache._encoded(dict(os.environ))).hexdigest(),
            }
        except (OSError, ValueError, IndexError):
            return None

    def dependencies(self, path: Path) -> dict[str, list[str]]:
        data = NativePlanReader()._read_regular(path)
        records = []
        position = 0
        while position < len(data):
            opcode = data[position]
            end = data.index(0, position + 1)
            value = os.fsdecode(data[position + 1 : end])
            if opcode not in {0, 0x10, 0x11, 0x40} or not value:
                raise ValueError("invalid linker dependency record")
            records.append((opcode, value))
            position = end + 1
        if not records or records[0][0] != 0 or sum(opcode == 0 for opcode, _ in records) != 1:
            raise ValueError("missing linker dependency version")
        outputs = [Path(value).resolve() for opcode, value in records if opcode == 0x40]
        if outputs != [Path(self.command[-1]).resolve()]:
            raise ValueError("linker dependency output mismatch")
        objects = {p.resolve() for p in self.objects}
        found = {Path(value).absolute() for opcode, value in records if opcode == 0x10}
        if not objects <= {p.resolve() for p in found}:
            raise ValueError("linker omitted object dependencies")
        return {
            "inputs": sorted(str(p) for p in found if p.resolve() not in objects),
            "missing": sorted({str(Path(value).absolute()) for opcode, value in records if opcode == 0x11}),
        }

    def snapshot(self, dependencies: dict[str, list[str]]) -> dict[str, object]:
        if set(dependencies) != {"inputs", "missing"} or not dependencies["inputs"]:
            raise ValueError("invalid link dependency inventory")
        if any(os.path.lexists(p) for p in dependencies["missing"]):
            raise ValueError("a previously missing link candidate now exists")
        return {"inputs": [self._file(p) for p in dependencies["inputs"]], "missing": dependencies["missing"]}

    def retained(self, context: dict[str, object]) -> bool:
        try:
            record = json.loads(NativePlanReader()._read_regular(self.path))
            if set(record) != {"context", "dependencies", "snapshot", "output"} or record["context"] != context:
                return False
            _regular_file(str(self.output), "retained executable")
            return (
                self.snapshot(record["dependencies"]) == record["snapshot"]
                and self._file(self.output) == record["output"]
            )
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            return False

    def store(
        self, context: dict[str, object], dependencies: dict[str, list[str]], snapshot: dict[str, object]
    ) -> bool:
        try:
            self.directory.mkdir(exist_ok=True)
            record = {
                "context": context,
                "dependencies": dependencies,
                "snapshot": snapshot,
                "output": self._file(self.output),
            }
            with tempfile.NamedTemporaryFile(dir=self.directory, prefix=".link-", delete=False) as stream:
                candidate = Path(stream.name)
                stream.write(_ObjectCache._encoded(record))
            try:
                os.replace(candidate, self.path)
            finally:
                candidate.unlink(missing_ok=True)
        except OSError:
            return False
        return True


class _PreprocessingReceipts:
    """Fresh driver expansion and one bound reader session for native inputs."""

    def __init__(self, directory: Path, drivers: tuple[str, ...], runner: Callable) -> None:
        self.directory = directory
        self.drivers = drivers
        self.reader = None
        if (
            sys.platform == "darwin"
            and runner is subprocess.run
            and drivers
            and all(driver.startswith("/nix/store/") for driver in drivers)
            and os.environ.get("BTRC_NATIVE_PREPROCESS_RECEIPTS", "1") != "0"
        ):
            candidate = os.environ.get("BTRC_NATIVE_HEADER_READER") or shutil.which("btrc-native-header")
            if candidate and candidate.startswith("/nix/store/"):
                self.reader = candidate

    @staticmethod
    def _arguments(command: list[str]) -> list[str]:
        arguments = command[1:].copy()
        output = arguments.index("-o")
        del arguments[output : output + 2]
        arguments.remove("-c")
        return arguments

    def _expand(self, command: list[str], directory: Path) -> list[str] | None:
        try:
            arguments = self._arguments(command)
            if any(arg.startswith(("@", "-fmodule", "-include-pch", "-include-pth")) for arg in arguments):
                return None
            result = subprocess.run(
                [
                    command[0],
                    *arguments,
                    "-E",
                    "-MD",
                    "-MF",
                    str(directory / "source.d"),
                    "-MT",
                    "btrc-object",
                    "-Xclang",
                    "-header-include-file",
                    "-Xclang",
                    str(directory / "headers.txt"),
                    "-Xclang",
                    "-fshow-skipped-includes",
                    "-o",
                    str(directory / "source.i"),
                    "-###",
                ],
                capture_output=True,
                text=True,
                shell=False,
                timeout=30,
            )
            if result.returncode or len(result.stderr.encode()) > MAX_PLAN_BYTES:
                return None
            jobs = [shlex.split(line.strip()) for line in result.stderr.splitlines() if line.lstrip().startswith('"')]
            if len(jobs) != 1 or len(jobs[0]) < 3 or jobs[0][1] != "-cc1":
                return None
            return jobs[0]
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None

    def read(self, commands: list[tuple[list[str], Path]], jobs: int, *, capture: bool) -> list[dict | None]:
        empty = [None] * len(commands)
        if not self.reader or not commands:
            return empty
        # These existing reader owners supply process-group deadlines, bounded
        # captures and no-follow, checksummed private blob reads for both APIs.
        from src.compiler.python.frontend.native_imports import NativeHeaderRead, NativeHeaderSession

        try:
            directory = str(self.directory.resolve(strict=True) / "preprocessing-v1")
            with tempfile.TemporaryDirectory(prefix=".expand-", dir=self.directory) as temporary:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=min(jobs, len(commands))) as pool:
                    expanded = list(pool.map(lambda item: self._expand(item[0], Path(temporary)), commands))
            requested = [(index, arguments) for index, arguments in enumerate(expanded) if arguments is not None]
            if not requested:
                return empty
            payload = json.dumps(
                {
                    "schema": "btrc.native-preprocess.v1",
                    "capture": capture,
                    "cache_directory": directory,
                    "drivers": list(self.drivers),
                    "units": [{"id": str(index), "cc1": arguments} for index, arguments in requested],
                }
            )
            if len(payload.encode()) > MAX_PLAN_BYTES:
                return empty
            encoded = NativeHeaderRead((self.reader, "--native-preprocess=-"), (0,), payload).read(dict(os.environ))
            response = json.loads(encoded, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            if (
                not isinstance(response, dict)
                or response.get("schema") != "btrc.native-preprocess.v1"
                or response.get("launcher") != self.reader
                or response.get("eligible_launcher") is not True
            ):
                return empty
            contexts, units = response.get("contexts"), response.get("units")
            if not isinstance(contexts, list) or not isinstance(units, list) or len(units) != len(requested):
                return empty
            bound = set()
            for context in contexts:
                if not isinstance(context, dict):
                    return empty
                if context.get("eligible") is True:
                    compiler = context.get("compiler")
                    if not isinstance(compiler, str) or context.get("drivers") != list(self.drivers):
                        return empty
                    bound.add(compiler)
            results = empty.copy()
            for (index, arguments), unit in zip(requested, units, strict=True):
                if not isinstance(unit, dict) or unit.get("id") != str(index):
                    return empty
                if unit.get("eligible") is not True:
                    continue
                identity, streams = unit.get("identity_sha256"), unit.get("response")
                if (
                    str(Path(arguments[0]).resolve(strict=True)) not in bound
                    or not isinstance(identity, str)
                    or not re.fullmatch("[0-9a-f]{64}", identity)
                    or type(unit.get("cache_hit")) is not bool
                ):
                    return empty
                if not capture and not unit["cache_hit"] and unit.get("reason") == "receipt-miss" and streams is None:
                    results[index] = {"identity": identity, "content": None, "cache_hit": False}
                    continue
                if not isinstance(streams, dict):
                    return empty
                text = NativeHeaderSession._stream(directory, streams.get("stdout"), MAX_PLAN_BYTES)
                errors = NativeHeaderSession._stream(directory, streams.get("stderr"), MAX_PLAN_BYTES)
                if text is None or errors is None:
                    return empty
                content = json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
                _exact_mapping(
                    content,
                    frozenset({"schema", "preprocessed", "dependencies", "headers", "buffers"}),
                    "preprocessed inputs",
                )
                if content["schema"] != "btrc.native-preprocessed.v1":
                    return empty
                for name in ["preprocessed", "dependencies", "headers"]:
                    if not isinstance(content[name], str) or not re.fullmatch("[0-9a-f]{64}", content[name]):
                        return empty
                buffers = content["buffers"]
                if not isinstance(buffers, list) or not buffers:
                    return empty
                paths = set()
                for buffer in buffers:
                    if (
                        not isinstance(buffer, list)
                        or len(buffer) != 2
                        or not isinstance(buffer[0], str)
                        or not buffer[0]
                        or "\0" in buffer[0]
                        or not isinstance(buffer[1], str)
                        or not re.fullmatch("[0-9a-f]{64}", buffer[1])
                    ):
                        return empty
                    paths.add(os.path.abspath(buffer[0]))
                if os.path.abspath(commands[index][1]) not in paths:
                    return empty
                results[index] = {"identity": identity, "content": content, "cache_hit": unit["cache_hit"]}
            return results
        except (OSError, ValueError, UnicodeError, RecursionError, subprocess.TimeoutExpired):
            return empty


class _ObjectCache:
    """Validate current preprocessing before reusing a native object.

    Scanning again is intentional: yesterday's dependency list cannot detect
    a newly created header earlier on the include path. Include system headers,
    observable source paths and compiler bytes, not only source mtimes/version.
    Cache failure is always a miss; the normal compile supplies diagnostics.
    """

    SCHEMA = 3
    KEEP_SECONDS = 14 * 24 * 3600
    _MAKE_WORDS = re.compile(r"(?:\\[ \t#\\]|[^\s])+")
    _MAKE_ESCAPES = re.compile(r"\\([ \t#\\])")

    def __init__(
        self,
        directory: Path,
        runner: Callable[..., subprocess.CompletedProcess[str]],
        *,
        target: str,
        drivers: tuple[str, ...] = (),
    ) -> None:
        self.directory = directory
        self._runner = runner
        self._target = target
        self._receipts = _PreprocessingReceipts(directory, drivers, runner)
        self._manifests: dict[str, dict[str, object]] = {}
        # An optional cache must not make an otherwise valid build fail.
        with contextlib.suppress(OSError):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _file_digest(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    @staticmethod
    def _encoded(value: object) -> bytes:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")

    @classmethod
    def _dependency_words(cls, text: str) -> list[str]:
        """Read the single -MT rule, including Make escaping (not shell quoting)."""
        target, separator, body = text.replace("\\\r\n", "").replace("\\\n", "").partition(":")
        if not separator or target != "btrc-object":
            raise ValueError("unexpected dependency rule")
        words = [
            (cls._MAKE_ESCAPES.sub(r"\1", word) if "\\" in word else word).replace("$$", "$")
            for word in cls._MAKE_WORDS.findall(body)
        ]
        if not words:
            raise ValueError("empty dependency rule")
        return words

    @classmethod
    def _dependencies(cls, text: str) -> list[Path]:
        return [Path(word).absolute() for word in dict.fromkeys(cls._dependency_words(text))]

    @classmethod
    def _clang_dependencies(cls, text: str, headers: str, source: Path) -> list[Path]:
        """Recover physical include names without dropping other dependencies.

        Clang's Make writer converts backslashes to separators on POSIX and
        leaves tabs unquoted. Its header report retains both, but omits inputs
        such as __has_include probes. Reconcile reported names against their
        Make spelling, then retain the remaining dependency words as well.
        Multiplicity matters: two distinct files can have one Make spelling.
        """
        names = [str(source)]
        for line in headers.split("\n"):
            if not line:
                continue
            # Lexer::Stringify quotes backslashes and double quotes, but folds
            # CR, LF and CRLF into the same escape. That spelling is ambiguous;
            # decline reuse instead of guessing which physical file was read.
            if "\\" in line:
                if not re.fullmatch(r'(?:[^\\]|\\[\\"])*', line):
                    raise ValueError("ambiguous Clang header report")
                line = re.sub(r'\\([\\"])', r"\1", line)
            names.append(line)
        names = list(dict.fromkeys(names))
        remaining = Counter(cls._dependency_words(text))
        for name in names:
            while name.startswith("./"):
                name = name[2:]
            # After Make decoding, Clang's quoted spaces, dollars and hashes
            # retain their spelling. Other whitespace remains a word boundary.
            words = [word for word in re.split(r"[^\S ]+", name.replace("\\", "/")) if word]
            if not words:
                raise ValueError("empty Clang dependency spelling")
            for word in words:
                if not remaining[word]:
                    raise ValueError("header report disagrees with dependency rule")
                remaining[word] -= 1
        return list(dict.fromkeys(Path(name).absolute() for name in [*names, *remaining.elements()]))

    def prepare(
        self, commands: list[tuple[list[str], Path]], jobs: int, *, capture: bool = False
    ) -> list[_CacheProbe | None]:
        records = self._receipts.read(commands, jobs, capture=capture)
        probes = []
        for (command, _), record in zip(commands, records, strict=True):
            if record is None:
                probes.append(None)
                continue
            if record["content"] is None:
                probes.append(_CacheProbe(reason="receipt-miss"))
                continue
            manifest = {
                "schema": self.SCHEMA,
                "target": self._target,
                "driver": command[0],
                "arguments": self._receipts._arguments(command),
                "cwd": str(Path.cwd()),
                "preprocessing_receipt": record["identity"],
                "observed_inputs": record["content"],
            }
            key = hashlib.sha256(self._encoded(manifest)).hexdigest()
            probes.append(_CacheProbe(key=key, reason="validated", manifest=manifest, receipt_hit=record["cache_hit"]))
        return probes

    def probe(self, command: list[str], source: Path) -> _CacheProbe:
        started = time.perf_counter()
        prepared = self.prepare([(command, source)], 1, capture=True)[0]
        if prepared is not None:
            prepared.scan_s = time.perf_counter() - started
            self._manifests[prepared.key] = prepared.manifest
            return prepared
        return self._ordinary_probe(command, source)

    def _ordinary_probe(self, command: list[str], source: Path) -> _CacheProbe:
        result = _CacheProbe()
        try:
            arguments = command[1:].copy()
            output_index = arguments.index("-o")
            del arguments[output_index : output_index + 2]
            arguments.remove("-c")
            # Module/PCH side inputs need their own compiler-specific validation.
            # Do not silently apply the textual dependency contract to them.
            if any(arg.startswith(("@", "-fmodule", "-include-pch", "-include-pth")) for arg in arguments):
                result.reason = "unsupported-input"
                return result
            tool = Path(command[0])
            version = self._runner([str(tool), "--version"], capture_output=True, text=True, check=False, shell=False)
            if version.returncode:
                result.reason = "compiler-identity-unavailable"
                return result
            with tempfile.TemporaryDirectory(prefix=".scan-", dir=self.directory) as temporary:
                preprocessed = Path(temporary) / "source.i"
                depfile = Path(temporary) / "source.d"
                headers = Path(temporary) / "headers.txt"
                # This spelling contract is for the POSIX Clang driver. Other
                # providers retain their own Make dependency path.
                clang_headers = os.name != "nt" and "clang" in version.stdout.lower()
                header_arguments = (
                    ["-Xclang", "-header-include-file", "-Xclang", str(headers), "-Xclang", "-fshow-skipped-includes"]
                    if clang_headers
                    else []
                )
                started = time.perf_counter()
                scanned = self._runner(
                    [
                        str(tool),
                        *arguments,
                        "-E",
                        "-MD",
                        "-MF",
                        str(depfile),
                        "-MT",
                        "btrc-object",
                        *header_arguments,
                        "-o",
                        str(preprocessed),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    shell=False,
                )
                result.scan_s = time.perf_counter() - started
                if scanned.returncode:
                    result.reason = "dependency-scan-failed"
                    return result
                dependency_text = depfile.read_text(encoding="utf-8", errors="surrogateescape")
                dependencies = (
                    self._clang_dependencies(
                        dependency_text, headers.read_text(encoding="utf-8", errors="surrogateescape"), source
                    )
                    if clang_headers
                    else self._dependencies(dependency_text)
                )
                if source.absolute() not in dependencies:
                    result.reason = "invalid-dependencies"
                    return result
                if any(Path(f"{path}.gch").exists() for path in dependencies):
                    result.reason = "unsupported-input"
                    return result
                manifest = {
                    "schema": self.SCHEMA,
                    "target": self._target,
                    "driver": str(tool),
                    "compiler": {
                        "path": str(tool.resolve()),
                        "sha256": self._file_digest(tool),
                        "version": version.stdout,
                    },
                    "arguments": arguments,
                    "cwd": str(Path.cwd()),
                    # Compiler wrappers can observe environment beyond CPATH and
                    # SDKROOT. Hash it conservatively without persisting secrets.
                    "environment": hashlib.sha256(self._encoded(dict(os.environ))).hexdigest(),
                    "preprocessed": self._file_digest(preprocessed),
                    "dependencies": [{"path": str(path), "sha256": self._file_digest(path)} for path in dependencies],
                }
            key = hashlib.sha256(self._encoded(manifest)).hexdigest()
            self._manifests[key] = manifest
            result.key = key
            result.reason = "validated"
        except (OSError, ValueError):
            pass
        return result

    def restore(self, key: str, object_path: Path) -> str:
        cached = self.directory / f"{key}.o"
        try:
            metadata = self.directory / f"{key}.json"
            if metadata.stat().st_size > MAX_PLAN_BYTES:
                return "invalid-manifest"
            record = json.loads(metadata.read_bytes())
            if not isinstance(record, dict) or record.get("inputs") != self._manifests[key]:
                return "invalid-manifest"
            shutil.copyfile(cached, object_path)
            if self._file_digest(object_path) != record.get("object-sha256"):
                return "object-checksum-mismatch"
            os.utime(cached)
            os.utime(metadata)
        except FileNotFoundError:
            return "missing-entry"
        except OSError:
            return "unreadable-entry"
        except (ValueError, RecursionError):
            return "invalid-manifest"
        return "hit"

    def store(self, key: str, object_path: Path) -> bool:
        try:
            # Unique staging names work for threads as well as processes. Publish
            # metadata last; a racing or interrupted pair only causes a miss.
            with tempfile.TemporaryDirectory(prefix=".publish-", dir=self.directory) as temporary:
                staged = Path(temporary) / "object.o"
                metadata = Path(temporary) / "object.json"
                shutil.copyfile(object_path, staged)
                metadata.write_bytes(
                    self._encoded({"inputs": self._manifests[key], "object-sha256": self._file_digest(staged)})
                )
                os.replace(staged, self.directory / f"{key}.o")
                os.replace(metadata, self.directory / f"{key}.json")
        except OSError:
            return False
        return True

    def prune(self) -> None:
        cutoff = time.time() - self.KEEP_SECONDS
        try:
            for entry in os.scandir(self.directory):
                if entry.name == "links" and entry.is_dir(follow_symlinks=False):
                    with os.scandir(entry.path) as receipts:
                        for receipt in receipts:
                            if (
                                receipt.name.startswith("link-v1-")
                                and receipt.name.endswith(".json")
                                and receipt.stat(follow_symlinks=False).st_mtime < cutoff
                            ):
                                Path(receipt.path).unlink(missing_ok=True)
                elif entry.name.endswith((".o", ".json")) and entry.stat().st_mtime < cutoff:
                    Path(entry.path).unlink(missing_ok=True)
        except OSError:
            pass


def main(argv: Sequence[str] | None = None, *, process_workers: bool = False) -> int:
    parser = argparse.ArgumentParser(prog="btrc-native-plan")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--generated-c", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--cxx", default="c++")
    parser.add_argument("--pkg-config", default="pkg-config")
    parser.add_argument("--report-json", type=Path, help="write successful build timings and operation counts")
    parser.add_argument("--jobs", type=int, default=None, help="parallel translation-unit builds (default: CPU count)")
    parser.add_argument("--debug-info", action="store_true", help="compile with -g so binaries carry source locations")
    parser.add_argument(
        "--object-cache",
        type=Path,
        default=None,
        help="reuse objects of unchanged translation units from this directory",
    )
    parser.add_argument(
        "--optimization",
        type=int,
        choices=range(4),
        default=2,
        help="native optimization level (default: 2; use 0 for unoptimized debugging)",
    )
    arguments = parser.parse_args(argv)
    try:
        NativePlanBuilder(process_workers=process_workers).build(
            plan_path=arguments.plan,
            generated_c=arguments.generated_c,
            output=arguments.output,
            cc=arguments.cc,
            cxx=arguments.cxx,
            pkg_config=arguments.pkg_config,
            optimization=arguments.optimization,
            jobs=arguments.jobs,
            debug_info=arguments.debug_info,
            object_cache=arguments.object_cache,
            report_path=arguments.report_json,
        )
    except (NativePlanError, OSError) as error:
        sys.stderr.write(f"btrc-native-plan: error: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(process_workers=True))
