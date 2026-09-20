"""Measure one program's build: both btrc compilers by phase, peak memory, the
emitted C's shape, and the C compiler on that output.

    python3 -m tools.perf ../btrsmith/src/BTRSmith.btrc --json build/perf/btrsmith.json

Runs inside the dev shell that provides the program's packages (BTRSmith needs
its own `nix develop`). Each compiler runs once under BTRC_TIMING=1 in a fresh
measuring process so peak RSS is that process alone. The emitted unit is then
compiled with the C compiler at each requested optimisation level, using the
link plan's pkg-config packages, defines and include directories, which is
what btrc-native-plan would pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PHASES = ("analyze", "lower", "optimize", "emit")
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


@dataclass
class CompilerRun:
    frontend: str
    wall_s: float
    cpu_s: float
    max_rss_kb: int
    phases_s: dict[str, float]
    generated_c: str
    plan: str


@dataclass
class CStats:
    lines: int
    bytes: int
    functions: int
    structs: int
    vector_instances: int
    line_directives: int


@dataclass
class CompileRun:
    compiler: str
    optimisation: str
    wall_s: float
    max_rss_kb: int
    object_bytes: int


@dataclass
class Report:
    program: str
    target: str
    compilers: list[CompilerRun] = field(default_factory=list)
    c_stats: dict[str, CStats] = field(default_factory=dict)
    c_compiles: list[CompileRun] = field(default_factory=list)


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
        "'max_rss_kb': usage.ru_maxrss, 'returncode': code}))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", runner, json.dumps(command), str(stdout), str(stderr)],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return Measurement(**json.loads(completed.stdout))


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


def plan_cflags(plan_path: Path, pkg_config: str) -> list[str]:
    """The compile flags btrc-native-plan derives from a link plan."""

    plan = json.loads(plan_path.read_text())
    flags: list[str] = []
    packages = sorted({entry["name"] for entry in plan.get("pkg-config", [])})
    if packages:
        completed = subprocess.run([pkg_config, "--cflags", *packages], capture_output=True, text=True, check=True)
        flags.extend(shlex.split(completed.stdout))
    for entry in plan.get("defines", []):
        value = entry.get("value")
        flags.append(f"-D{entry['name']}={value}" if value not in (None, "") else f"-D{entry['name']}")
    for entry in plan.get("include-directories", []):
        flags.append("-I" + (entry if isinstance(entry, str) else entry["path"]))
    return flags


class Perf:
    def __init__(self, arguments: argparse.Namespace) -> None:
        self.arguments = arguments
        self.program = Path(arguments.program).resolve()
        self.out = Path(arguments.out).resolve() if arguments.out else REPO / "build" / "perf" / self.program.stem
        self.out.mkdir(parents=True, exist_ok=True)
        self.env = {**os.environ, "BTRC_TIMING": "1", "BTRC_HOME": str(REPO / "src")}
        self.report = Report(str(self.program), arguments.target)

    def compiler_command(self, frontend: str, generated: Path, plan: Path) -> list[str]:
        if frontend == "btrcpy":
            return [
                sys.executable,
                "-m",
                "src.compiler.python.main",
                "--no-cache",
                "--strict-imports",
                "--target",
                self.arguments.target,
                "--emit-link-plan",
                str(plan),
                str(self.program),
                "-o",
                str(generated),
            ]
        return [
            str(Path(self.arguments.btrcc).resolve()),
            "--strict-imports",
            "--target",
            self.arguments.target,
            "--emit-link-plan",
            str(plan),
            str(self.program),
        ]

    def run_compiler(self, frontend: str) -> CompilerRun:
        generated = self.out / f"{self.program.stem}.{frontend}.c"
        plan = self.out / f"{self.program.stem}.{frontend}.link.json"
        stdout = self.out / f"{frontend}.stdout"
        stderr = self.out / f"{frontend}.stderr"
        measured = measure(self.compiler_command(frontend, generated, plan), self.env, REPO, stdout, stderr)
        if measured.returncode != 0:
            raise SystemExit(f"{frontend} failed ({measured.returncode}):\n{stderr.read_text()[-3000:]}")
        if frontend == "btrcc":
            generated.write_bytes(stdout.read_bytes())
        run = CompilerRun(
            frontend,
            measured.wall_s,
            measured.cpu_s,
            measured.max_rss_kb,
            phase_times(stderr.read_text()),
            str(generated),
            str(plan),
        )
        self.report.compilers.append(run)
        self.report.c_stats[frontend] = c_stats(generated)
        return run

    def run_c_compiler(self, source: Path, plan: Path) -> None:
        flags = plan_cflags(plan, self.arguments.pkg_config)
        for level in self.arguments.opt:
            obj = self.out / f"{source.stem}.{level}.o"
            command = [self.arguments.cc, "-std=c11", "-w", f"-{level}", *flags, "-c", str(source), "-o", str(obj)]
            measured = measure(
                command, self.env, REPO, self.out / f"cc.{level}.stdout", self.out / f"cc.{level}.stderr"
            )
            if measured.returncode != 0:
                raise SystemExit(
                    f"{self.arguments.cc} -{level} failed:\n{(self.out / f'cc.{level}.stderr').read_text()[-3000:]}"
                )
            self.report.c_compiles.append(
                CompileRun(self.arguments.cc, level, measured.wall_s, measured.max_rss_kb, obj.stat().st_size)
            )

    def run(self) -> Report:
        for frontend in self.arguments.frontends:
            self.run_compiler(frontend)
        primary = self.report.compilers[-1]
        self.run_c_compiler(Path(primary.generated_c), Path(primary.plan))
        return self.report

    def markdown(self) -> str:
        report = self.report
        rows = [f"### {Path(report.program).name} ({report.target})", ""]
        rows.append("| Compiler | Wall | CPU | Peak RSS | front end | analyze | lower | optimize | emit |")
        rows.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for run in report.compilers:
            named = {phase: run.phases_s.get(phase, 0.0) for phase in PHASES}
            front = sum(run.phases_s.values()) - sum(named.values())
            rows.append(
                f"| {run.frontend} | {run.wall_s:.1f} s | {run.cpu_s:.1f} s | {run.max_rss_kb / 1024:.0f} MB | {front:.1f} s | "
                + " | ".join(f"{named[phase]:.1f} s" for phase in PHASES)
                + " |"
            )
        rows.append("")
        rows.append("| Output | Lines | Bytes | Functions | Structs | Vector instances | #line |")
        rows.append("| --- | --- | --- | --- | --- | --- | --- |")
        for frontend, stats in report.c_stats.items():
            rows.append(
                f"| {frontend} | {stats.lines:,} | {stats.bytes / 1_000_000:.1f} MB | {stats.functions:,} | {stats.structs:,} | {stats.vector_instances} | {stats.line_directives} |"
            )
        rows.append("")
        rows.append("| C compiler | Wall | Peak RSS | Object |")
        rows.append("| --- | --- | --- | --- |")
        for compile in report.c_compiles:
            rows.append(
                f"| {compile.compiler} -{compile.optimisation} | {compile.wall_s:.1f} s | {compile.max_rss_kb / 1024:.0f} MB | {compile.object_bytes / 1_000_000:.1f} MB |"
            )
        return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("program", help="the .btrc entry point to build")
    parser.add_argument("--btrcc", default=str(REPO / "bin" / "btrcc"))
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--pkg-config", default="pkg-config")
    parser.add_argument("--target", default="linux-x86_64")
    parser.add_argument(
        "--frontends", default="btrcpy,btrcc", help="comma-separated: btrcpy, btrcc (last one feeds the C compiler)"
    )
    parser.add_argument("--opt", default="O0,O2", help="comma-separated C optimisation levels to time")
    parser.add_argument("--out", help="working directory (default build/perf/<program>)")
    parser.add_argument("--json", help="write the report here")
    arguments = parser.parse_args(argv)
    arguments.frontends = [name for name in arguments.frontends.split(",") if name]
    arguments.opt = [level for level in arguments.opt.split(",") if level]
    perf = Perf(arguments)
    started = time.perf_counter()
    perf.run()
    table = perf.markdown()
    print(table)
    print(f"({time.perf_counter() - started:.0f} s in total; working files in {perf.out})")
    if arguments.json:
        path = Path(arguments.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(perf.report), indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
