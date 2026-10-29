"""Inventory and check every applicable stdlib source with full body diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

from src.compiler.python.abi.generated import TARGET_ROWS
from src.compiler.python.application.compiler import Compiler
from src.compiler.python.application.pipeline import CompilationPipeline
from src.compiler.python.application.results import CompilerOptions
from src.compiler.python.frontend.imports import ImportResolver
from src.compiler.python.frontend.packages import (
    PackageImportPolicy,
    PackageManifestReader,
    PackageManifestValidator,
    PackageTarget,
    ResolvedPackages,
    TargetSelector,
)
from src.compiler.python.frontend.sources import (
    ConditionalEnvironment,
    SourceConditionals,
    SourceDirectiveScanner,
    StdlibRepository,
)
from src.compiler.python.frontend.stage import FrontendStage
from src.compiler.python.syntax.ast.generated import RelativePath
from tools.native_plan import TargetToolchain

REPO = Path(__file__).resolve().parents[2]
STDLIB = REPO / "src/stdlib"


class StdlibInventory:
    """All source files, including private providers, and their target dependencies."""

    def __init__(self, root: Path = STDLIB, *, runtime_root: Path | None = None) -> None:
        self.root = root.resolve()
        self.runtime_root = (runtime_root if runtime_root is not None else REPO / "src/runtime/c").resolve()
        self.modules = tuple(sorted(self.root.rglob("*.btrc")))
        if not self.modules:
            raise ValueError(f"no stdlib modules in {self.root}")
        self.sha256 = self.fingerprint(self.root, self.runtime_root)
        self.constraints: dict[Path, list[tuple[str, tuple[TargetSelector, ...]]]] = defaultdict(list)
        reader = PackageManifestReader()
        validator = PackageManifestValidator()
        for path in sorted(self.root.rglob("btrc.toml")):
            manifest = reader.read(str(path))
            package = validator.validate_identity(manifest, str(path))
            groups: dict[tuple[Path, str], list[TargetSelector]] = defaultdict(list)
            for provider in validator.providers(manifest, str(path)):
                groups[Path(provider.module), "provider selection"].append(provider.selector)
                groups[Path(provider.implementation), "provider implementation"].append(provider.selector)
            for binding in validator.bindings(manifest, str(path.parent), package, str(path)):
                groups[Path(binding.module), "native bindings"].append(binding.selector)
            for (module, kind), selectors in groups.items():
                self.constraints[module.resolve()].append((kind, tuple(selectors)))
        self.operating_systems = frozenset(row.operating_system for row in TARGET_ROWS)
        self.resolver = ImportResolver(StdlibRepository(directory=str(self.root)))
        self.scanner = SourceDirectiveScanner()
        self._dependencies: dict[tuple[str, Path], tuple[Path, ...]] = {}

    @staticmethod
    def fingerprint(root: Path, runtime_root: Path) -> str:
        """Bind reports to every library input, including transitive native headers.

        Headers need not have an extension or appear directly in a manifest.
        Hash the library and its shared runtime snapshot rather than guessing
        the include graph. Preserve their sibling layout in disposable checks.
        """
        digest = hashlib.sha256()
        for label, directory in (("stdlib", root), ("runtime/c", runtime_root)):
            if not directory.is_dir():
                raise ValueError(f"missing qualification input directory: {directory}")
            for source in sorted(path for path in directory.rglob("*") if path.is_file()):
                name = f"{label}/{source.relative_to(directory).as_posix()}".encode()
                for value in (name, source.read_bytes()):
                    digest.update(len(value).to_bytes(8, "big"))
                    digest.update(value)
        return digest.hexdigest()

    def restriction(self, module: Path, target: PackageTarget) -> str | None:
        relative = module.relative_to(self.root)
        for segment in relative.parts[:-1]:
            if segment.lower() in self.operating_systems and segment.lower() != target.operating_system:
                return f"{relative.as_posix()} belongs to {segment.lower()}"
        for kind, selectors in self.constraints.get(module, ()):
            if not any(selector.selected_for(target) for selector in selectors):
                return f"{relative.as_posix()} has no {kind} for {target.label}"
        return None

    def dependencies(self, module: Path, target: PackageTarget) -> tuple[Path, ...]:
        key = target.label, module
        if key not in self._dependencies:
            conditioned = SourceConditionals(ConditionalEnvironment(target)).condition(module.read_text(), str(module))
            paths = list(PackageImportPolicy(target).provider_for(str(module)))
            for directive in self.scanner.scan(conditioned.text):
                spec = RelativePath(path=directive.payload) if directive.kind == "btrc_include" else directive.payload
                paths.extend(self.resolver.import_paths(spec, str(module.parent), ResolvedPackages.empty(target)))
            dependencies = tuple(sorted({Path(path).resolve() for path in paths if path.endswith(".btrc")}))
            for dependency in dependencies:
                if not dependency.is_relative_to(self.root):
                    raise ValueError(f"stdlib source {module} imports outside the inventory: {dependency}")
            self._dependencies[key] = dependencies
        return self._dependencies[key]

    def _walk(self, module: Path, target: PackageTarget) -> Iterator[Path]:
        pending = [module]
        visited: set[Path] = set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            yield current
            pending.extend(reversed(self.dependencies(current, target)))

    def exclusion(self, module: Path, target: PackageTarget) -> str | None:
        for current in self._walk(module, target):
            if reason := self.restriction(current, target):
                return reason
        return None

    def requires_native(self, module: Path, target: PackageTarget) -> bool:
        return any(
            kind == "native bindings"
            for current in self._walk(module, target)
            for kind, _ in self.constraints.get(current, ())
        )

    def rows(self, target: PackageTarget) -> list[dict]:
        return [
            {
                "module": module.relative_to(self.root).as_posix(),
                "sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
                "excluded": self.exclusion(module, target),
            }
            for module in self.modules
        ]


class StdlibCheck:
    """Run each source in a fresh compiler process against a disposable library copy."""

    def __init__(
        self,
        inventory: StdlibInventory,
        target: PackageTarget,
        frontend: str,
        btrcc: Path | None,
        native_sdk: Path | None = None,
    ) -> None:
        if frontend == "selfhost" and (btrcc is None or not btrcc.is_file()):
            raise ValueError("selfhost checks require --btrcc pointing to a built compiler")
        self.inventory = inventory
        self.target = target
        self.frontend = frontend
        self.btrcc = btrcc.resolve() if btrcc is not None else None
        self.native_sdk = native_sdk.resolve(strict=True) if native_sdk is not None else None
        if self.native_sdk is not None:
            for directory in ("include", "lib/pkgconfig"):
                if not (self.native_sdk / directory).is_dir():
                    raise ValueError(f"native SDK is missing {directory}: {self.native_sdk}")

    def environment(self) -> dict[str, str]:
        environment = dict(os.environ)
        if self.native_sdk is not None:
            for key, directory in (("CPATH", "include"), ("PKG_CONFIG_PATH", "lib/pkgconfig")):
                environment[key] = os.pathsep.join(
                    filter(None, (str(self.native_sdk / directory), environment.get(key)))
                )
            # Nix wrappers must not source a container startup file that replaces
            # the already composed target package paths.
            environment.pop("BASH_ENV", None)
        return environment

    @staticmethod
    def compile_python(stdlib: str, source: str, target: str) -> int:
        compiler = Compiler(CompilationPipeline(frontend=FrontendStage(StdlibRepository(directory=stdlib))))
        result = compiler.compile(
            Path(source).read_text(),
            source,
            CompilerOptions(
                target=target,
                stdlib_strict=True,
                strict_imports=True,
                use_cache=False,
                use_ast_cache=False,
                map_stdlib_positions=True,
            ),
        )
        failures = result.failure.diagnostics if result.failure is not None else ()
        for diagnostic in (*result.diagnostics, *failures):
            path, line = result.map_diagnostic(diagnostic) or (diagnostic.file or source, diagnostic.line)
            print(
                f"{diagnostic.severity}: {path}:{line}:{diagnostic.col}: {diagnostic.message}",
                file=sys.stderr,
            )
        if result.failure is not None:
            print(f"error: {result.failure.message}", file=sys.stderr)
        return 0 if result.successful and not result.diagnostics else 1

    def run(self, output: Path, *, timeout: int = 600, modules: tuple[str, ...] = ()) -> dict:
        output = output.resolve()
        output.mkdir(parents=True, exist_ok=True)
        rows = self.inventory.rows(self.target)
        unknown = set(modules) - {row["module"] for row in rows}
        if unknown:
            raise ValueError(f"unknown stdlib modules: {sorted(unknown)}")
        report = {
            "schema": 1,
            "inventory_sha256": self.inventory.sha256,
            "target": self.target.label,
            "frontend": self.frontend,
            "strict_imports": True,
            "stdlib_strict": True,
            "complete": False,
            "partial": bool(modules),
            "modules": rows,
        }
        if self.btrcc is not None:
            report["compiler_sha256"] = hashlib.sha256(self.btrcc.read_bytes()).hexdigest()
        report_path = output / "report.json"
        environment = self.environment()
        if any(
            row["excluded"] is None
            and (not modules or row["module"] in modules)
            and self.inventory.requires_native(self.inventory.root / row["module"], self.target)
            for row in rows
        ):
            environment.update(
                {
                    "BTRC_NATIVE_TARGET": self.target.row.triple,
                    "BTRC_NATIVE_SYSROOT": str(TargetToolchain(self.target.row).sysroot()),
                }
            )
        with tempfile.TemporaryDirectory(prefix="sources-", dir=output) as directory:
            data = Path(directory)
            shutil.copytree(self.inventory.root, data / "stdlib")
            shutil.copytree(self.inventory.runtime_root, data / "runtime/c")
            if self.inventory.fingerprint(data / "stdlib", data / "runtime/c") != self.inventory.sha256:
                raise ValueError("stdlib inputs changed while preparing qualification")
            shutil.copytree(REPO / "src/language", data / "language")
            for row in rows:
                module = row["module"]
                if row["excluded"] is not None:
                    row["status"] = "not-applicable"
                elif modules and module not in modules:
                    row["status"] = "not-selected"
                else:
                    source = data / "stdlib" / module
                    if hashlib.sha256(source.read_bytes()).hexdigest() != row["sha256"]:
                        raise ValueError(f"stdlib source changed while preparing qualification: {module}")
                    probe = source.with_name("StdlibQualificationProbe.btrc")
                    if probe.exists():
                        raise ValueError(f"qualification probe would replace an existing module: {probe}")
                    probe.write_text(f"import ./{source.name};\nint main() {{ return 0; }}\n")
                    row["status"] = "running"
                    report_path.write_text(json.dumps(report, indent=2) + "\n")
                    if self.frontend == "python":
                        command = [
                            sys.executable,
                            "-c",
                            "from tools.qualification.stdlib import StdlibCheck; import sys; "
                            "sys.exit(StdlibCheck.compile_python(*sys.argv[1:]))",
                            str(data / "stdlib"),
                            str(probe),
                            self.target.label,
                        ]
                    else:
                        command = [
                            str(self.btrcc),
                            str(probe),
                            "--stdlib-strict",
                            "--strict-imports",
                            "--no-cache",
                            "--target",
                            self.target.label,
                            "-o",
                            str(data / "module.c"),
                        ]
                    try:
                        result = subprocess.run(
                            command,
                            cwd=REPO,
                            env={**environment, "BTRC_HOME": str(data)},
                            capture_output=True,
                            text=True,
                            timeout=timeout,
                        )
                        row["status"] = (
                            "passed" if result.returncode == 0 and "warning:" not in result.stderr else "failed"
                        )
                        row["returncode"] = result.returncode
                        diagnostic = result.stderr
                    except subprocess.TimeoutExpired as error:
                        row["status"] = "failed"
                        diagnostic = error.stderr or b""
                        if isinstance(diagnostic, bytes):
                            diagnostic = diagnostic.decode(errors="replace")
                        diagnostic += f"\nCompiler exceeded {timeout} seconds.\n"
                    finally:
                        probe.unlink()
                    log = output / "logs" / Path(module).with_suffix(".stderr")
                    log.parent.mkdir(parents=True, exist_ok=True)
                    log.write_text(diagnostic)
                    row["log"] = log.relative_to(output).as_posix()
                    print(f"{self.frontend} {self.target.label} {module}: {row['status']}", flush=True)
                report_path.write_text(json.dumps(report, indent=2) + "\n")
        report["complete"] = True
        report_path.write_text(json.dumps(report, indent=2) + "\n")
        return report


class StdlibCoverage:
    """Require complete per-target checks and both frontends for every source."""

    def __init__(self, inventory: StdlibInventory) -> None:
        self.inventory = inventory

    def validate(self, reports: list[dict], targets: tuple[PackageTarget, ...]) -> dict:
        expected = {(frontend, target.label) for frontend in ("python", "selfhost") for target in targets}
        received: set[tuple[str, str]] = set()
        covered: dict[str, set[str]] = {frontend: set() for frontend in ("python", "selfhost")}
        for report in reports:
            identity = report.get("frontend"), report.get("target")
            if identity not in expected or identity in received:
                raise ValueError(f"unexpected or duplicate stdlib report: {identity}")
            received.add(identity)
            if (
                report.get("schema") != 1
                or report.get("inventory_sha256") != self.inventory.sha256
                or report.get("complete") is not True
                or report.get("partial") is not False
                or report.get("stdlib_strict") is not True
                or report.get("strict_imports") is not True
            ):
                raise ValueError(f"incomplete, partial or stale stdlib report: {identity}")
            frontend, target = identity
            expected_rows = {row["module"]: row for row in self.inventory.rows(PackageTarget.parse(target))}
            rows = report.get("modules", [])
            if len(rows) != len(expected_rows) or {row.get("module") for row in rows} != set(expected_rows):
                raise ValueError(f"stdlib report omits or duplicates modules: {identity}")
            for row in rows:
                module = row["module"]
                expected_row = expected_rows[module]
                if row.get("sha256") != expected_row["sha256"] or row.get("excluded") != expected_row["excluded"]:
                    raise ValueError(f"stdlib source or applicability changed: {identity} {module}")
                if expected_row["excluded"] is None:
                    if row.get("status") != "passed":
                        raise ValueError(f"stdlib module did not pass: {identity} {module}")
                    covered[frontend].add(module)
                elif row.get("status") != "not-applicable":
                    raise ValueError(f"stdlib exclusion has an inconsistent status: {identity} {module}")
        if missing := expected - received:
            raise ValueError(f"missing stdlib reports: {sorted(missing)}")
        all_modules = {module.relative_to(self.inventory.root).as_posix() for module in self.inventory.modules}
        for frontend, modules in covered.items():
            if missing := all_modules - modules:
                raise ValueError(f"stdlib modules have no {frontend} coverage: {sorted(missing)}")
        return {
            "modules": len(all_modules),
            "reports": len(received),
            "targets": sorted(target.label for target in targets),
        }


class StdlibCommand:
    def run(self, arguments: list[str] | None = None) -> int:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("command", choices=("inventory", "check", "coverage"))
        parser.add_argument("--stdlib", type=Path, default=STDLIB)
        parser.add_argument("--target", action="append", required=True)
        parser.add_argument("--report", type=Path, action="append", default=[])
        parser.add_argument("--frontend", choices=("python", "selfhost"), default="python")
        parser.add_argument("--btrcc", type=Path)
        parser.add_argument("--native-sdk", type=Path, help="target SDK with include/ and lib/pkgconfig/")
        parser.add_argument("--output", type=Path)
        parser.add_argument("--timeout", type=int, default=600)
        parser.add_argument("--module", action="append", default=[])
        args = parser.parse_args(arguments)
        inventory = StdlibInventory(args.stdlib)
        targets = tuple(PackageTarget.parse(target) for target in args.target)
        if args.command == "coverage":
            result = StdlibCoverage(inventory).validate([json.loads(path.read_text()) for path in args.report], targets)
            print(json.dumps(result, indent=2))
            return 0
        if len(targets) != 1:
            parser.error("inventory and check require exactly one --target")
        target = targets[0]
        if args.command == "inventory":
            print(json.dumps(inventory.rows(target), indent=2))
            return 0
        if args.output is None or args.timeout <= 0:
            parser.error("check requires --output and a positive --timeout")
        report = StdlibCheck(inventory, target, args.frontend, args.btrcc, args.native_sdk).run(
            args.output,
            timeout=args.timeout,
            modules=tuple(args.module),
        )
        return int(any(row["status"] == "failed" for row in report["modules"]))


if __name__ == "__main__":
    raise SystemExit(StdlibCommand().run())
