"""Measurements: what the suite times and how it times it."""

from __future__ import annotations

import os
import resource
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PROGRAMS = REPO / "src" / "tests" / "benchmarks"
CFLAGS = shlex.split(os.environ.get("BTRC_CFLAGS", "-std=c11 -pedantic"))
LIBS = ["-lm", "-lpthread"]


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
    metrics: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        env["BTRC_HOME"] = str(REPO / "src")
        env["BTRCC_TIMING"] = "1"
        return env

    def run(self, programs: list[Program]) -> dict[str, float]:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        env = self.environment()
        startup, _ = best([str(self.btrcc), "--stdlib-dir"], env, REPO, max(self.repeat, 10))
        self.metrics["btrcc.startup_ms"] = round(startup.wall_ms, 3)
        for program in programs:
            self._program(program, env)
        return self.metrics

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
