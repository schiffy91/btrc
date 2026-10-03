"""Measure complete strict native-plan builds of one program from both BTRC frontends.

    python3 -m tools.perf src/compiler/btrc/BtrccMain.btrc --json build/perf/self.json

BTRSmith's bucket-1 budgets (cold, body, instance and interface edits, no-op,
touch, batch, release, memory, worker sweeps, and the self-compile and corpus
scaling workloads, on either frontend) belong to tools/budget_bench.py, which
samples and verifies them as PLAN.md's acceptance tables require. This tool
profiles one program's cold build: phase attribution, C statistics and
input provenance.

Use the program's development environment for SDKs and packages. Every sample
transpiles into split units and builds all emitted/native/adapter units, then
links using the production native-plan adapter. Dev uses source mapping and
-O0 -g; release uses -O2. Warm-native samples validate the object cache and
relink the existing plan; they are not whole-product no-op measurements.
Raw logs, operation reports and binaries remain in the reported run directory.

    python3 -m tools.perf --cprofile --frontend reference --workspace <BTRSmith> --json build/perf/attribution.json

attributes the reference compiler's time instead (ReferenceAttribution, PLAN.md
Stage 6 `perf-ref-attribution`). On a copy of the workspace, or budget_bench's
--stand-in, it times cold transpiles and budget_bench's EDIT_FIXTURES edits
twice each: once plain, for the uninstrumented `btrcpy timing:` phases, and
once under cProfile. Each profile is rolled up by owner (frontend, native
plan, analyzer, lowering, module units, optimizer, emitter, artifacts, driver,
plus import-time startup), by module and by owner class, reconciled with the
phases, and reported as the fraction of the profiled wall time it attributes.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import pstats
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.compiler.python.frontend.packages import PackageTarget
from tools.budget_bench import (
    CC,
    CXX,
    EDIT_FIXTURES,
    ENTRY,
    Distribution,
    Fixture,
    Flavor,
    HostSummary,
    HostTarget,
    ProductPaths,
    StandInWorkspace,
    State,
)
from tools.native_plan import NativePlanError, NativePlanReader

REPO = Path(__file__).resolve().parents[1]
PHASES = ("analyze", "lower", "optimize", "emit")
FRONTEND_PHASES = frozenset(
    {
        "grammar",
        "tables",
        "packages",
        "resolve",
        "native",
        "lex",
        "parse",
        "visibility",
        "visibility-index",
        "catalog",
        "stdlib-manifests",
        "stdlib-finish",
        "stdlib-restrict",
        "resolve_includes",
        "stdlib_include",
        "stdlib_archive",
    }
)
FUNCTION_DEFINITION = re.compile(r"\) \{$")
STRUCT_DEFINITION = re.compile(r"^struct [A-Za-z_0-9]+ \{$")
VECTOR_INSTANCE = re.compile(r"^typedef struct (btrc_Vector_[A-Za-z0-9_]+) ")


@dataclass
class Measurement:
    wall_s: float
    cpu_s: float
    max_rss_kb: int
    returncode: int

    @classmethod
    def from_usage(cls, usage: dict[str, float], platform: str) -> Measurement:
        # Darwin reports bytes; Linux reports KiB. Keep the historical JSON
        # field name but give it the same KiB unit on both hosts.
        rss = usage["max_rss"] / 1024 if platform == "darwin" else usage["max_rss"]
        return cls(usage["wall_s"], usage["cpu_s"], int(rss), int(usage["returncode"]))

    @classmethod
    def run(cls, command: list[str], env: dict[str, str], cwd: Path, stdout: Path, stderr: Path) -> Measurement:
        """Run `command` in a fresh Python process that reports its children's rusage."""

        runner = (
            "import json, resource, subprocess, sys, time\n"
            "command = json.loads(sys.argv[1]); out, err = sys.argv[2], sys.argv[3]\n"
            "started = time.perf_counter()\n"
            "with open(out, 'w') as o, open(err, 'w') as e:\n"
            "    code = subprocess.run(command, stdout=o, stderr=e).returncode\n"
            "wall = time.perf_counter() - started\n"
            "usage = resource.getrusage(resource.RUSAGE_CHILDREN)\n"
            "print(json.dumps({'wall_s': wall, 'cpu_s': usage.ru_utime + usage.ru_stime, "
            "'max_rss': usage.ru_maxrss, 'returncode': code}))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", runner, json.dumps(command), str(stdout), str(stderr)],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return cls.from_usage(json.loads(completed.stdout), sys.platform)


@dataclass
class CompilerRun:
    frontend: str
    wall_s: float
    cpu_s: float
    max_rss_kb: int
    phases_s: dict[str, float]
    generated_c: str
    plan: str
    mode: str = "release"
    sample: int = 1
    command: list[str] = field(default_factory=list)
    returncode: int = 0

    def phase_totals(self) -> dict[str, float]:
        totals = dict.fromkeys(("frontend", *PHASES, "other"), 0.0)
        for name, seconds in self.phases_s.items():
            if name in PHASES:
                totals[name] += seconds
            elif self.frontend == "btrcc" and name.startswith(("a-", "l-", "o-")):
                # BtrccPhaseTimer.mark restarts its stopwatch. These marks
                # partition the stage; the final stage mark is the remainder.
                totals[{"a": "analyze", "l": "lower", "o": "optimize"}[name[0]]] += seconds
            elif name == "setjmp-analysis":
                totals["optimize"] += seconds
            elif name in FRONTEND_PHASES or (self.frontend == "btrcc" and name.startswith("r-")):
                totals["frontend"] += seconds
            else:
                totals["other"] += seconds
        totals["unattributed"] = self.wall_s - sum(totals.values())
        return totals


@dataclass
class CStats:
    lines: int
    bytes: int
    functions: int
    structs: int
    vector_instances: int
    line_directives: int

    @classmethod
    def read(cls, path: Path) -> CStats:
        """Count one emitted C unit's lines, definitions and `#line` directives."""

        lines = functions = structs = directives = 0
        vectors: set[str] = set()
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                lines += 1
                if FUNCTION_DEFINITION.search(line):
                    functions += 1
                if STRUCT_DEFINITION.match(line):
                    structs += 1
                if line.startswith("#line"):
                    directives += 1
                match = VECTOR_INSTANCE.match(line)
                if match:
                    vectors.add(match.group(1))
        return cls(lines, path.stat().st_size, functions, structs, len(vectors), directives)


@dataclass
class NativeRun:
    frontend: str
    mode: str
    sample: int
    scenario: str
    command: list[str]
    measurement: Measurement
    executable: str
    operations: dict[str, object]
    end_to_end_s: float | None = None


@dataclass
class Report:
    program: str
    target: str
    schema: int = 2
    compilers: list[CompilerRun] = field(default_factory=list)
    c_stats: dict[str, CStats] = field(default_factory=dict)
    native_builds: list[NativeRun] = field(default_factory=list)
    provenance: dict[str, object] = field(default_factory=dict)
    failure: str | None = None


# One phase mark: everything before the last `=NNNus`. A mark may carry
# counters in parentheses, `a-records-stored(replayed=3,journaled=1)=12us`,
# which are dropped from the phase name so runs with different counts sum
# into one phase.
PHASE_MARK = re.compile(r"^(?P<name>[^()=]+)(?:\([^()]*\))?=(?P<micros>\d+)us$")
WORKER_TIMING_LINE = re.compile(r"^(?:btrcpy|btrcc) worker timing: worker=(\d+) (.*)$")
MICROSECONDS = re.compile(r"^(\d+)us$")
WORKER_USAGE = re.compile(r"^user:(\d+)us,sys:(\d+)us,maxrss:(\d+)KiB$")


