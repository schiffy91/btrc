"""Measurements: what the suite times and how it times it."""

from __future__ import annotations

import os
import platform
import re
import resource
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROGRAMS = REPO / "src" / "tests" / "benchmarks"
CFLAGS = shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11 -pedantic"))
LIBS = ["-lm", "-lpthread"]
TIME = Path("/usr/bin/time")
FOOTPRINT = re.compile(r"(\d+)\s+peak memory footprint")
TIMING_VARIABLES = ("BTRC_TIMING", "BTRCC_TIMING")


@dataclass(frozen=True)
class Program:
    name: str
    path: Path

    @property
    def runs(self) -> bool:
        """Workloads named Run* are executed and timed; the rest are compile-only."""

        return self.name.startswith("Run") or self.name == "BenchHello"

    @property
    def phases(self) -> bool:
        """Per-phase compiler timings are kept for the floor program and the stdlib-heavy one."""

        return self.name in {"BenchHello", "CompileStdlibHeavy"}


def discover(names: list[str] | None = None) -> list[Program]:
    programs = [Program(path.stem, path) for path in sorted(PROGRAMS.glob("*.btrc"))]
    if names:
        wanted = set(names)
        programs = [program for program in programs if program.name in wanted]
        missing = wanted - {program.name for program in programs}
        if missing:
            raise ValueError(f"unknown benchmark programs: {', '.join(sorted(missing))}")
    return programs


@dataclass
class Timing:
    wall_ms: float
    cpu_ms: float
    stdout: str = ""
    stderr: str = ""


def _children_cpu_seconds() -> float:
    """User plus system time of reaped children, at microsecond resolution.

    os.times() reports children in clock ticks (10 ms on Linux), which cannot
    resolve a 14 ms compile; getrusage carries the kernel's timeval.
    """

    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def _run_timed(command: list[str], env: dict[str, str], cwd: Path) -> Timing:
    before = _children_cpu_seconds()
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - started
    cpu = _children_cpu_seconds() - before
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed ({completed.returncode}):\n{completed.stderr[:2000]}")
    return Timing(wall * 1000.0, cpu * 1000.0, completed.stdout, completed.stderr)


def best(command: list[str], env: dict[str, str], cwd: Path, repeat: int) -> tuple[Timing, list[Timing]]:
    """Best-of-N wall and CPU time; the minimum is the stable estimator on a shared host."""

    samples = [_run_timed(command, env, cwd) for _ in range(repeat)]
    fastest = min(samples, key=lambda sample: sample.wall_ms)
    return Timing(fastest.wall_ms, min(sample.cpu_ms for sample in samples), fastest.stdout, fastest.stderr), samples


@dataclass(frozen=True)
class Peak:
    """One process's peak memory in bytes, and which counter reported it."""

    bytes: int
    source: str  # "footprint" or "maxrss"


def measure_peak(command: list[str], env: dict[str, str], cwd: Path) -> Peak:
    """The peak memory of one run of `command`, which must succeed.

    On macOS it is the peak footprint `/usr/bin/time -l` reports, the number the
    M11 budget is written in. Elsewhere it is the child's own maximum resident
    set from wait4 (KiB on Linux), which a reaped sibling cannot inflate the way
    RUSAGE_CHILDREN's running maximum would. Standard output is discarded.
    """

    if peak_counter() == "footprint":
        completed = subprocess.run(
            [str(TIME), "-l", *command],
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        if completed.returncode != 0:
            raise RuntimeError(f"{' '.join(command)} failed ({completed.returncode}):\n{completed.stderr[-2000:]}")
        found = FOOTPRINT.search(completed.stderr)
        if found is None:
            raise RuntimeError(f"{TIME} -l reported no peak memory footprint:\n{completed.stderr[-2000:]}")
        return Peak(int(found.group(1)), "footprint")
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=errors)
        _, status, usage = os.wait4(process.pid, 0)
        process.returncode = os.waitstatus_to_exitcode(status)
        if process.returncode != 0:
            errors.seek(0)
            detail = errors.read().decode(errors="replace")[-2000:]
            raise RuntimeError(f"{' '.join(command)} failed ({process.returncode}):\n{detail}")
    return Peak(usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024), "maxrss")


def peak_counter() -> str:
    """Which counter measure_peak reads on this host."""

    return "footprint" if sys.platform == "darwin" and TIME.is_file() else "maxrss"


