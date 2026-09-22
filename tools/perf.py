"""Measure complete strict native-plan builds from both BTRC frontends.

    python3 -m tools.perf ../btrsmith/src/BTRSmith.btrc --json build/perf/btrsmith.json

Use the program's development environment for SDKs and packages. Every sample
transpiles into split units and builds all emitted/native/adapter units, then
links using the production native-plan adapter. Dev uses source mapping and
-O0 -g; release uses -O2. Warm-native samples validate the object cache and
relink the existing plan; they are not whole-product no-op measurements.
Raw logs, operation reports and binaries remain in the reported run directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.compiler.python.frontend.packages import PackageTarget
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
TIMING_LINE = re.compile(r"^(btrcpy|btrcc) timing: (.*)$")


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


def measure(command: list[str], env: dict[str, str], cwd: Path, stdout: Path, stderr: Path) -> Measurement:
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
    return Measurement.from_usage(json.loads(completed.stdout), sys.platform)


def phase_times(stderr: str) -> dict[str, float]:
    """Both compilers print `<name> timing: phase=NNNus ...`; sum per phase in seconds."""

    phases: dict[str, float] = {}
    for line in stderr.splitlines():
        match = TIMING_LINE.match(line.strip())
        if not match:
            continue
        for item in match.group(2).split():
            name, _, value = item.partition("=")
            if value.endswith("us"):
                phases[name] = phases.get(name, 0.0) + int(value[:-2]) / 1_000_000.0
    return phases


def c_stats(path: Path) -> CStats:
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
    return CStats(lines, path.stat().st_size, functions, structs, len(vectors), directives)


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
        measured = measure(command, self.env, REPO, stdout, stderr)
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
        for path in [generated, *(Path(f"{generated}.unit-{index}.c") for index in range(1, native.emitted_units + 1))]:
            self.report.c_stats[str(path.relative_to(self.out))] = c_stats(path)
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
        measured = measure(command, self.env, REPO, stdout, stderr)
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
                f"| {frontend} / {mode} | {scenario} | {len(successful)} | {statistics.median(times):.3f} s | {times[math.ceil(0.95 * len(times)) - 1]:.3f} s | {counts_text} | {links_text} |"
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", help="the .btrc entry point to build")
    parser.add_argument("--btrcc", default=str(REPO / "bin" / "btrcc"))
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--cxx", default="c++")
    parser.add_argument("--pkg-config", default="pkg-config")
    parser.add_argument("--target", help="OS-ARCH (defaults to the current host)")
    parser.add_argument("--frontends", default="btrcpy,btrcc", help="comma-separated: btrcpy,btrcc")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--modes", default=None, help="comma-separated dev,release (default both)")
    modes.add_argument("--opt", default=None, help="explicit O0..O3 native optimization levels without debug mapping")
    parser.add_argument(
        "--samples", type=int, default=1, help="cold samples per frontend/mode (use at least 5 for acceptance)"
    )
    parser.add_argument("--warm-native-runs", type=int, default=1, help="native-only object-cache repeats per sample")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--unit-lines", type=int, help="override the emitted-unit line target")
    parser.add_argument("--out", help="parent of a fresh retained run directory")
    parser.add_argument("--json", help="write the report here, including failure evidence")
    arguments = parser.parse_args(argv)
    arguments.frontends = arguments.frontends.split(",")
    selected_modes = arguments.opt if arguments.opt is not None else arguments.modes
    arguments.modes = ("dev,release" if selected_modes is None else selected_modes).split(",")
    allowed_modes = {"O0", "O1", "O2", "O3"} if arguments.opt is not None else {"dev", "release"}
    if not set(arguments.frontends) <= {"btrcpy", "btrcc"} or len(set(arguments.frontends)) != len(arguments.frontends):
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
    perf = Perf(arguments)
    code = 0
    try:
        perf.run()
    except (OSError, NativePlanError, subprocess.CalledProcessError) as error:
        perf.report.failure = str(error)
        print(str(error), file=sys.stderr)
        code = 1
    finally:
        payload = json.dumps(asdict(perf.report), indent=2) + "\n"
        (perf.out / "report.json").write_text(payload)
        if arguments.json:
            path = Path(arguments.json)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload)
    print(perf.markdown())
    print(f"Raw evidence: {perf.out}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