class TimingReport:
    """The `BTRC_TIMING=1` report both compilers print on standard error.

    Every reader of those lines -- this tool, `tools.bench`, the module-unit
    tests -- goes through this owner, so a mark is parsed one way everywhere.
    """

    COMPILERS = ("btrcpy", "btrcc")

    @classmethod
    def phase_times(
        cls, stderr: str, *, compilers: tuple[str, ...] = COMPILERS, per_second: int = 1
    ) -> dict[str, float]:
        """Both compilers print `<name> timing: phase=NNNus ...`; sum per phase.

        Times are in seconds, or in `per_second` parts of one (``1000`` gives
        milliseconds), and only `compilers`' owner lines are read. Tokens that are not a phase
        mark -- counters such as `module-units=lowered:3,reused:2` or
        `setjmp-analyses=2/3,rounds=1` -- are skipped rather than parsed.
        """

        prefixes = tuple(f"{compiler} timing: " for compiler in compilers)
        phases: dict[str, float] = {}
        for line in stderr.splitlines():
            line = line.strip()
            prefix = next((prefix for prefix in prefixes if line.startswith(prefix)), None)
            if prefix is None:
                continue
            for item in line[len(prefix) :].split():
                if mark := PHASE_MARK.match(item):
                    name = mark.group("name")
                    phases[name] = phases.get(name, 0.0) + int(mark.group("micros")) / (1_000_000.0 / per_second)
        return phases

    @classmethod
    def worker_phase_times(cls, stderr: str) -> dict[int, dict[str, float]]:
        """Forked module-unit workers' reports, by worker index, in seconds.

        Each `<name> worker timing: worker=<i> ...` line sums its `phase=NNNus`
        marks per phase, and its `busy=op:NNNus,...` times as `busy:<op>`. The
        owner's line is `phase_times`'s alone, so no worker time reaches it.
        """

        workers: dict[int, dict[str, float]] = {}
        for index, fields in cls._worker_lines(stderr):
            phases = workers.setdefault(index, {})
            for item in fields:
                name, _, value = item.partition("=")
                if name == "busy":
                    for entry in value.split(","):
                        operation, _, micros = entry.partition(":")
                        if found := MICROSECONDS.match(micros):
                            key = f"busy:{operation}"
                            phases[key] = phases.get(key, 0.0) + int(found.group(1)) / 1_000_000.0
                elif found := MICROSECONDS.match(value):
                    phases[name] = phases.get(name, 0.0) + int(found.group(1)) / 1_000_000.0
        return workers

    @classmethod
    def worker_usage(cls, stderr: str) -> dict[int, dict[str, float]]:
        """Forked module-unit workers' own resource usage, by worker index.

        A worker line's `usage=user:Nus,sys:Nus,maxrss:NKiB` field, which the
        owner appends after reaping the worker, becomes `user` and `sys` in
        seconds and `maxrss_kib`. A worker the host reported no usage for is
        absent, as is every worker of a build that forked none.
        """

        workers: dict[int, dict[str, float]] = {}
        for index, fields in cls._worker_lines(stderr):
            for item in fields:
                name, _, value = item.partition("=")
                if name == "usage" and (found := WORKER_USAGE.match(value)):
                    workers[index] = {
                        "user": int(found.group(1)) / 1_000_000.0,
                        "sys": int(found.group(2)) / 1_000_000.0,
                        "maxrss_kib": float(found.group(3)),
                    }
        return workers

    @staticmethod
    def _worker_lines(stderr: str) -> list[tuple[int, list[str]]]:
        lines = []
        for line in stderr.splitlines():
            if match := WORKER_TIMING_LINE.match(line.strip()):
                lines.append((int(match.group(1)), match.group(2).split()))
        return lines


# The names docs/design/compile-performance.md documents for reading a timing report.
phase_times = TimingReport.phase_times
worker_phase_times = TimingReport.worker_phase_times
worker_usage = TimingReport.worker_usage