def host_target() -> str | None:
    """btrcc's `--target` name for this host, when it has one."""

    system = {"darwin": "macos", "linux": "linux"}.get(sys.platform)
    machine = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "amd64": "x64"}.get(platform.machine().lower())
    return f"{system}-{machine}" if system and machine else None


@dataclass(frozen=True)
class Workload:
    """A pinned whole program whose cold `--jobs 1` compile peak is guarded.

    The command is tools/budget_bench.py's memory scenario, the compile the M11
    peak budget is written for: module units with debug info and one worker,
    into empty artifact caches. The workspace is read, never written; caches
    and outputs go under the suite's scratch directory.
    """

    workspace: Path
    entry: str = "src/BTRSmith.btrc"
    target: str | None = None

    @property
    def name(self) -> str:
        return Path(self.entry).stem

    @property
    def metric(self) -> str:
        return f"btrcc.workload.{self.name}_peak"

    def command(self, btrcc: Path, build: Path) -> list[str]:
        command = [str(btrcc), "--jobs", "1", "--strict-imports"]
        if self.target:
            command += ["--target", self.target]
        return [
            *command,
            "--debug",
            "--emit-link-plan",
            str(build / "p.json"),
            "--emit-units",
            str(build / "p"),
            "--module-units",
            self.entry,
            "-o",
            str(build / "p.c"),
        ]


def phase_times(stderr: str) -> dict[str, float]:
    """Sum the self-host's BTRCC_TIMING marks per phase, in milliseconds."""

    phases: dict[str, float] = {}
    for line in stderr.splitlines():
        if not line.startswith("btrcc timing: "):
            continue
        for item in line[len("btrcc timing: ") :].split():
            name, _, value = item.partition("=")
            if value.endswith("us"):
                phases[name] = phases.get(name, 0.0) + int(value[:-2]) / 1000.0
    return phases


