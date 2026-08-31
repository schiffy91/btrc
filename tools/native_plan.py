"""Validate and realize one compiler-emitted native link plan.

The adapter is intentionally narrower than a general build-command surface:
it accepts no free-form compiler or linker flags, never invokes a shell, and
compiles only the generated C file plus units enumerated by the canonical plan.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

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


class NativePlanReader:
    """Own bounded canonical JSON reads and closed schema validation."""

    def read(self, path: Path) -> NativeBuildPlan:
        encoded = self._read_regular(path)
        try:
            payload = json.loads(
                encoded.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise NativePlanError(f"cannot parse native link plan {path}: {error}") from error
        root = _exact_mapping(payload, ROOT_FIELDS, "native link plan")
        canonical = json.dumps(root, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        if encoded != canonical.encode("utf-8"):
            raise NativePlanError("native link plan must use canonical schema-1 JSON")
        return self._validate(root)

    def _read_regular(self, path: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
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
        if type(root["schema"]) is not int or root["schema"] != 1:
            raise NativePlanError("native link plan schema must be integer 1")
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
        linker_language = _text(root["linker-language"], "native link plan linker-language")
        expected_linker = "c++" if any(unit.language in {"c++", "objective-c++"} for unit in units) else "c"
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
        )

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


class NativePlanBuilder:
    """Compile and link exactly one validated plan without a command shell."""

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        reader: NativePlanReader | None = None,
    ) -> None:
        self._runner = runner
        self._reader = reader or NativePlanReader()

    def build(
        self,
        *,
        plan_path: Path,
        generated_c: Path,
        output: Path,
        cc: str = "cc",
        cxx: str = "c++",
        pkg_config: str = "pkg-config",
    ) -> None:
        plan = self._reader.read(plan_path)
        generated = _regular_file(str(generated_c.absolute()), "generated C input")
        if not output.is_absolute():
            output = output.absolute()
        parent = _real_directory(str(output.parent), "native output directory")
        inputs = {plan_path.absolute(), generated, *(unit.path for unit in plan.units)}
        if output in inputs:
            raise NativePlanError("native output must differ from its plan and source inputs")
        tools = {"cc": self._tool(cc, "C compiler"), "cxx": self._tool(cxx, "C++ compiler")}
        package_compile, package_link = self._pkg_config(plan, pkg_config)
        includes = [f"-I{path}" for path in plan.include_directories]
        defines = [f"-D{name}={value}" if value else f"-D{name}" for name, value in plan.defines]
        strict = ["-pedantic-errors", "-Wall", "-Wextra", "-Werror"]
        with tempfile.TemporaryDirectory(prefix=".btrc-native-", dir=parent) as temporary_text:
            temporary = Path(temporary_text)
            objects: list[Path] = []
            generated_object = temporary / "generated.o"
            self._run(
                [
                    tools["cc"],
                    "-x",
                    "c",
                    "-std=c11",
                    *strict,
                    *includes,
                    *defines,
                    *package_compile,
                    "-c",
                    str(generated),
                    "-o",
                    str(generated_object),
                ]
            )
            objects.append(generated_object)
            for index, unit in enumerate(plan.units):
                object_path = temporary / f"native-{index}.o"
                self._run(
                    [
                        tools[SOURCE_DRIVERS[unit.language]],
                        *SOURCE_LANGUAGE_ARGUMENTS[unit.language],
                        f"-std={unit.standard}",
                        *strict,
                        *includes,
                        *defines,
                        *package_compile,
                        "-c",
                        str(unit.path),
                        "-o",
                        str(object_path),
                    ]
                )
                objects.append(object_path)
            staged = temporary / output.name
            runtime_libraries = ["-lm"]
            if plan.operating_system != "windows":
                runtime_libraries.append("-pthread")
            framework_flags = [part for name in plan.frameworks for part in ("-framework", name)]
            self._run(
                [
                    tools["cxx" if plan.linker_language == "c++" else "cc"],
                    *(str(path) for path in objects),
                    *package_link,
                    *framework_flags,
                    *runtime_libraries,
                    "-o",
                    str(staged),
                ]
            )
            os.replace(staged, output)

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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="btrc-native-plan")
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--generated-c", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--cxx", default="c++")
    parser.add_argument("--pkg-config", default="pkg-config")
    arguments = parser.parse_args(argv)
    try:
        NativePlanBuilder().build(
            plan_path=arguments.plan,
            generated_c=arguments.generated_c,
            output=arguments.output,
            cc=arguments.cc,
            cxx=arguments.cxx,
            pkg_config=arguments.pkg_config,
        )
    except (NativePlanError, OSError) as error:
        sys.stderr.write(f"btrc-native-plan: error: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