class Perf:
    ENVIRONMENT_INPUTS = (
        "PATH",
        "CC",
        "CXX",
        "SDKROOT",
        "MACOSX_DEPLOYMENT_TARGET",
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "OBJC_INCLUDE_PATH",
        "LIBRARY_PATH",
        "PKG_CONFIG_PATH",
        "PKG_CONFIG_LIBDIR",
        "PKG_CONFIG_SYSROOT_DIR",
        "BTRC_NATIVE_HEADER_READER",
        "BTRC_NATIVE_SYSROOT",
        "BTRC_NATIVE_TARGET",
        "BTRC_UNIT_LINES",
        "BTRC_HOME",
        "NIX_CFLAGS_COMPILE",
        "NIX_LDFLAGS",
        "SOURCE_DATE_EPOCH",
    )

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.arguments = arguments
        self.program = Path(arguments.program).resolve(strict=True)
        destination = Path(arguments.out).resolve() if arguments.out else REPO / "build/perf" / self.program.stem
        destination.mkdir(parents=True, exist_ok=True)
        self.out = Path(tempfile.mkdtemp(prefix="run-", dir=destination))
        self.env = {**os.environ, "BTRC_TIMING": "1", "BTRC_HOME": str(REPO / "src")}
        if arguments.unit_lines is not None:
            self.env["BTRC_UNIT_LINES"] = str(arguments.unit_lines)
        self.report = Report(str(self.program), arguments.target)

    @staticmethod
    def fingerprint(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    @classmethod
    def source_snapshot(
        cls, root: Path, directories: tuple[str, ...], *, exclude: tuple[Path, ...] = ()
    ) -> dict[str, object]:
        digest = hashlib.sha256()
        count = size = 0
        suffixes = {
            ".py",
            ".btrc",
            ".c",
            ".h",
            ".cpp",
            ".hpp",
            ".m",
            ".mm",
            ".toml",
            ".asdl",
            ".ebnf",
            ".json",
            ".mk",
            ".nix",
            ".lock",
        }
        excluded = {"build", "dist", ".git", ".btrc-cache", "__pycache__", "node_modules", ".venv"}
        for directory in directories:
            source = root / directory
            paths = [source] if source.is_file() else []
            if source.is_dir():
                for current, children, files in os.walk(source):
                    children[:] = [
                        name
                        for name in children
                        if name not in excluded
                        and not any((Path(current) / name).resolve().is_relative_to(output) for output in exclude)
                    ]
                    paths.extend(Path(current) / name for name in files)
            for path in sorted(paths):
                relative = path.relative_to(root)
                if (
                    (path.suffix not in suffixes and path.name != "Makefile")
                    or not path.is_file()
                    or excluded.intersection(relative.parts)
                    or any(path.resolve().is_relative_to(output) for output in exclude)
                ):
                    continue
                digest.update(str(relative).encode("utf-8", "surrogateescape") + b"\0")
                digest.update(bytes.fromhex(cls.fingerprint(path)))
                count += 1
                size += path.stat().st_size
        return {"sha256": digest.hexdigest(), "files": count, "bytes": size}

    def input_snapshot(self) -> dict[str, object]:
        product = self.repository(self.program.parent)
        package = next(
            (parent for parent in self.program.parents if (parent / "btrc.toml").is_file()), self.program.parent
        )
        roots = ("src", "packages", "make", "Makefile", "flake.nix", "flake.lock", "btrc.toml", "btrc.lock")
        exclude = (self.out, *((Path(self.arguments.json).resolve(),) if self.arguments.json else ()))
        compiler = self.repository(REPO)
        return {
            "compiler_sources": self.source_snapshot(
                REPO, ("src/compiler", "src/language", "src/runtime", "src/stdlib", "tools"), exclude=exclude
            ),
            "product_sources": self.source_snapshot(Path(product["root"]), roots, exclude=exclude)
            if product["root"]
            else None,
            "entry_package_sources": self.source_snapshot(package, (".",), exclude=exclude),
            "entry_package_root": str(package),
            "entry_sha256": self.fingerprint(self.program),
            "compiler_revision": compiler["revision"],
            "product_revision": product["revision"],
            "compiler_locks": compiler.get("locks"),
            "product_locks": product.get("locks"),
        }

    @classmethod
    def repository(cls, directory: Path) -> dict[str, object]:
        def git(*args):
            result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True)
            return result.stdout.strip() if result.returncode == 0 else None

        root_text = git("rev-parse", "--show-toplevel")
        if root_text is None:
            return {"root": None, "revision": None}
        root = Path(root_text)
        return {
            "root": str(root),
            "revision": git("rev-parse", "HEAD"),
            "status": git("status", "--porcelain"),
            "locks": {
                name: cls.fingerprint(root / name)
                for name in ("flake.lock", "btrc.lock", "btrc.toml")
                if (root / name).is_file()
            },
        }

    @classmethod
    def tool_identity(cls, tool: str, *, version: bool = True) -> dict[str, object]:
        resolved = shutil.which(tool)
        if resolved is None:
            return {"requested": tool, "available": False}
        path = Path(resolved)
        identity = {"requested": tool, "path": str(path.resolve()), "sha256": cls.fingerprint(path)}
        if version:
            result = subprocess.run([resolved, "--version"], capture_output=True, text=True)
            identity["version"] = result.stdout.strip()
            identity["version_returncode"] = result.returncode
        return identity

    def record_provenance(self) -> None:
        product = self.repository(self.program.parent)
        tools = {
            "python": self.tool_identity(sys.executable),
            "cc": self.tool_identity(self.arguments.cc),
            "cxx": self.tool_identity(self.arguments.cxx),
            "pkg-config": self.tool_identity(self.arguments.pkg_config),
        }
        if "btrcc" in self.arguments.frontends:
            tools["btrcc"] = self.tool_identity(self.arguments.btrcc, version=False)
        if self.env.get("BTRC_NATIVE_HEADER_READER"):
            tools["native-header-reader"] = self.tool_identity(self.env["BTRC_NATIVE_HEADER_READER"], version=False)
        self.report.provenance = {
            "compiler_repository": self.repository(REPO),
            "product_repository": product,
            **self.input_snapshot(),
            "tools": tools,
            "host": platform.uname()._asdict(),
            "host_summary": HostSummary.describe(),
            "cpu_count": os.cpu_count(),
            "jobs": self.arguments.jobs,
            "environment": {name: self.env[name] for name in self.ENVIRONMENT_INPUTS if name in self.env},
            "environment_sha256": hashlib.sha256(json.dumps(self.env, sort_keys=True).encode()).hexdigest(),
            "samples": self.arguments.samples,
            "warm_native_runs": self.arguments.warm_native_runs,
            "work_directory": str(self.out),
            "rss_unit": "KiB",
            "rss_scope": "normalized RUSAGE_CHILDREN.ru_maxrss; not simultaneous aggregate build RSS",
            "cache_scope": "fresh generated files and object cache per sample, then warm-native repeats; reference output cache disabled; native-header, package and OS caches uncontrolled",
            "power_and_thermal_state": "unmeasured",
            "input_stability_scope": "before/after source, package and build-file snapshots; not proof against transient edits or a complete external SDK/dependency closure",
        }

    def verify_inputs(self) -> None:
        final = self.input_snapshot()
        changed = [name for name, value in final.items() if value != self.report.provenance[name]]
        tools = self.report.provenance["tools"]
        final_tools = {name: self.tool_identity(tool["requested"], version=False) for name, tool in tools.items()}
        if any(
            final_tools[name].get(field) != tool.get(field)
            for name, tool in tools.items()
            for field in ("path", "sha256", "available")
        ):
            changed.append("tools")
        self.report.provenance["final_inputs"] = final
        self.report.provenance["final_tools"] = final_tools
        self.report.provenance["input_stability"] = {"changed": changed, "unchanged": not changed}
        if changed:
            raise NativePlanError(
                f"measurement inputs changed during the run: {', '.join(changed)}; rerun on a frozen tree"
            )

    def compiler_command(self, frontend: str, mode: str, generated: Path, plan: Path) -> list[str]:
        driver = (
            [sys.executable, "-m", "src.compiler.python.main", "--no-cache"]
            if frontend == "btrcpy"
            else [str(Path(self.arguments.btrcc).resolve())]
        )
        return [
            *driver,
            "--strict-imports",
            "--target",
            self.arguments.target,
            "--emit-link-plan",
            str(plan),
            "--emit-units",
            str(generated),
            *(["--debug"] if mode == "dev" else []),
            str(self.program),
            "-o",
            str(generated),
        ]

    def run_compiler(self, frontend: str, mode: str, sample: int, directory: Path) -> CompilerRun:
        generated = directory / "program.c"
        plan = directory / "program.link.json"
        command = self.compiler_command(frontend, mode, generated, plan)
        stdout, stderr = directory / "frontend.stdout", directory / "frontend.stderr"
        measured = Measurement.run(command, self.env, REPO, stdout, stderr)
        run = CompilerRun(
            frontend,
            measured.wall_s,
            measured.cpu_s,
            measured.max_rss_kb,
            phase_times(stderr.read_text()),
            str(generated),
            str(plan),
            mode,
            sample,
            command,
            measured.returncode,
        )
        self.report.compilers.append(run)
        if measured.returncode != 0:
            raise NativePlanError(f"{frontend}/{mode} failed ({measured.returncode}):\n{stderr.read_text()[-3000:]}")
        native = NativePlanReader().read(plan)
        for path in (generated, *native.emitted_paths):
            resolved = path.resolve()
            out = self.out.resolve()
            name = resolved.relative_to(out) if resolved.is_relative_to(out) else path
            self.report.c_stats[str(name)] = CStats.read(path)
        return run

    def run_native(self, run: CompilerRun, directory: Path, scenario: str, started: float | None) -> None:
        executable = directory / ("program.exe" if sys.platform == "win32" else "program")
        operations_path = directory / f"{scenario}.native.json"
        optimization = 0 if run.mode == "dev" else 2 if run.mode == "release" else int(run.mode[1:])
        command = [
            sys.executable,
            "-m",
            "tools.native_plan",
            "--plan",
            run.plan,
            "--generated-c",
            run.generated_c,
            "--output",
            str(executable),
            "--cc",
            self.arguments.cc,
            "--cxx",
            self.arguments.cxx,
            "--pkg-config",
            self.arguments.pkg_config,
            "--optimization",
            str(optimization),
            "--jobs",
            str(self.arguments.jobs),
            "--object-cache",
            str(directory / "objects"),
            "--report-json",
            str(operations_path),
            *(["--debug-info"] if run.mode == "dev" else []),
        ]
        stdout, stderr = directory / f"{scenario}.stdout", directory / f"{scenario}.stderr"
        measured = Measurement.run(command, self.env, REPO, stdout, stderr)
        elapsed = time.perf_counter() - started if started is not None else None
        operations = json.loads(operations_path.read_text()) if measured.returncode == 0 else {}
        self.report.native_builds.append(
            NativeRun(
                run.frontend, run.mode, run.sample, scenario, command, measured, str(executable), operations, elapsed
            )
        )
        if measured.returncode != 0:
            raise NativePlanError(
                f"native build {run.frontend}/{run.mode}/{scenario} failed ({measured.returncode}):\n{stderr.read_text()[-3000:]}"
            )

    def run(self) -> Report:
        self.record_provenance()
        for frontend in self.arguments.frontends:
            for mode in self.arguments.modes:
                for sample in range(1, self.arguments.samples + 1):
                    directory = self.out / f"{frontend}-{mode}-{sample}"
                    directory.mkdir()
                    started = time.perf_counter()
                    run = self.run_compiler(frontend, mode, sample, directory)
                    self.run_native(run, directory, "cold", started)
                    for repeat in range(1, self.arguments.warm_native_runs + 1):
                        self.run_native(run, directory, f"warm-native-{repeat}", None)
        self.verify_inputs()
        return self.report

    def markdown(self) -> str:
        rows = [
            f"### {self.program.name} ({self.report.target})",
            "",
            "| Frontend / mode | Scenario | Samples | Median | p95 | Compiled / reused | Links |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        groups: dict[tuple[str, str, str], list[NativeRun]] = {}
        for run in self.report.native_builds:
            scenario = "cold build" if run.scenario == "cold" else "warm native only"
            groups.setdefault((run.frontend, run.mode, scenario), []).append(run)
        for (frontend, mode, scenario), runs in groups.items():
            successful = [run for run in runs if run.measurement.returncode == 0]
            if not successful:
                rows.append(f"| {frontend} / {mode} | {scenario} | {len(runs)} failed | — | — | — | — |")
                continue
            times = sorted(
                run.end_to_end_s if run.end_to_end_s is not None else run.measurement.wall_s for run in successful
            )
            counts = sorted({(run.operations["compiled_units"], run.operations["reused_units"]) for run in successful})
            counts_text = ", ".join(f"{compiled} / {reused}" for compiled, reused in counts)
            links_text = ", ".join(str(count) for count in sorted({run.operations["links"] for run in successful}))
            rows.append(
                f"| {frontend} / {mode} | {scenario} | {len(successful)} | {statistics.median(times):.3f} s | {Distribution.nearest_rank(times, 95):.3f} s | {counts_text} | {links_text} |"
            )
        rows.extend(
            [
                "",
                "Cold build includes transpilation, strict native compile/link and harness overhead. Warm native excludes transpilation; it is not a product no-op. Per-unit timings, raw phase marks, RSS, commands and provenance are in JSON.",
                "",
            ]
        )
        rows.extend(
            [
                "| Frontend / mode / sample | Frontend | Analyze | Lower | Optimize | Emit | Other | Unattributed | Peak RSS |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for run in self.report.compilers:
            totals = run.phase_totals()
            times = " | ".join(f"{totals[name]:.3f} s" for name in ("frontend", *PHASES, "other", "unattributed"))
            rows.append(f"| {run.frontend} / {run.mode} / {run.sample} | {times} | {run.max_rss_kb / 1024:.1f} MiB |")
        return "\n".join(rows) + "\n"

    @staticmethod
    def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
        """Parse and validate the measurement matrix before anything is built."""

        parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument("program", help="the .btrc entry point to build")
        parser.add_argument("--btrcc", default=str(REPO / "bin" / "btrcc"))
        # One toolchain for both drivers, the pair tools.budget_bench pins.
        parser.add_argument("--cc", default=CC)
        parser.add_argument("--cxx", default=CXX)
        parser.add_argument("--pkg-config", default="pkg-config")
        parser.add_argument("--target", help="OS-ARCH (defaults to the current host)")
        parser.add_argument("--frontends", default="btrcpy,btrcc", help="comma-separated: btrcpy,btrcc")
        modes = parser.add_mutually_exclusive_group()
        modes.add_argument("--modes", default=None, help="comma-separated dev,release (default both)")
        modes.add_argument(
            "--opt", default=None, help="explicit O0..O3 native optimization levels without debug mapping"
        )
        parser.add_argument(
            "--samples", type=int, default=1, help="cold samples per frontend/mode (use at least 5 for acceptance)"
        )
        parser.add_argument(
            "--warm-native-runs", type=int, default=1, help="native-only object-cache repeats per sample"
        )
        parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
        parser.add_argument("--unit-lines", type=int, help="override the emitted-unit line target")
        parser.add_argument("--out", help="parent of a fresh retained run directory")
        parser.add_argument("--json", help="write the report here, including failure evidence")
        arguments = parser.parse_args(argv)
        arguments.frontends = arguments.frontends.split(",")
        selected_modes = arguments.opt if arguments.opt is not None else arguments.modes
        arguments.modes = ("dev,release" if selected_modes is None else selected_modes).split(",")
        allowed_modes = {"O0", "O1", "O2", "O3"} if arguments.opt is not None else {"dev", "release"}
        if not set(arguments.frontends) <= {"btrcpy", "btrcc"} or len(set(arguments.frontends)) != len(
            arguments.frontends
        ):
            parser.error("frontends must be distinct names from btrcpy,btrcc")
        if not set(arguments.modes) <= allowed_modes or len(set(arguments.modes)) != len(arguments.modes):
            parser.error("modes must be distinct supported values")
        if (
            arguments.samples < 1
            or arguments.jobs < 1
            or arguments.warm_native_runs < 0
            or (arguments.unit_lines is not None and arguments.unit_lines < 1)
        ):
            parser.error("samples, jobs and unit-lines must be positive; warm-native-runs must be nonnegative")
        try:
            target = PackageTarget.parse(arguments.target)
        except ValueError as error:
            parser.error(str(error))
        arguments.target = f"{target.operating_system}-{target.architecture}"
        if arguments.json:
            report_path, program_path = Path(arguments.json), Path(arguments.program)
            if report_path.resolve() == program_path.resolve() or (
                report_path.exists() and program_path.exists() and report_path.samefile(program_path)
            ):
                parser.error("JSON report must differ from the program input")
        return arguments

    def execute(self) -> int:
        """Run the matrix, then write the report and print its tables, failure included."""

        code = 0
        try:
            self.run()
        except (OSError, NativePlanError, subprocess.CalledProcessError) as error:
            self.report.failure = str(error)
            print(str(error), file=sys.stderr)
            code = 1
        finally:
            payload = json.dumps(asdict(self.report), indent=2) + "\n"
            (self.out / "report.json").write_text(payload)
            if self.arguments.json:
                path = Path(self.arguments.json)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload)
        print(self.markdown())
        print(f"Raw evidence: {self.out}")
        return code


# -- reference-compiler attribution (--cprofile) ----------------------------------

COMPILER_ROOT = REPO / "src" / "compiler" / "python"
# (owner, path under src/compiler/python, owner-class pattern): the first match
# wins. A path ending in "/" names a package; any other names one file.
OWNER_RULES: tuple[tuple[str, str, re.Pattern[str] | None], ...] = (
    ("native-plan", "frontend/native_imports.py", None),
    ("native-plan", "frontend/packages.py", re.compile(r"^Native")),
    ("frontend", "lexer/", None),
    ("frontend", "parser/", None),
    ("frontend", "syntax/", None),
    ("frontend", "frontend/", None),
    ("frontend", "abi/", None),
    ("analyzer", "analyzer/", None),
    ("optimizer", "ir/optimizer.py", None),
    ("optimizer", "ir/verifier.py", None),
    ("lowering", "ir/", None),
    ("lowering", "runtime/", None),
    ("emitter", "backend/", None),
    ("artifacts", "artifacts/", None),
    ("module-units", "application/modules.py", None),
    ("driver", "application/", None),
    ("driver", "cli/", None),
    ("driver", "main.py", None),
    ("driver", "__init__.py", None),
)
# `startup` is import-time code: module bodies and the import machinery.
OWNERS = (
    "frontend",
    "native-plan",
    "analyzer",
    "lowering",
    "module-units",
    "optimizer",
    "emitter",
    "artifacts",
    "driver",
    "startup",
)
UNATTRIBUTED = "unattributed"
# The `btrcpy timing:` phase groups, plus `outside`: wall time no phase mark covers.
PHASE_GROUPS = ("frontend", "analyze", "lower", "optimize", "emit", "outside")
# The phase group each owner's time is compared with. Ownership is not phase
# (the lowerer calls analyzer helpers; module units also optimize and emit), so
# the comparison is a triage aid; the owner table is the attribution.
OWNER_PHASE_GROUPS = {
    "frontend": "frontend",
    "native-plan": "frontend",
    "analyzer": "analyze",
    "lowering": "lower",
    "module-units": "lower",
    "optimizer": "optimize",
    "emitter": "emit",
    "artifacts": "outside",
    "driver": "outside",
    "startup": "outside",
    UNATTRIBUTED: "outside",
}


class ClassSpans:
    """The classes each compiler source declares, so a profiled line names its owner class."""

    def __init__(self) -> None:
        self._files: dict[Path, list[tuple[int, int, str]]] = {}

    def owner(self, path: Path, line: int) -> str | None:
        """The innermost class whose source span holds `line`, dotted (`Outer.Inner`)."""

        spans = self._files.get(path)
        if spans is None:
            spans = self._files[path] = self.read(path)
        owner = None
        for start, end, name in spans:
            # Outer classes precede the classes nested in them.
            if start <= line <= end:
                owner = name
        return owner

    @staticmethod
    def read(path: Path) -> list[tuple[int, int, str]]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError, ValueError):
            return []
        spans: list[tuple[int, int, str]] = []

        def visit(node: ast.AST, prefix: str) -> None:
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.ClassDef):
                    name = f"{prefix}{child.name}"
                    start = min((decorator.lineno for decorator in child.decorator_list), default=child.lineno)
                    spans.append((start, child.end_lineno or child.lineno, name))
                    visit(child, f"{name}.")
                else:
                    visit(child, prefix)

        visit(tree, "")
        return spans