@dataclass
class Suite:
    btrcc: Path
    cc: list[str]
    repeat: int
    out_dir: Path
    reference: bool = True
    peaks: bool = True
    peak_only: bool = False
    workloads: list[Workload] = field(default_factory=list)
    workload_samples: int = 1
    metrics: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env["BTRC_HOME"] = str(REPO / "src")
        env["BTRCC_TIMING"] = "1"
        return env

    def peak_environment(self) -> dict[str, str]:
        """As a developer compiles: no phase timing report held in memory."""

        env = {name: value for name, value in os.environ.items() if name not in TIMING_VARIABLES}
        env["BTRC_HOME"] = str(REPO / "src")
        return env

    def run(self, programs: list[Program]) -> dict[str, float]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        env = self.environment()
        if not self.peak_only:
            startup, _ = best([str(self.btrcc), "--stdlib-dir"], env, REPO, max(self.repeat, 10))
            self.metrics["btrcc.startup_ms"] = round(startup.wall_ms, 3)
        for program in programs:
            if not self.peak_only:
                self._program(program, env)
            if self.peaks:
                self._program_peak(program)
        for workload in self.workloads:
            self._workload_peak(workload)
        return self.metrics

    def _program_peak(self, program: Program) -> None:
        """The compile's peak memory, the lowest of up to three samples."""

        command = [str(self.btrcc), str(program.path)]
        samples = [measure_peak(command, self.peak_environment(), REPO) for _ in range(max(1, min(self.repeat, 3)))]
        self.metrics[f"btrcc.compile.{program.name}_peak"] = min(sample.bytes for sample in samples)

    def _workload_peak(self, workload: Workload) -> None:
        """The workload's cold compile peak, the lowest of its samples."""

        scratch = self.out_dir / "workloads" / workload.name
        samples: list[Peak] = []
        for _ in range(max(1, self.workload_samples)):
            shutil.rmtree(scratch, ignore_errors=True)
            (scratch / "cache").mkdir(parents=True)
            (scratch / "build").mkdir()
            env = {**self.peak_environment(), "BTRC_CACHE_DIR": str(scratch / "cache")}
            samples.append(measure_peak(workload.command(self.btrcc, scratch / "build"), env, workload.workspace))
        shutil.rmtree(scratch, ignore_errors=True)
        lowest = min(samples, key=lambda sample: sample.bytes)
        self.metrics[workload.metric] = lowest.bytes
        self.notes.append(
            f"{workload.name}: cold --jobs 1 peak {lowest.source} {lowest.bytes} bytes ({lowest.bytes / 2**30:.3f} GiB)"
        )

    def _program(self, program: Program, env: dict[str, str]) -> None:
        name = program.name
        compiled, _ = best([str(self.btrcc), str(program.path)], env, REPO, self.repeat)
        self.metrics[f"btrcc.compile.{name}_ms"] = round(compiled.wall_ms, 3)
        self.metrics[f"btrcc.compile.{name}_cpu_ms"] = round(compiled.cpu_ms, 3)
        if program.phases:
            for phase, millis in phase_times(compiled.stderr).items():
                self.metrics[f"btrcc.phase.{name}.{phase}_ms"] = round(millis, 3)
        c_source = compiled.stdout
        c_path = self.out_dir / f"{name}.c"
        c_path.write_text(c_source, encoding="utf-8")
        self.metrics[f"c.{name}.bytes"] = len(c_source.encode("utf-8"))
        self.metrics[f"c.{name}.lines"] = c_source.count("\n")
        reference_c = None
        if self.reference:
            reference_ms, reference_c = self._reference(program)
            self.metrics[f"reference.compile.{name}_ms"] = round(reference_ms, 3)
        for level in ("O0", "O2"):
            binary = self.out_dir / f"{name}.{level}"
            command = [*self.cc, *CFLAGS, f"-{level}", str(c_path), "-o", str(binary), *LIBS]
            timing, _ = best(command, env, REPO, self.repeat if level == "O0" else 1)
            self.metrics[f"cc.{name}.{level}_ms"] = round(timing.wall_ms, 3)
            if level == "O2":
                self.metrics[f"binary.{name}.bytes"] = binary.stat().st_size
        ran, _ = best([str(self.out_dir / f"{name}.O2")], env, self.out_dir, max(self.repeat, 5) if program.runs else 1)
        if program.runs:
            self.metrics[f"run.{name}_ms"] = round(ran.wall_ms, 3)
            self.metrics[f"run.{name}_cpu_ms"] = round(ran.cpu_ms, 3)
        if reference_c is not None:
            # Both compilers must build a program that behaves identically. The
            # C text itself legitimately differs (temporary numbering), so the
            # contract is the program's output.
            reference_path = self.out_dir / f"{name}.reference.c"
            reference_path.write_text(reference_c, encoding="utf-8")
            reference_binary = self.out_dir / f"{name}.reference"
            _run_timed([*self.cc, *CFLAGS, "-O2", str(reference_path), "-o", str(reference_binary), *LIBS], env, REPO)
            reference_run = _run_timed([str(reference_binary)], env, self.out_dir)
            parity = 1 if reference_run.stdout == ran.stdout else 0
            self.metrics[f"c.{name}.parity"] = parity
            if not parity:
                self.notes.append(
                    f"{name}: reference and self-host programs print different output; see {self.out_dir}"
                )

    def _reference(self, program: Program) -> tuple[float, str]:
        """In-process reference transpile, best of N after one warm-up."""

        if str(REPO) not in sys.path:
            sys.path.insert(0, str(REPO))
        from src.compiler.python import Compiler, CompilerOptions
        from src.compiler.python.ir.lowering.lowerer import IRLowerer

        compiler = Compiler()
        source = program.path.read_text(encoding="utf-8")

        def transpile() -> str:
            options = CompilerOptions(map_stdlib_positions=True)
            frontend = compiler.compile_frontend(source, str(program.path), options, filename=program.path.name)
            if frontend.analyzed.errors:
                raise RuntimeError(f"{program.name}: reference analyzer errors: {frontend.analyzed.errors}")
            source_map = frontend.source_bundle.source_map(
                split_spaces=bool(frontend.stdlib_source and frontend.user_program is not None),
            )
            module = IRLowerer(
                frontend.analyzed, source_file=program.path.name, source_map=source_map, prune_stdlib=options.dce
            ).lower()
            module = compiler.pipeline.optimize(module, options)
            return compiler.pipeline.emit(module)

        emitted = transpile()
        fastest = float("inf")
        for _ in range(self.repeat):
            started = time.perf_counter()
            transpile()
            fastest = min(fastest, (time.perf_counter() - started) * 1000.0)
        return fastest, emitted


def default_cc() -> list[str]:
    configured = os.environ.get("BTRC_CC")
    if configured:
        return shlex.split(configured)
    if sys.platform == "darwin" and shutil.which("clang"):
        return ["clang"]
    return ["cc"]
