"""Measure PLAN.md's bucket-1 BTRSmith budgets with the self-hosted compiler.

    nix develop <btrsmith dev shell> --command python3 -m tools.budget_bench \\
        --btrcc build/btrcc --workspace ~/.cache/btrc/bsm-measure --out ~/.cache/btrc/bench/run

Run it where BTRSmith builds: PKG_CONFIG_PATH names its packages and
BTRC_NATIVE_HEADER_READER, BTRC_NATIVE_TARGET and BTRC_NATIVE_SYSROOT name the
native header reader. The workspace is copied, never edited in place.

A build is what a developer runs: btrcc --module-units --debug with default
workers, then tools/native_plan at -O0 with debug info and the object cache
at 8 native jobs, executable included. Times are wall seconds from command
entry until the artifact exists. Cold scenarios take 5 samples and
incremental ones 20; every sample is printed with the median, the
nearest-rank p95 and the maximum, as PLAN's "Numeric acceptance budgets"
requires.

- cold-transpile: the compiler alone with empty btrc artifact caches.
- cold-dev: empty caches, objects and output, executable included.
- edit-<fixture>: a real private-body change in a named product module;
  every sample writes source the run has not built before, so none is
  answered from the artifact cache. After a fixture's samples, a clean build
  of the same tree must emit the same function bodies and its executable must
  print the same smoke output.
- noop: nothing changed.
- touch: one source rewritten with identical bytes.
- memory: btrcc's peak footprint for a cold --jobs 1 compile, and the
  process tree's summed RSS sampled every 100 ms through a cold dev build.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENTRY = "src/BTRSmith.btrc"
NATIVE_JOBS = 8
SMOKE_ENVIRONMENT = {"BTRSMITH_SMOKE_FRAMES": "3", "BTRSMITH_SMOKE_POLL_LIMIT": "600", "BTRSMITH_SMOKE_CYCLES": "1"}
RESOURCES = ("Rosewood.png", "StratocasterBody.png", "DreadnoughtBody.png")

# (name, module, text, template): sample n replaces the text with the
# template filled with n, so every sample writes source no earlier build of
# the run has seen and no build is answered from the artifact cache.
FIXTURES = (
    (
        "navigation",
        "src/frontend/library/AlbumGrid.btrc",
        "self._artworkStatus.arrange(12.0, 12.0,",
        "self._artworkStatus.arrange(12.{n:04d}, 12.0,",
    ),
    (
        "ui-controller",
        "src/frontend/player/UiPlayerTransport.btrc",
        "int rounded = (int)(percent + 0.5);",
        "int rounded = (int)(percent + 0.5{n:04d});",
    ),
    (
        "audio-preparation",
        "src/backend/audio/PlaybackPreparation.btrc",
        "int chunkFrames = 8192;",
        "int chunkFrames = {chunk};",
    ),
)
TOUCHED = "src/frontend/player/UiPlayerTransport.btrc"

_FUNCTION_HEADER = re.compile(r"^[A-Za-z_][\w\s*]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{$")
_SESSION_NAME = re.compile(r"\b(?:__[A-Za-z]\w*?\d+\w*|[A-Za-z]\w*_\d+)\b")


@dataclass
class Scenario:
    name: str
    samples: list[float] = field(default_factory=list)
    parts: list[tuple[float, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, object]:
        ordered = sorted(self.samples)
        rank = max(1, math.ceil(0.95 * len(ordered)))
        return {
            "samples": [round(value, 3) for value in self.samples],
            "compile_native": [(round(a, 3), round(b, 3)) for a, b in self.parts],
            "median": round(statistics.median(ordered), 3) if ordered else None,
            "p95": round(ordered[rank - 1], 3) if ordered else None,
            "max": round(ordered[-1], 3) if ordered else None,
            "notes": self.notes,
        }


class BudgetBench:
    """Drive one copied workspace through every budget scenario."""

    def __init__(self, arguments: argparse.Namespace) -> None:
        self.btrcc = Path(arguments.btrcc).resolve()
        self.out = Path(arguments.out).resolve()
        self.cold_samples = arguments.cold_samples
        self.incremental_samples = arguments.incremental_samples
        self.scenarios = arguments.scenarios.split(",")
        self.workspace = self.out / "ws"
        self.results: dict[str, Scenario] = {}
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        shutil.copytree(Path(arguments.workspace).expanduser(), self.workspace, symlinks=True)
        self.edits = {name: 0 for name, *_ in FIXTURES}

    def paths(self, state: str) -> dict[str, Path]:
        root = self.out / state
        return {"cache": root / "cache", "objects": root / "objects", "build": root / "build"}

    def reset(self, state: str, *, objects: bool) -> None:
        paths = self.paths(state)
        shutil.rmtree(paths["cache"], ignore_errors=True)
        shutil.rmtree(paths["build"], ignore_errors=True)
        if objects:
            shutil.rmtree(paths["objects"], ignore_errors=True)
        for path in paths.values():
            path.mkdir(parents=True, exist_ok=True)

    def compile(self, state: str, *, jobs: int | None = None, timing: Path | None = None) -> float:
        paths = self.paths(state)
        build = paths["build"]
        command = [
            str(self.btrcc),
            "--strict-imports",
            "--target",
            "macos-arm64",
            "--debug",
            "--emit-link-plan",
            str(build / "p.json"),
            "--emit-units",
            str(build / "p"),
            "--module-units",
            ENTRY,
            "-o",
            str(build / "p.c"),
        ]
        if jobs is not None:
            command[1:1] = ["--jobs", str(jobs)]
        environment = {**os.environ, "BTRC_HOME": str(REPO / "src"), "BTRC_CACHE_DIR": str(paths["cache"])}
        if timing is not None:
            environment["BTRC_TIMING"] = "1"
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=self.workspace, env=environment, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        if timing is not None:
            timing.write_text(completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError(f"btrcc failed ({completed.returncode}):\n{completed.stderr[-4000:]}")
        return elapsed

    def native(self, state: str) -> float:
        paths = self.paths(state)
        build = paths["build"]
        command = [
            sys.executable,
            "-m",
            "tools.native_plan",
            "--plan",
            str(build / "p.json"),
            "--generated-c",
            str(build / "p.c"),
            "--output",
            str(build / "BTRSmith"),
            "--cc",
            "clang",
            "--cxx",
            "clang++",
            "--jobs",
            str(NATIVE_JOBS),
            "--debug-info",
            "--optimization",
            "0",
            "--object-cache",
            str(paths["objects"]),
        ]
        environment = {**os.environ, "PYTHONPATH": str(REPO)}
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=self.workspace, env=environment, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        if completed.returncode != 0:
            raise RuntimeError(f"native plan failed ({completed.returncode}):\n{completed.stderr[-4000:]}")
        return elapsed

    def build(self, state: str, label: str | None = None) -> tuple[float, float]:
        """Compile and build natively; `label` keeps the compile's phase timing."""
        timing = None
        if label is not None:
            (self.out / "timing").mkdir(exist_ok=True)
            timing = self.out / "timing" / f"{label}.txt"
        return self.compile(state, timing=timing), self.native(state)

    def record(self, scenario: Scenario, compile_s: float, native_s: float) -> None:
        scenario.samples.append(compile_s + native_s)
        scenario.parts.append((compile_s, native_s))
        index = len(scenario.samples)
        print(
            f"  {scenario.name} #{index}: {compile_s + native_s:7.2f} s (compile {compile_s:6.2f} + native {native_s:6.2f})",
            flush=True,
        )

    def edit(self, fixture: str) -> None:
        name, module, original, template = next(item for item in FIXTURES if item[0] == fixture)
        path = self.workspace / module
        text = path.read_text()
        previous = self.edits[name]
        current = template.format(n=previous, chunk=8192 - previous) if previous else original
        self.edits[name] = previous + 1
        replacement = template.format(n=previous + 1, chunk=8192 - previous - 1)
        if text.count(current) != 1:
            raise RuntimeError(f"edit anchor for {name} is not unique in {module}")
        path.write_text(text.replace(current, replacement, 1))

    @staticmethod
    def function_bodies(directory: Path) -> dict[str, set[str]]:
        """Every function body in a build's C, independent of how units split it."""
        bodies: dict[str, set[str]] = {}
        for unit in sorted(directory.glob("p*.c")):
            lines = unit.read_text(errors="replace").split("\n")
            index = 0
            while index < len(lines):
                header = _FUNCTION_HEADER.match(lines[index])
                if header is None:
                    index += 1
                    continue
                end = lines.index("}", index + 1)
                body = "".join(line for line in lines[index + 1 : end] if not line.startswith("#line"))
                name = _SESSION_NAME.sub("_", header.group(1))
                bodies.setdefault(name, set()).add(re.sub(r"\s+", "", _SESSION_NAME.sub("_", body)))
                index = end + 1
        return bodies

    def smoke(self, executable: Path, label: str) -> str:
        layout = self.out / f"smoke-{label}"
        shutil.rmtree(layout, ignore_errors=True)
        (layout / "bin").mkdir(parents=True)
        (layout / "share/btrsmith").mkdir(parents=True)
        (layout / "state").mkdir(mode=0o700)
        for name in RESOURCES:
            shutil.copy2(self.workspace / "packaging/assets" / name, layout / "share/btrsmith" / name)
        shutil.copy2(executable, layout / "bin/BTRSmith")
        environment = {
            **os.environ,
            **SMOKE_ENVIRONMENT,
            "BTRSMITH_STATE_DIRECTORY": str(layout / "state"),
            "BTRSMITH_CATALOG_PATH": str(layout / "state/catalog.sqlite"),
        }
        completed = subprocess.run(
            [str(layout / "bin/BTRSmith")], cwd=layout, env=environment, capture_output=True, text=True, timeout=300
        )
        return f"exit {completed.returncode}\n{completed.stdout}"

    def verify_against_clean(self, scenario: Scenario) -> None:
        """A clean build of the current tree must match the incremental one."""
        warm = self.paths("warm")["build"]
        incremental_bodies = self.function_bodies(warm)
        incremental_smoke = self.smoke(warm / "BTRSmith", "incremental")
        self.reset("clean", objects=True)
        self.build("clean")
        clean = self.paths("clean")["build"]
        clean_bodies = self.function_bodies(clean)
        clean_smoke = self.smoke(clean / "BTRSmith", "clean")
        same_bodies = clean_bodies == incremental_bodies
        same_smoke = clean_smoke == incremental_smoke and "PASS" in clean_smoke
        scenario.notes.append(
            f"clean-build check: {len(clean_bodies)} functions, bodies {'equal' if same_bodies else 'DIFFER'}; "
            f"smoke {'equal' if same_smoke else 'DIFFERS'}: {clean_smoke.strip()!r}"
        )
        print(f"  {scenario.notes[-1]}", flush=True)
        if not (same_bodies and same_smoke):
            raise RuntimeError(f"{scenario.name}: incremental build differs from a clean build")
        shutil.rmtree(self.out / "clean", ignore_errors=True)

    def run_cold(self) -> None:
        transpile = Scenario("cold-transpile")
        for _ in range(self.cold_samples):
            self.reset("cold", objects=True)
            self.record(transpile, self.compile("cold"), 0.0)
        self.results[transpile.name] = transpile
        dev = Scenario("cold-dev")
        for _ in range(self.cold_samples):
            self.reset("cold", objects=True)
            self.record(dev, *self.build("cold"))
        self.results[dev.name] = dev

    def run_incremental(self) -> None:
        self.reset("warm", objects=True)
        print("  priming the warm state", flush=True)
        self.build("warm")
        self.build("warm")
        for fixture, *_ in FIXTURES:
            if f"edit-{fixture}" not in self.scenarios and "edit" not in self.scenarios:
                continue
            scenario = Scenario(f"edit-{fixture}")
            for index in range(self.incremental_samples):
                self.edit(fixture)
                self.record(scenario, *self.build("warm", f"{scenario.name}-{index + 1}"))
            self.verify_against_clean(scenario)
            self.results[scenario.name] = scenario
        if "noop" in self.scenarios:
            scenario = Scenario("noop")
            for index in range(self.incremental_samples):
                self.record(scenario, *self.build("warm", f"noop-{index + 1}"))
            self.results[scenario.name] = scenario
        if "touch" in self.scenarios:
            scenario = Scenario("touch")
            path = self.workspace / TOUCHED
            for _ in range(self.incremental_samples):
                path.write_bytes(path.read_bytes())
                self.record(scenario, *self.build("warm"))
            self.results[scenario.name] = scenario

    def run_memory(self) -> None:
        scenario = Scenario("memory")
        self.reset("memory", objects=True)
        paths = self.paths("memory")
        timing = self.out / "memory-time.txt"
        command = [
            "/usr/bin/time",
            "-l",
            str(self.btrcc),
            "--jobs",
            "1",
            "--strict-imports",
            "--target",
            "macos-arm64",
            "--debug",
            "--emit-link-plan",
            str(paths["build"] / "p.json"),
            "--emit-units",
            str(paths["build"] / "p"),
            "--module-units",
            ENTRY,
            "-o",
            str(paths["build"] / "p.c"),
        ]
        environment = {**os.environ, "BTRC_HOME": str(REPO / "src"), "BTRC_CACHE_DIR": str(paths["cache"])}
        completed = subprocess.run(command, cwd=self.workspace, env=environment, capture_output=True, text=True)
        timing.write_text(completed.stderr)
        footprint = re.search(r"(\d+)\s+peak memory footprint", completed.stderr)
        instructions = re.search(r"(\d+)\s+instructions retired", completed.stderr)
        peak = int(footprint.group(1)) if footprint else -1
        scenario.notes.append(f"btrcc --jobs 1 peak footprint {peak} bytes ({peak / 2**30:.3f} GiB)")
        if instructions:
            scenario.notes.append(f"btrcc --jobs 1 instructions retired {int(instructions.group(1)):,}")
        self.reset("memory", objects=True)
        aggregate = self.sample_aggregate(lambda: self.build("memory"))
        scenario.notes.append(
            f"cold dev build sampled aggregate RSS peak {aggregate} bytes ({aggregate / 2**30:.3f} GiB)"
        )
        for note in scenario.notes:
            print(f"  memory: {note}", flush=True)
        self.results[scenario.name] = scenario

    @staticmethod
    def sample_aggregate(action) -> int:
        """Run `action` while summing the RSS of this process's descendants."""
        root = os.getpid()
        peak = 0
        done = threading.Event()

        def sampler() -> None:
            nonlocal peak
            while not done.is_set():
                listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True).stdout
                children: dict[int, list[int]] = {}
                rss: dict[int, int] = {}
                for line in listing.split("\n"):
                    parts = line.split()
                    if len(parts) != 3:
                        continue
                    pid, ppid, kilobytes = map(int, parts)
                    children.setdefault(ppid, []).append(pid)
                    rss[pid] = kilobytes * 1024
                pending = list(children.get(root, []))
                total = 0
                while pending:
                    pid = pending.pop()
                    total += rss.get(pid, 0)
                    pending.extend(children.get(pid, []))
                peak = max(peak, total)
                done.wait(0.1)

        thread = threading.Thread(target=sampler, daemon=True)
        thread.start()
        try:
            action()
        finally:
            done.set()
            thread.join()
        return peak

    def run(self) -> dict[str, object]:
        if "cold" in self.scenarios:
            self.run_cold()
        if any(name.startswith(("edit", "noop", "touch")) for name in self.scenarios):
            self.run_incremental()
        if "memory" in self.scenarios:
            self.run_memory()
        report = {name: scenario.summary() for name, scenario in self.results.items()}
        (self.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print("\nscenario            median     p95     max  samples")
        for name, summary in report.items():
            if summary["median"] is None:
                continue
            print(
                f"{name:18} {summary['median']:7.2f} {summary['p95']:7.2f} {summary['max']:7.2f}  {len(summary['samples'])}"
            )
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--btrcc", required=True)
    parser.add_argument("--workspace", required=True, help="the pinned BTRSmith checkout; copied, never edited")
    parser.add_argument("--out", required=True, help="run directory, replaced")
    parser.add_argument("--scenarios", default="cold,edit,noop,touch,memory")
    parser.add_argument("--cold-samples", type=int, default=5)
    parser.add_argument("--incremental-samples", type=int, default=20)
    BudgetBench(parser.parse_args(argv)).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