@dataclass(frozen=True)
class ProfileAnchor:
    """Where a profiled function's attributed time goes: its owner, module and owner class."""

    owner: str
    module: str
    owner_class: str | None


ProfileFunction = tuple[str, int, str]


class ProfileAttribution:
    """Partition one cProfile run, or several merged, among the reference compiler's owners.

    cProfile records each function's own time and, per caller, the time spent
    in it from that caller. A compiler function keeps its own time. A library,
    builtin or harness function hands its own time to its callers in
    proportion to the time each spent in it, round after round, until the time
    reaches a compiler function, or import-time code (`startup`). Time that
    reaches a root without passing either is `unattributed`. The owners
    therefore partition the profile: they sum to its total and nothing is
    counted twice, where cumulative times would count nested owners again.
    The split by caller is proportional, as in gprof, so a helper shared by
    two owners is divided by how long each spent in it, not by exact stacks.
    """

    MAX_ROUNDS = 1000
    EPSILON_S = 1e-9

    def __init__(
        self,
        stats: Mapping[ProfileFunction, tuple],
        *,
        root: Path = REPO,
        compiler: Path = COMPILER_ROOT,
        classes: ClassSpans | None = None,
    ) -> None:
        self.stats = stats
        self.root = root
        self.compiler = compiler
        self.classes = classes or ClassSpans()
        self._anchors: dict[ProfileFunction, ProfileAnchor | None] = {}
        self._shares: dict[tuple[ProfileFunction, bool], tuple[tuple[ProfileFunction, float], ...]] = {}

    @classmethod
    def load(cls, paths: Sequence[Path], **options) -> ProfileAttribution:
        """Merge `pstats` files (cProfile's `-o` output) into one attribution."""

        return cls(pstats.Stats(*(str(path) for path in paths)).stats, **options)  # type: ignore[attr-defined]

    @staticmethod
    def owner_rule(relative: str, owner_class: str | None) -> tuple[str, str, re.Pattern[str] | None] | None:
        """The OWNER_RULES row for a file under src/compiler/python, or None."""

        for rule in OWNER_RULES:
            _, prefix, pattern = rule
            located = relative.startswith(prefix) if prefix.endswith("/") else relative == prefix
            if located and (pattern is None or (owner_class is not None and pattern.search(owner_class))):
                return rule
        return None

    def module(self, filename: str) -> str:
        path = Path(filename)
        return (
            path.relative_to(self.root).as_posix()
            if path.is_absolute() and path.is_relative_to(self.root)
            else filename
        )

    def anchor(self, function: ProfileFunction) -> ProfileAnchor | None:
        """The owner a function's time stops at, or None when it passes to its callers."""

        if function in self._anchors:
            return self._anchors[function]
        filename, line, name = function
        anchor = None
        # cProfile's own `-m` harness runs as `<string>:1(<module>)`; it is not import time.
        if (name == "<module>" and filename != "<string>") or filename.startswith(
            ("<frozen importlib", "<frozen zipimport")
        ):
            anchor = ProfileAnchor("startup", self.module(filename), None)
        else:
            path = Path(filename)
            if path.is_absolute() and path.is_relative_to(self.compiler):
                owner_class = self.classes.owner(path, line)
                rule = self.owner_rule(path.relative_to(self.compiler).as_posix(), owner_class)
                anchor = ProfileAnchor(rule[0] if rule else "driver", self.module(filename), owner_class)
        self._anchors[function] = anchor
        return anchor

    def caller_shares(self, function: ProfileFunction, *, inherited: bool) -> tuple[tuple[ProfileFunction, float], ...]:
        """Each caller's fraction of `function`'s time; recursion is not a caller.

        cProfile's caller edges are (primitive calls, calls, own time,
        cumulative time). A function's own time splits by each caller's own
        time in it, which is exact; time it inherited from its callees splits
        by cumulative time. Splitting own time by cumulative time instead
        would hand a hub such as `exec` to whichever caller ran the most below it.
        """

        key = (function, inherited)
        if key in self._shares:
            return self._shares[key]
        entry = self.stats.get(function)
        callers = {caller: edge for caller, edge in (entry[4] if entry else {}).items() if caller != function}
        weights = {
            caller: (edge[3] if inherited else edge[2]) if isinstance(edge, tuple) else 0.0
            for caller, edge in callers.items()
        }
        if sum(weights.values()) <= 0:
            # Too fast for the clock: split by call count.
            weights = {caller: edge[1] if isinstance(edge, tuple) else edge for caller, edge in callers.items()}
        total = sum(weights.values())
        shares = (
            tuple((caller, weight / total) for caller, weight in weights.items() if weight > 0) if total > 0 else ()
        )
        self._shares[key] = shares
        return shares

    def distribute(self) -> tuple[dict[ProfileFunction, float], float]:
        """Every anchored function's attributed seconds, and the unattributed rest."""

        attributed: dict[ProfileFunction, float] = defaultdict(float)
        unattributed = 0.0
        pending = {function: entry[2] for function, entry in self.stats.items() if entry[2] > 0}
        for round_index in range(self.MAX_ROUNDS):
            if not pending:
                break
            following: dict[ProfileFunction, float] = defaultdict(float)
            for function, seconds in pending.items():
                if self.anchor(function) is not None:
                    attributed[function] += seconds
                    continue
                shares = self.caller_shares(function, inherited=round_index > 0)
                if not shares:
                    unattributed += seconds
                    continue
                for caller, share in shares:
                    following[caller] += seconds * share
            pending = {}
            for function, seconds in following.items():
                if seconds > self.EPSILON_S:
                    pending[function] = seconds
                else:
                    unattributed += seconds
        unattributed += sum(pending.values())
        return attributed, unattributed

    def rollup(self, *, top: int = 40) -> dict[str, object]:
        """Seconds per owner, per module and per owner class, and the heaviest functions."""

        attributed, unattributed = self.distribute()
        owners = dict.fromkeys((*OWNERS, UNATTRIBUTED), 0.0)
        modules: dict[tuple[str, str], float] = defaultdict(float)
        classes: dict[tuple[str, str], float] = defaultdict(float)
        for function, seconds in attributed.items():
            anchor = self.anchor(function)
            assert anchor is not None
            owners[anchor.owner] += seconds
            modules[(anchor.owner, anchor.module)] += seconds
            if anchor.owner_class is not None:
                classes[(anchor.owner, f"{anchor.module}:{anchor.owner_class}")] += seconds
        owners[UNATTRIBUTED] = unattributed
        heaviest = sorted(attributed.items(), key=lambda item: -item[1])[:top]

        def ranked(table: dict[tuple[str, str], float], key: str, limit: int | None) -> list[dict[str, object]]:
            rows = sorted(table.items(), key=lambda item: -item[1])
            return [{key: name, "owner": owner, "seconds": seconds} for (owner, name), seconds in rows[:limit]]

        return {
            "profile_total_s": sum(entry[2] for entry in self.stats.values()),
            "owners_s": owners,
            "modules": ranked(modules, "module", None),
            "classes": ranked(classes, "class", top),
            "functions": [
                {
                    "function": f"{self.module(function[0])}:{function[1]}({function[2]})",
                    "owner": self.anchor(function).owner,  # type: ignore[union-attr]
                    "owner_class": self.anchor(function).owner_class,  # type: ignore[union-attr]
                    "seconds": seconds,
                    "self_s": self.stats[function][2],
                    "cumulative_s": self.stats[function][3],
                    "calls": self.stats[function][1],
                }
                for function, seconds in heaviest
            ],
        }


@dataclass
class AttributionSample:
    """One plain and one profiled build of the same scenario."""

    scenario: str
    sample: int
    plain_wall_s: float
    plain_phases_s: dict[str, float]
    profiled_wall_s: float
    profiled_phases_s: dict[str, float]
    profile: str
    profile_total_s: float = 0.0
    attributed_s: float = 0.0
    attributed_fraction: float = 0.0


class ReferenceAttribution:
    """`--cprofile`: where the reference compiler's cold and edit time goes.

    Every scenario sample is two builds: a plain one with BTRC_TIMING=1, whose
    phases are the unprofiled reference, and one under cProfile. cProfile
    slows small, frequent calls most, so the profiled build's shares are a
    triage map, reported beside the plain phases, not a substitute for them.
    The time measured is the compiler process alone, from command start to
    exit; the native build is tools.native_plan's, and tools.perf's default
    mode measures it. Module-unit builds lower with --jobs 1 by default:
    cProfile sees one process, so work done in forked workers would show as
    the owner waiting for them.
    """

    SCHEMA = "btrc-reference-attribution/1"
    # PLAN.md Stage 6: at least 90% of reference time is attributed.
    TARGET_FRACTION = 0.90
    # Top-level workspace entries a copy leaves behind: outputs and history.
    SKIPPED_TOP_LEVEL = frozenset({".git", "build", "dist", ".btrc-cache"})
    # `python -m cProfile` swallows the compiler's SystemExit and exits 0, so a
    # failed compile would pass as a sample. This runner keeps its exit status.
    PROFILER = (
        "import cProfile, runpy, sys\n"
        "output, sys.argv = sys.argv[1], ['src.compiler.python.main', *sys.argv[2:]]\n"
        "profiler = cProfile.Profile()\n"
        "code = 0\n"
        "profiler.enable()\n"
        "try:\n"
        "    runpy.run_module('src.compiler.python.main', run_name='__main__', alter_sys=True)\n"
        "except SystemExit as stop:\n"
        "    code = stop.code if isinstance(stop.code, int) else (0 if stop.code is None else 1)\n"
        "finally:\n"
        "    profiler.disable()\n"
        "    profiler.dump_stats(output)\n"
        "sys.exit(code)\n"
    )

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.arguments = arguments
        destination = Path(arguments.out).resolve() if arguments.out else REPO / "build/perf/attribution"
        destination.mkdir(parents=True, exist_ok=True)
        self.out = Path(tempfile.mkdtemp(prefix="cprofile-", dir=destination))
        self.workspace = self.out / "ws"
        self.flavor = Flavor(arguments.mode, arguments.units)
        self.revisions: dict[str, int] = {}
        self.samples: list[AttributionSample] = []
        self.report: dict[str, object] = {
            "schema": self.SCHEMA,
            "tool": "tools/perf.py --cprofile",
            "frontend": "reference",
            "configuration": {
                "stand_in": arguments.stand_in,
                "workspace": None if arguments.stand_in else str(Path(arguments.workspace).resolve()),
                "entry": ENTRY,
                "mode": arguments.mode,
                "units": arguments.units,
                "jobs": arguments.jobs if arguments.units == "module" else None,
                "target": arguments.target,
                "cold_samples": arguments.cold_samples,
                "edit_samples": arguments.edit_samples,
                "edits": [fixture.name for fixture in arguments.fixtures],
                "dry_run": arguments.dry_run,
                "target_fraction": self.TARGET_FRACTION,
                "min_attributed": arguments.min_attributed,
            },
            "scenarios": {},
            "summary": {},
            "provenance": {},
            "failure": None,
        }

    # -- builds

    def prepare(self) -> None:
        if self.arguments.stand_in:
            StandInWorkspace.write(self.workspace)
            return
        source = Path(self.arguments.workspace).resolve()

        def skipped(directory: str, names: list[str]) -> set[str]:
            return set(names) & self.SKIPPED_TOP_LEVEL if Path(directory).resolve() == source else set()

        shutil.copytree(source, self.workspace, symlinks=True, ignore=skipped)
        if not (self.workspace / ENTRY).is_file():
            raise NativePlanError(f"--workspace {source} has no {ENTRY}")

    def command(self, paths: ProductPaths, profile: Path | None) -> list[str]:
        """budget_bench's reference compile (BuildCommands.compile), optionally under cProfile."""

        driver = ["-c", self.PROFILER, str(profile)] if profile is not None else ["-m", "src.compiler.python.main"]
        jobs = ["--jobs", str(self.arguments.jobs)] if self.arguments.units == "module" else []
        return [
            sys.executable,
            "-P",
            *driver,
            "--strict-imports",
            "--target",
            self.arguments.target,
            *self.flavor.compiler_flags(),
            *jobs,
            "--emit-link-plan",
            str(paths.plan),
            "--emit-units",
            str(paths.units_prefix),
            ENTRY,
            "-o",
            str(paths.generated_c),
        ]

    def environment(self, state: State) -> dict[str, str]:
        return {
            **os.environ,
            "BTRC_HOME": str(REPO / "src"),
            "BTRC_CACHE_DIR": str(state.cache),
            "PYTHONPATH": str(REPO),
            "BTRC_TIMING": "1",
        }

    def build(self, state: State, label: str, *, profiled: bool) -> tuple[float, dict[str, float], Path | None]:
        """One compile: wall seconds from command start to exit, its phase marks, its profile."""

        profile = self.out / "profiles" / f"{label}.prof" if profiled else None
        logs = self.out / "logs"
        for directory in (logs, *((profile.parent,) if profile else ()), state.build):
            directory.mkdir(parents=True, exist_ok=True)
        command = self.command(ProductPaths.direct(state.build), profile)
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            env=self.environment(state),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=self.arguments.timeout_s,
        )
        wall = time.perf_counter() - started
        (logs / f"{label}.stderr").write_text(completed.stderr)
        if completed.returncode != 0:
            raise NativePlanError(
                f"reference compile {label} failed ({completed.returncode}): {' '.join(command)}\n"
                f"{completed.stderr[-3000:]}"
            )
        if profile is not None and not profile.is_file():
            raise NativePlanError(f"reference compile {label} wrote no profile {profile}")
        return wall, phase_times(completed.stderr), profile

    def sample(self, scenario: str, index: int, plain: State, profiled: State, before=None) -> None:
        """A plain build, then a profiled one; `before` runs ahead of each (an edit)."""

        if before is not None:
            before()
        plain_wall, plain_phases, _ = self.build(plain, f"{scenario}-{index}-plain", profiled=False)
        if before is not None:
            before()
        wall, phases, profile = self.build(profiled, f"{scenario}-{index}-profiled", profiled=True)
        assert profile is not None
        self.samples.append(
            AttributionSample(
                scenario, index, plain_wall, plain_phases, wall, phases, str(profile.relative_to(self.out))
            )
        )

    def apply(self, fixture: Fixture, revision: int) -> None:
        """budget_bench's edit: replace the fixture's current text with a novel revision."""

        path = self.workspace / fixture.module
        text = path.read_text()
        current = fixture.render(self.revisions.get(fixture.name, 0))
        if text.count(current) != 1:
            raise NativePlanError(f"edit anchor for {fixture.name} is not unique in {fixture.module}")
        path.write_text(text.replace(current, fixture.render(revision), 1))
        self.revisions[fixture.name] = revision

    def advance(self, fixture: Fixture) -> None:
        self.apply(fixture, self.revisions.get(fixture.name, 0) + 1)

    def cold(self) -> None:
        """Each build starts from an empty artifact cache and output directory."""

        for index in range(1, self.arguments.cold_samples + 1):
            states = [State(self.out / "states" / f"cold-{index}-{kind}") for kind in ("plain", "profiled")]
            for state in states:
                state.reset(objects=True)
            self.sample("cold", index, *states)

    def edits(self) -> None:
        """Each build follows the previous one in one primed state, as a developer's edit does.

        Every build writes a revision the run has not built, so none is an
        artifact-cache hit, and each is one module's body changed since the
        build before it.
        """

        if not self.arguments.fixtures:
            return
        state = State(self.out / "states" / "edits")
        state.reset(objects=True)
        self.build(state, "edits-prime", profiled=False)
        for fixture in self.arguments.fixtures:
            for index in range(1, self.arguments.edit_samples + 1):
                self.sample(
                    f"edit-{fixture.name}", index, state, state, before=lambda fixture=fixture: self.advance(fixture)
                )

    # -- the report

    @staticmethod
    def phase_group(name: str) -> str:
        if name in FRONTEND_PHASES:
            return "frontend"
        if name in PHASES:
            return name
        return "optimize" if name == "setjmp-analysis" else "outside"

    @classmethod
    def grouped_phases(cls, phases: Mapping[str, float], wall: float) -> dict[str, float]:
        """Phase marks by group; `outside` is the wall time no frontend..emit mark covers."""

        groups = dict.fromkeys(PHASE_GROUPS, 0.0)
        for name, seconds in phases.items():
            group = cls.phase_group(name)
            if group != "outside":
                groups[group] += seconds
        groups["outside"] = wall - sum(groups[group] for group in PHASE_GROUPS if group != "outside")
        return groups

    @staticmethod
    def fraction(part: float, whole: float) -> float:
        return part / whole if whole > 0 else 0.0

    @staticmethod
    def distribution(values: list[float]) -> dict[str, float | None]:
        return {
            "median": Distribution.median(values),
            "p95": Distribution.nearest_rank(values, 95),
            "max": max(values, default=None),
        }

    def scenario_report(self, samples: list[AttributionSample]) -> dict[str, object]:
        profiles = [self.out / sample.profile for sample in samples]
        for sample, path in zip(samples, profiles, strict=True):
            owners = ProfileAttribution.load([path]).rollup(top=0)
            sample.profile_total_s = float(owners["profile_total_s"])  # type: ignore[arg-type]
            sample.attributed_s = sum(
                seconds
                for owner, seconds in owners["owners_s"].items()  # type: ignore[union-attr]
                if owner != UNATTRIBUTED
            )
            sample.attributed_fraction = self.fraction(sample.attributed_s, sample.profiled_wall_s)
        rollup = ProfileAttribution.load(profiles).rollup(top=self.arguments.top)
        plain_wall = sum(sample.plain_wall_s for sample in samples)
        profiled_wall = sum(sample.profiled_wall_s for sample in samples)
        owners: dict[str, float] = rollup["owners_s"]  # type: ignore[assignment]
        attributed = sum(seconds for owner, seconds in owners.items() if owner != UNATTRIBUTED)
        plain_groups = dict.fromkeys(PHASE_GROUPS, 0.0)
        profiled_groups = dict.fromkeys(PHASE_GROUPS, 0.0)
        for sample in samples:
            for group, seconds in self.grouped_phases(sample.plain_phases_s, sample.plain_wall_s).items():
                plain_groups[group] += seconds
            for group, seconds in self.grouped_phases(sample.profiled_phases_s, sample.profiled_wall_s).items():
                profiled_groups[group] += seconds
        owner_groups = dict.fromkeys(PHASE_GROUPS, 0.0)
        for owner, seconds in owners.items():
            owner_groups[OWNER_PHASE_GROUPS[owner]] += seconds
        # Wall time the profile never saw (interpreter start before cProfile,
        # writing the profile, interpreter exit) is outside every phase too.
        owner_groups["outside"] += profiled_wall - float(rollup["profile_total_s"])  # type: ignore[arg-type]
        reconciliation = {
            group: {
                "plain_phase_s": plain_groups[group],
                "plain_share": self.fraction(plain_groups[group], plain_wall),
                "profiled_phase_s": profiled_groups[group],
                "profiled_share": self.fraction(profiled_groups[group], profiled_wall),
                "owner_s": owner_groups[group],
                "owner_share": self.fraction(owner_groups[group], profiled_wall),
                "owners": sorted(owner for owner, mapped in OWNER_PHASE_GROUPS.items() if mapped == group),
            }
            for group in PHASE_GROUPS
        }
        return {
            "samples": [asdict(sample) for sample in samples],
            "plain_wall_s": self.distribution([sample.plain_wall_s for sample in samples]),
            "profiled_wall_s": self.distribution([sample.profiled_wall_s for sample in samples]),
            "plain_wall_total_s": plain_wall,
            "profiled_wall_total_s": profiled_wall,
            "profile_total_s": rollup["profile_total_s"],
            "profiler_coverage": self.fraction(float(rollup["profile_total_s"]), profiled_wall),  # type: ignore[arg-type]
            "overhead_ratio": self.fraction(profiled_wall, plain_wall),
            "attributed_s": attributed,
            "attributed_fraction": self.fraction(attributed, profiled_wall),
            # The same without import time, which `startup` attributes to modules, not to compiler work.
            "compiler_fraction": self.fraction(attributed - owners["startup"], profiled_wall),
            "owner_shares": {owner: self.fraction(seconds, profiled_wall) for owner, seconds in owners.items()},
            # Each owner's share of the profiled wall, applied to the plain wall:
            # an estimate of where uninstrumented time goes, skewed by profiler overhead.
            "estimated_plain_owner_s": {
                owner: self.fraction(seconds, profiled_wall) * plain_wall for owner, seconds in owners.items()
            },
            "reconciliation": reconciliation,
            "attribution": rollup,
        }

    def summarize(self) -> None:
        scenarios: dict[str, list[AttributionSample]] = {}
        for sample in self.samples:
            scenarios.setdefault(sample.scenario, []).append(sample)
        reports = {name: self.scenario_report(samples) for name, samples in scenarios.items()}
        self.report["scenarios"] = reports
        profiled = sum(report["profiled_wall_total_s"] for report in reports.values())  # type: ignore[misc]
        attributed = sum(report["attributed_s"] for report in reports.values())  # type: ignore[misc]
        fractions = {name: report["attributed_fraction"] for name, report in reports.items()}
        minimum = min(fractions.values(), default=0.0)
        self.report["summary"] = {
            "attributed_fraction": self.fraction(attributed, profiled),
            "scenario_fractions": fractions,
            "minimum_fraction": minimum,
            "target_fraction": self.TARGET_FRACTION,
            "meets_target": bool(fractions) and minimum >= self.TARGET_FRACTION,
            "meets_minimum": bool(fractions) and minimum >= self.arguments.min_attributed,
            "owner_shares": {
                name: {owner: round(share, 4) for owner, share in report["owner_shares"].items()}  # type: ignore[union-attr]
                for name, report in reports.items()
            },
        }

    def record_provenance(self) -> None:
        workspace = None if self.arguments.stand_in else Perf.repository(Path(self.arguments.workspace).resolve())
        self.report["provenance"] = {
            "compiler_repository": Perf.repository(REPO),
            "product_repository": workspace,
            "python": {"executable": sys.executable, "version": platform.python_version()},
            "host": platform.uname()._asdict(),
            "host_summary": HostSummary.describe(),
            "cpu_count": os.cpu_count(),
            "work_directory": str(self.out),
            "scope": "the reference compiler process only, from command start to exit; native builds are not timed",
            "profiler": "cProfile (deterministic); its overhead inflates small, frequent calls, so plain phases are reported beside it",
        }

    def run(self) -> None:
        self.record_provenance()
        self.prepare()
        if self.arguments.cold_samples:
            self.cold()
        self.edits()
        self.summarize()
        if self.arguments.min_attributed and not self.report["summary"]["meets_minimum"]:  # type: ignore[index]
            raise NativePlanError(
                f"attributed {self.report['summary']['minimum_fraction']:.1%} of a scenario's profiled wall time, "  # type: ignore[index]
                f"below --min-attributed {self.arguments.min_attributed:.0%}"
            )

    def markdown(self) -> str:
        scenarios: dict[str, dict] = self.report["scenarios"]  # type: ignore[assignment]
        configuration = self.report["configuration"]
        rows = [
            f"### Reference attribution ({'stand-in' if configuration['stand_in'] else configuration['workspace']}, "  # type: ignore[index]
            f"{configuration['mode']}/{configuration['units']})",  # type: ignore[index]
            "",
            "| Scenario | Samples | Plain median | Profiled median | Overhead | Profiled | Attributed |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for name, report in scenarios.items():
            rows.append(
                f"| {name} | {len(report['samples'])} | {report['plain_wall_s']['median']:.3f} s | "
                f"{report['profiled_wall_s']['median']:.3f} s | {report['overhead_ratio']:.2f}x | "
                f"{report['profiler_coverage']:.1%} | {report['attributed_fraction']:.1%} |"
            )
        rows.extend(
            ["", f"| Scenario | {' | '.join((*OWNERS, UNATTRIBUTED))} |", f"| --- |{' --- |' * (len(OWNERS) + 1)}"]
        )
        for name, report in scenarios.items():
            shares = " | ".join(f"{report['owner_shares'][owner]:.1%}" for owner in (*OWNERS, UNATTRIBUTED))
            rows.append(f"| {name} | {shares} |")
        rows.extend(
            [
                "",
                "| Scenario | Group | Plain phases | Profiled phases | Profiled owners |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for name, report in scenarios.items():
            for group, row in report["reconciliation"].items():
                rows.append(
                    f"| {name} | {group} | {row['plain_share']:.1%} | {row['profiled_share']:.1%} | {row['owner_share']:.1%} |"
                )
        summary = self.report["summary"]
        if summary:
            rows.extend(
                [
                    "",
                    f"Attributed {summary['attributed_fraction']:.1%} of profiled wall time overall, "  # type: ignore[index]
                    f"{summary['minimum_fraction']:.1%} in the least-attributed scenario "  # type: ignore[index]
                    f"(target {self.TARGET_FRACTION:.0%}). Owner shares are of profiled wall time; "
                    "`outside` is wall time no `btrcpy timing:` phase covers. Classes, modules and functions are in JSON.",
                ]
            )
        return "\n".join(rows) + "\n"

    @classmethod
    def parse_arguments(cls, argv: list[str]) -> argparse.Namespace:
        parser = argparse.ArgumentParser(
            prog="python3 -m tools.perf --cprofile",
            description=ReferenceAttribution.__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("--cprofile", action="store_true", required=True, help="attribute reference time")
        parser.add_argument("--frontend", choices=("reference",), default="reference")
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--workspace", help="the pinned BTRSmith checkout; copied, never edited")
        source.add_argument("--stand-in", action="store_true", help="budget_bench's generated stand-in workspace")
        parser.add_argument("--mode", choices=("dev", "release"), default="dev")
        parser.add_argument("--units", choices=("module", "whole"), help="default: module for dev, whole for release")
        parser.add_argument("--target", help="OS-ARCH; default: this host as BTRSmith's make/Config.mk spells it")
        parser.add_argument(
            "--jobs",
            type=int,
            default=1,
            help="module-unit workers (default 1: cProfile sees only the owner process, not forked workers)",
        )
        parser.add_argument("--cold-samples", type=int, default=3, help="cold transpiles (each plain and profiled)")
        parser.add_argument("--edit-samples", type=int, default=3, help="edits per fixture (each plain and profiled)")
        parser.add_argument(
            "--edits",
            default="all",
            help=f"comma-separated EDIT_FIXTURES ({', '.join(fixture.name for fixture in EDIT_FIXTURES)}), all, or none",
        )
        parser.add_argument("--dry-run", action="store_true", help="one sample of each scenario")
        parser.add_argument(
            "--min-attributed",
            type=float,
            default=0.0,
            help="fail when a scenario attributes less than this fraction (the Stage 6 target is 0.90)",
        )
        parser.add_argument("--top", type=int, default=40, help="classes and functions kept per scenario")
        parser.add_argument("--timeout-s", type=float, default=7200.0, help="limit for one compile")
        parser.add_argument("--out", help="parent of a fresh retained run directory")
        parser.add_argument("--json", help="write the report here, including failure evidence")
        arguments = parser.parse_args(argv)
        arguments.units = arguments.units or ("module" if arguments.mode == "dev" else "whole")
        try:
            arguments.target = HostTarget.resolve(arguments.target)
        except ValueError as error:
            parser.error(str(error))
        names = {fixture.name: fixture for fixture in EDIT_FIXTURES}
        requested = [name for name in arguments.edits.split(",") if name]
        if requested == ["all"]:
            requested = list(names)
        elif requested == ["none"]:
            requested = []
        unknown = [name for name in requested if name not in names]
        if unknown or len(set(requested)) != len(requested):
            parser.error(f"--edits names distinct fixtures from {', '.join(names)}, or all, or none")
        arguments.fixtures = tuple(names[name] for name in requested)
        if arguments.dry_run:
            arguments.cold_samples = min(arguments.cold_samples, 1)
            arguments.edit_samples = min(arguments.edit_samples, 1)
        if arguments.cold_samples < 0 or arguments.edit_samples < 1 or arguments.top < 1 or arguments.timeout_s <= 0:
            parser.error("cold-samples must be nonnegative; edit-samples, top and timeout-s positive")
        if not arguments.cold_samples and not arguments.fixtures:
            parser.error("nothing to measure: no cold samples and no edits")
        if not 0.0 <= arguments.min_attributed <= 1.0:
            parser.error("--min-attributed is a fraction from 0 to 1")
        if not 1 <= arguments.jobs <= 64:
            parser.error("--jobs is a worker count from 1 to 64")
        if arguments.workspace is not None:
            workspace = Path(arguments.workspace).resolve()
            if not workspace.is_dir():
                parser.error(f"--workspace {arguments.workspace} is not a directory")
            if not (workspace / ENTRY).is_file():
                parser.error(f"--workspace {arguments.workspace} has no {ENTRY}")
            out = Path(arguments.out).resolve() if arguments.out else REPO / "build/perf/attribution"
            inside = out.relative_to(workspace).parts if out.is_relative_to(workspace) else None
            if inside is not None and (not inside or inside[0] not in cls.SKIPPED_TOP_LEVEL):
                parser.error(f"--out {out} is inside --workspace, which is copied; choose another directory")
        return arguments

    def execute(self) -> int:
        """Run the scenarios, then write the report and print its tables, failure included."""

        code = 0
        try:
            self.run()
        except (OSError, NativePlanError, subprocess.SubprocessError) as error:
            self.report["failure"] = str(error)
            print(str(error), file=sys.stderr)
            code = 1
        finally:
            payload = json.dumps(self.report, indent=2) + "\n"
            (self.out / "attribution.json").write_text(payload)
            if self.arguments.json:
                path = Path(self.arguments.json)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(payload)
        print(self.markdown())
        print(f"Raw evidence (profiles, logs): {self.out}")
        return code


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if "--cprofile" in arguments:
        return ReferenceAttribution(ReferenceAttribution.parse_arguments(arguments)).execute()
    return Perf(Perf.parse_arguments(argv)).execute()


if __name__ == "__main__":
    raise SystemExit(main())
