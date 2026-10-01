"""Measure PLAN.md's bucket-1 BTRSmith budgets on either frontend.

    tools/bench/scripts/bench.sh <btrc-tree> <btrcc> <out> [options]

runs, inside BTRSmith's dev shell (tools/bench/scripts/bsm_env.sh)::

    python3 -m tools.budget_bench --btrcc build/btrcc --workspace ~/.cache/btrc/bsm-measure \\
        --out ~/.cache/btrc/bench.noindex/run [--frontend reference] [--scenarios all]

Run it where BTRSmith builds: PKG_CONFIG_PATH names its packages and
BTRC_NATIVE_HEADER_READER, BTRC_NATIVE_TARGET and BTRC_NATIVE_SYSROOT name the
native header reader. The workspace is copied, never edited in place; --out is
replaced only when it is empty or an earlier run of this tool.

A build is what a developer runs, timed in wall seconds from command entry
until the artifact exists. --frontend selfhost runs --btrcc; reference runs
this checkout's Python compiler. --mode dev compiles with --debug and builds
natively at -O0 with debug info; --mode release uses neither, at the native
plan's -O2, as BTRSmith's make/Config.mk does. --units module (the dev
default) lowers one translation unit per compilation group; whole (the release
default) is Config.mk's whole-program --emit-units split. --entry direct runs
the compiler, then tools/native_plan with an object cache at --native-jobs;
--entry make runs BTRSmith's own `make -f make/Product.mk btrsmith-native`
with the same compiler, flags and native builder, because acceptance is
measured from the build command. --target defaults to the host as Config.mk
spells it. Cold scenarios take --cold-samples (5) and incremental ones
--incremental-samples (20); every sample is reported with the median, the
nearest-rank p95 and the maximum, as PLAN's "Numeric acceptance budgets"
requires; tools.qualification.statistics computes them. --dry-run takes one
sample of each and marks the report.

Scenarios (--scenarios, comma-separated, or `all`):

- cold: cold-transpile, the compiler alone with empty btrc artifact caches,
  and cold-<mode>: empty caches, objects and output, executable included.
  --timing-cold keeps every cold build's BTRC_TIMING owner and worker lines.
- edit, or edit-<fixture>: a real private-body change in a named product
  module; every sample writes source the run has not built before, so none is
  answered from the artifact cache. After a fixture's samples, a clean build
  of the same tree must emit the same function bodies and its executable must
  print the same smoke output.
- instance-edit: a body edit that adds a generic instance and a stdlib call
  the program lacked. Each sample starts from the restored original, rebuilt
  untimed, so every timed build adds both; the build must show a new instance
  type and the new call, and the clean-build check follows.
- interface-edit: a public layout change in a widely imported domain class,
  --cold-samples times. A clean build of each changed tree must match the
  incremental one, which may take at most 110% of the clean build.
- noop: nothing changed. touch: one source rewritten with identical bytes.
- memory: the compiler's peak for one cold --jobs 1 compile (/usr/bin/time -l
  on macOS, -v on Linux), and the process tree's summed RSS sampled every
  100 ms through a cold build.
- release: cold release builds, whole-program and module-unit; the module-unit
  build may take at most 110% of the whole-program one.
- batch: the --batch-manifest's ten entry points, built after priming only the
  shared application dependencies (a product build's caches and objects);
  build and test execution are recorded separately.
- workers: cold module-unit builds at each --workers count (1,2,4,8) with
  --native-jobs fixed, with the compiler's peak and the sampled process-tree
  RSS of the compile and the native build (M10).
- self-compile: the frontend compiling the self-hosted compiler for this host
  (--target included), transpile only.
- corpus: the frontend transpiling every runnable corpus program, one process
  each, --corpus-jobs at a time. self-compile and corpus are the scaling
  workloads: median wall and RSS may not regress more than 5%.

memory, workers, batch, self-compile and corpus measure processes this tool
starts itself, so they require --entry direct.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import hashlib
import json
import os
import platform
import queue
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import ClassVar, TypeVar

from src.compiler.python.frontend.packages import PackageTarget

from tools.qualification.statistics import SampleStatistics

REPO = Path(__file__).resolve().parents[1]
ENTRY = "src/BTRSmith.btrc"
CC = "clang"
CXX = "clang++"
DEFAULT_BATCH_MANIFEST = REPO / "tools/bench/btrsmith-batch.json"
SMOKE_ENVIRONMENT = {"BTRSMITH_SMOKE_FRAMES": "3", "BTRSMITH_SMOKE_POLL_LIMIT": "600", "BTRSMITH_SMOKE_CYCLES": "1"}
RESOURCES = ("Rosewood.png", "StratocasterBody.png", "DreadnoughtBody.png")
TOUCHED = "src/frontend/player/UiPlayerTransport.btrc"
# Plan reference "Definitions and scope": an interface edit may take 110% of
# a clean build of the changed tree; Stage 5 holds the module-unit release
# build to 110% of the whole-program one.
INTERFACE_EDIT_BUDGET = 1.10
MODULE_UNIT_BUDGET = 1.10

_FUNCTION_HEADER = re.compile(r"^[A-Za-z_][\w\s*]*?\b([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{$")
_STRUCT_TYPEDEF = re.compile(r"^typedef struct (\w+)\b")
_SESSION_NAME = re.compile(r"\b(?:__[A-Za-z]\w*?\d+\w*|[A-Za-z]\w*_\d+)\b")

T = TypeVar("T")


class Distribution:
    """The order statistics PLAN's acceptance tables report.

    tools.qualification.statistics computes them, so a report and the ledger
    that ingests it cannot disagree about a median or a percentile.
    """

    @staticmethod
    def median(values: Sequence[float]) -> float | None:
        summary = SampleStatistics.of(values)
        return None if summary is None else summary.median

    @staticmethod
    def nearest_rank(values: Sequence[float], percent: int) -> float | None:
        """The smallest sample with at least `percent`% of the samples at or below it.

        With five samples p95 is the maximum, with twenty it is the nineteenth
        smallest.
        """
        return SampleStatistics.nearest_rank(sorted(values), percent / 100) if values else None

    @staticmethod
    def rounded(value: float | None, places: int = 3) -> float | None:
        return None if value is None else round(value, places)


@dataclass
class Scenario:
    """One scenario's samples, per-sample evidence and conclusions."""

    name: str
    samples: list[float] = field(default_factory=list)
    parts: list[tuple[float, float] | None] = field(default_factory=list)
    metrics: list[dict[str, object]] = field(default_factory=list)
    timing: list[dict[str, object]] = field(default_factory=list)
    facts: dict[str, object] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def add(
        self,
        total: float,
        *,
        compile_s: float | None = None,
        native_s: float | None = None,
        metrics: dict[str, object] | None = None,
    ) -> None:
        self.samples.append(total)
        self.parts.append(None if compile_s is None else (compile_s, native_s or 0.0))
        self.metrics.append({key: value for key, value in (metrics or {}).items() if value is not None})
        detail = "" if compile_s is None else f" (compile {compile_s:6.2f} + native {native_s or 0.0:6.2f})"
        print(f"  {self.name} #{len(self.samples)}: {total:7.2f} s{detail}", flush=True)

    def note(self, text: str) -> None:
        self.notes.append(text)
        print(f"  {self.name}: {text}", flush=True)

    def compile_samples(self) -> list[float]:
        return [part[0] for part in self.parts if part is not None]

    def metric_medians(self) -> dict[str, float]:
        numeric: dict[str, list[float]] = {}
        for sample in self.metrics:
            for key, value in sample.items():
                if isinstance(value, int | float) and not isinstance(value, bool):
                    numeric.setdefault(key, []).append(float(value))
        return {key: round(statistics.median(values), 3) for key, values in sorted(numeric.items())}

    def summary(self) -> dict[str, object]:
        return {
            "samples": [round(value, 3) for value in self.samples],
            "compile_native": [None if part is None else [round(part[0], 3), round(part[1], 3)] for part in self.parts],
            "median": Distribution.rounded(Distribution.median(self.samples)),
            "p95": Distribution.rounded(Distribution.nearest_rank(self.samples, 95)),
            "max": Distribution.rounded(max(self.samples) if self.samples else None),
            "metric_medians": self.metric_medians(),
            "metrics": self.metrics,
            "facts": self.facts,
            "timing": self.timing,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class TimeReport:
    """One process's resource usage as /usr/bin/time reports it, in seconds and bytes."""

    wall_s: float | None = None
    user_s: float | None = None
    system_s: float | None = None
    max_rss_bytes: int | None = None
    peak_footprint_bytes: int | None = None
    instructions_retired: int | None = None

    TOOL = Path("/usr/bin/time")

    @classmethod
    def available(cls) -> bool:
        return cls.TOOL.is_file()

    @classmethod
    def command(cls, system: str = sys.platform) -> list[str]:
        """BSD time reports bytes and Apple's counters with -l; GNU time reports KiB with -v."""
        return [str(cls.TOOL), "-l" if system == "darwin" else "-v"]

    @classmethod
    def parse(cls, text: str, system: str = sys.platform) -> TimeReport:
        return cls._parse_bsd(text) if system == "darwin" else cls._parse_gnu(text)

    @staticmethod
    def _integer(pattern: str, text: str) -> int | None:
        match = re.search(pattern, text, re.MULTILINE)
        return int(match.group(1)) if match else None

    @classmethod
    def _parse_bsd(cls, text: str) -> TimeReport:
        times = re.search(r"^\s*([\d.]+) real\s+([\d.]+) user\s+([\d.]+) sys\s*$", text, re.MULTILINE)
        return cls(
            wall_s=float(times.group(1)) if times else None,
            user_s=float(times.group(2)) if times else None,
            system_s=float(times.group(3)) if times else None,
            max_rss_bytes=cls._integer(r"^\s*(\d+)\s+maximum resident set size\s*$", text),
            peak_footprint_bytes=cls._integer(r"^\s*(\d+)\s+peak memory footprint\s*$", text),
            instructions_retired=cls._integer(r"^\s*(\d+)\s+instructions retired\s*$", text),
        )

    @classmethod
    def _parse_gnu(cls, text: str) -> TimeReport:
        def seconds(label: str) -> float | None:
            match = re.search(rf"^\s*{re.escape(label)}: ([\d.]+)\s*$", text, re.MULTILINE)
            return float(match.group(1)) if match else None

        elapsed = re.search(r"^\s*Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): ([\d:.]+)\s*$", text, re.MULTILINE)
        wall = None
        if elapsed:
            wall = 0.0
            for part in elapsed.group(1).split(":"):
                wall = wall * 60 + float(part)
        kilobytes = cls._integer(r"^\s*Maximum resident set size \(kbytes\): (\d+)\s*$", text)
        return cls(
            wall_s=wall,
            user_s=seconds("User time (seconds)"),
            system_s=seconds("System time (seconds)"),
            max_rss_bytes=None if kilobytes is None else kilobytes * 1024,
        )

    def metrics(self, prefix: str) -> dict[str, object]:
        return {
            f"{prefix}max_rss_bytes": self.max_rss_bytes,
            f"{prefix}peak_footprint_bytes": self.peak_footprint_bytes,
            f"{prefix}instructions_retired": self.instructions_retired,
        }


@dataclass(frozen=True)
class TimingLine:
    """One process's BTRC_TIMING line: the owner's, or a forked worker's."""

    compiler: str
    role: str
    phases_s: dict[str, float]
    facts: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "compiler": self.compiler,
            "role": self.role,
            "total_s": round(sum(self.phases_s.values()), 6),
            "phases_s": {name: round(value, 6) for name, value in self.phases_s.items()},
            "facts": list(self.facts),
        }


class PhaseTiming:
    """Both compilers print `<name> timing: phase=NNNus ... fact ...` once per process."""

    LINE = re.compile(r"^(btrcc|btrcpy) timing: (.*)$")
    # The owner records how many module-unit workers it started, after they
    # forked; a worker's line never carries it. Without a pool the owner's is
    # the only line.
    OWNER_FACT = "module-unit-workers="

    @classmethod
    def parse(cls, stderr: str) -> list[TimingLine]:
        raw: list[tuple[str, dict[str, float], tuple[str, ...]]] = []
        for line in stderr.splitlines():
            match = cls.LINE.match(line.strip())
            if not match:
                continue
            phases: dict[str, float] = {}
            facts: list[str] = []
            for item in match.group(2).split():
                name, separator, value = item.rpartition("=")
                if separator and value.endswith("us") and value[:-2].isdigit():
                    phases[name] = phases.get(name, 0.0) + int(value[:-2]) / 1_000_000
                else:
                    facts.append(item)
            raw.append((match.group(1), phases, tuple(facts)))
        if not raw:
            return []
        owner = next(
            (index for index, (_, _, facts) in enumerate(raw) if any(f.startswith(cls.OWNER_FACT) for f in facts)),
            len(raw) - 1,
        )
        return [
            TimingLine(compiler, "owner" if index == owner else "worker", phases, facts)
            for index, (compiler, phases, facts) in enumerate(raw)
        ]


class ProcessTreeSampler:
    """The peak summed RSS of this process's descendants, sampled every `interval` seconds.

    RUSAGE_CHILDREN reports the largest single child, not the concurrent sum
    a build needs from the machine, so the tree is walked with ps instead.
    """

    def __init__(self, interval: float = 0.1) -> None:
        self.interval = interval

    @staticmethod
    def tree_rss(root: int, listing: str) -> int:
        children: dict[int, list[int]] = {}
        rss: dict[int, int] = {}
        for line in listing.splitlines():
            parts = line.split()
            if len(parts) != 3 or not all(part.isdigit() for part in parts):
                continue
            pid, parent, kilobytes = map(int, parts)
            children.setdefault(parent, []).append(pid)
            rss[pid] = kilobytes * 1024
        total = 0
        pending = list(children.get(root, []))
        while pending:
            pid = pending.pop()
            total += rss.get(pid, 0)
            pending.extend(children.get(pid, []))
        return total

    def run(self, action: Callable[[], T]) -> tuple[T, int]:
        root = os.getpid()
        peak = 0
        done = threading.Event()

        def sample() -> None:
            nonlocal peak
            while not done.is_set():
                listing = subprocess.run(["ps", "-A", "-o", "pid=,ppid=,rss="], capture_output=True, text=True).stdout
                peak = max(peak, self.tree_rss(root, listing))
                done.wait(self.interval)

        thread = threading.Thread(target=sample, daemon=True)
        thread.start()
        try:
            result = action()
        finally:
            done.set()
            thread.join()
        return result, peak


@dataclass(frozen=True)
class BatchEntry:
    name: str
    source: str
    arguments: tuple[str, ...] = ()
    environment: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BatchManifest:
    """The warm test batch's exact entry points (plan reference "Warm test batch").

    `status` is "placeholder" until the chosen ten are filled in; a measured
    run refuses a placeholder, a dry run accepts it.
    """

    status: str
    entries: tuple[BatchEntry, ...]
    note: str = ""

    SCHEMA = 1
    SIZE = 10
    STATUSES = ("placeholder", "final")
    NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

    @classmethod
    def load(cls, path: Path) -> BatchManifest:
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"{path}: {error}") from error
        return cls.parse(data, str(path))

    @classmethod
    def parse(cls, data: object, origin: str = "batch manifest") -> BatchManifest:
        def fail(message: str) -> ValueError:
            return ValueError(f"{origin}: {message}")

        if not isinstance(data, dict):
            raise fail("must be a JSON object")
        unknown = set(data) - {"schema", "status", "note", "entries"}
        if unknown:
            raise fail(f"unknown keys {sorted(unknown)}")
        if data.get("schema") != cls.SCHEMA:
            raise fail(f"schema must be {cls.SCHEMA}")
        status = data.get("status")
        if status not in cls.STATUSES:
            raise fail(f"status must be one of {', '.join(cls.STATUSES)}")
        note = data.get("note", "")
        if not isinstance(note, str):
            raise fail("note must be a string")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list) or len(raw_entries) != cls.SIZE:
            raise fail(f"entries must list exactly {cls.SIZE} entry points")
        entries = tuple(cls._entry(raw, index, fail) for index, raw in enumerate(raw_entries))
        for attribute in ("name", "source"):
            values = [getattr(entry, attribute) for entry in entries]
            duplicates = sorted({value for value in values if values.count(value) > 1})
            if duplicates:
                raise fail(f"duplicate entry {attribute}s {duplicates}")
        return cls(status, entries, note)

    @classmethod
    def _entry(cls, raw: object, index: int, fail: Callable[[str], ValueError]) -> BatchEntry:
        where = f"entries[{index}]"
        if not isinstance(raw, dict):
            raise fail(f"{where} must be an object")
        unknown = set(raw) - {"name", "source", "arguments", "environment"}
        if unknown:
            raise fail(f"{where} has unknown keys {sorted(unknown)}")
        name, source = raw.get("name"), raw.get("source")
        if not isinstance(name, str) or not cls.NAME.match(name):
            raise fail(f"{where}.name must match {cls.NAME.pattern}")
        if not isinstance(source, str) or "\\" in source:
            raise fail(f"{where}.source must be a POSIX path")
        path = PurePosixPath(source)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".btrc" or str(path) != source:
            raise fail(f"{where}.source must be a normalized relative .btrc path inside the workspace")
        arguments = raw.get("arguments", [])
        if not isinstance(arguments, list) or not all(isinstance(argument, str) for argument in arguments):
            raise fail(f"{where}.arguments must be a list of strings")
        environment = raw.get("environment", {})
        if not isinstance(environment, dict) or not all(
            isinstance(key, str) and key and isinstance(value, str) for key, value in environment.items()
        ):
            raise fail(f"{where}.environment must map names to strings")
        return BatchEntry(name, source, tuple(arguments), tuple(sorted(environment.items())))

    @property
    def placeholder(self) -> bool:
        return self.status == "placeholder"

    def check_sources(self, workspace: Path) -> None:
        missing = [entry.source for entry in self.entries if not (workspace / entry.source).is_file()]
        if missing:
            raise ValueError(f"batch entry points missing from {workspace}: {missing}")


@dataclass(frozen=True)
class Fixture:
    """One measured source edit. Revision 0 is the original text, revision n a novel one."""

    name: str
    module: str
    original: str
    template: str
    # A substring of a C function name the edit must make reachable.
    new_call: str = ""

    def render(self, revision: int) -> str:
        if revision == 0:
            return self.original
        return self.template.format(n=revision, chunk=8192 - revision, kind=("int", "long long")[revision % 2])


# Private-body edits (plan reference "Body edit"): navigation/model, UI
# controller and an audio-adjacent non-RT implementation.
EDIT_FIXTURES = (
    Fixture(
        "navigation",
        "src/frontend/library/AlbumGrid.btrc",
        "self._artworkStatus.arrange(12.0, 12.0,",
        "self._artworkStatus.arrange(12.{n:04d}, 12.0,",
    ),
    Fixture(
        "ui-controller",
        "src/frontend/player/UiPlayerTransport.btrc",
        "int rounded = (int)(percent + 0.5);",
        "int rounded = (int)(percent + 0.5{n:04d});",
    ),
    Fixture(
        "audio-preparation",
        "src/backend/audio/PlaybackPreparation.btrc",
        "int chunkFrames = 8192;",
        "int chunkFrames = {chunk};",
    ),
)
# Vector<Vector<double>> and Math.gcd appear nowhere else in BTRSmith; the
# numbered locals keep every revision's source novel. The added term is zero.
INSTANCE_FIXTURE = Fixture(
    "instance",
    "src/frontend/visualization/instrument/InstrumentCamera.btrc",
    "double offset = self.value - self.target;",
    "Vector<double> budgetBenchRow{n:04d} = [(double)Math.gcd({n}, 6)];\n"
    "\t\tVector<Vector<double>> budgetBenchRows{n:04d} = [];\n"
    "\t\tbudgetBenchRows{n:04d}.push(budgetBenchRow{n:04d});\n"
    "\t\tdouble offset = self.value - self.target + (double)(budgetBenchRows{n:04d}.len - 1);",
    new_call="gcd",
)
# AuthoredTimeline is in the most widely imported song module; a new field
# changes its layout, and alternating its type changes it again every revision.
INTERFACE_FIXTURE = Fixture(
    "interface",
    "src/domain/song/Timeline.btrc",
    "class AuthoredTimeline {\n\tprivate TimelineIdentity _identity;",
    "class AuthoredTimeline {{\n\tpublic {kind} budgetBenchLayout{n:04d} = 0;\n\tprivate TimelineIdentity _identity;",
)

COLD_SCENARIOS = ("cold", "release")
INCREMENTAL_SCENARIOS = (
    *(f"edit-{fixture.name}" for fixture in EDIT_FIXTURES),
    "instance-edit",
    "interface-edit",
    "noop",
    "touch",
)
DIRECT_ONLY_SCENARIOS = ("memory", "workers", "batch", "self-compile", "corpus")
SCENARIOS = (*COLD_SCENARIOS, *INCREMENTAL_SCENARIOS, *DIRECT_ONLY_SCENARIOS)
DEFAULT_SCENARIOS = "cold,edit,noop,touch,memory"


@dataclass(frozen=True)
class Flavor:
    """A build's mode and C split, rendered as BTRSmith's make/Config.mk renders them."""

    mode: str
    units: str

    def compiler_flags(self) -> list[str]:
        return [*(["--debug"] if self.mode == "dev" else []), *(["--module-units"] if self.units == "module" else [])]

    def native_flags(self) -> list[str]:
        return ["--optimization", "0", "--debug-info"] if self.mode == "dev" else []


@dataclass(frozen=True)
class ProductPaths:
    """Where one build writes its C, link plan, executable and native report."""

    generated_c: Path
    plan: Path
    units_prefix: Path
    executable: Path
    native_report: Path

    @classmethod
    def direct(cls, build: Path, executable: str = "BTRSmith") -> ProductPaths:
        return cls(build / "p.c", build / "p.json", build / "p", build / executable, build / "native.json")

    @classmethod
    def make(cls, build: Path, frontend: str) -> ProductPaths:
        """make/Suites.mk's BTRSMITH_C, BTRSMITH_PLAN and BTRSMITH_BINARY under BUILD_DIR."""
        generated = build / "generated" / f"btrsmith.{frontend}.c"
        return cls(
            generated,
            build / "generated" / f"btrsmith.{frontend}.link.json",
            generated,
            build / "bin" / f"btrsmith.{frontend}",
            build / "native.json",
        )

    def c_files(self, workspace: Path) -> list[Path]:
        units = json.loads(self.plan.read_text()).get("emitted-units", [])
        return [self.generated_c, *(Path(unit) if Path(unit).is_absolute() else workspace / unit for unit in units)]


@dataclass(frozen=True)
class State:
    """One build's mutable inputs: the btrc artifact cache, object cache and outputs."""

    root: Path

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    @property
    def objects(self) -> Path:
        return self.root / "objects"

    @property
    def build(self) -> Path:
        return self.root / "build"

    def reset(self, *, objects: bool) -> None:
        shutil.rmtree(self.cache, ignore_errors=True)
        shutil.rmtree(self.build, ignore_errors=True)
        if objects:
            shutil.rmtree(self.objects, ignore_errors=True)
        for path in (self.cache, self.objects, self.build):
            path.mkdir(parents=True, exist_ok=True)


class HostTarget:
    """The --target a developer's build passes on this host."""

    # make/Config.mk's DEFAULT_BTRC_TARGET spellings, so a direct build and
    # `--entry make` hand the compiler the same option.
    PRODUCT_SPELLINGS: ClassVar[dict[tuple[str, str], str]] = {
        ("Darwin", "arm64"): "macos-arm64",
        ("Linux", "x86_64"): "linux-x86_64",
    }

    @classmethod
    def resolve(cls, requested: str | None, system: str | None = None, machine: str | None = None) -> str:
        if requested is not None:
            PackageTarget.parse(requested)
            return requested
        key = (system or platform.system(), machine or platform.machine())
        if key in cls.PRODUCT_SPELLINGS:
            return cls.PRODUCT_SPELLINGS[key]
        target = PackageTarget.parse(None)
        return f"{target.operating_system}-{target.architecture}"

    @staticmethod
    def self_compile_entry(system: str | None = None) -> str:
        """The compiler entry this host bootstraps (CLAUDE.md: build for the compiler's host)."""
        return (
            "src/compiler/btrc/cli/MacOSMain.btrc"
            if (system or platform.system()) == "Darwin"
            else "src/compiler/btrc/BtrccMain.btrc"
        )


@dataclass(frozen=True)
class BenchSettings:
    """One run's validated options."""

    btrcc: Path | None
    workspace: Path
    out: Path
    frontend: str
    mode: str
    units: str
    entry: str
    target: str
    scenarios: tuple[str, ...]
    cold_samples: int
    incremental_samples: int
    dry_run: bool
    timing_cold: bool
    native_jobs: int
    workers: tuple[int, ...]
    corpus_jobs: int
    batch_manifest: Path
    self_compile_entry: str
    make: str
    keep: bool

    @staticmethod
    def parser() -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            prog="python3 -m tools.budget_bench",
            description=__doc__,
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("--btrcc", help="the self-hosted compiler; required for --frontend selfhost")
        parser.add_argument("--workspace", required=True, help="the pinned BTRSmith checkout; copied, never edited")
        parser.add_argument("--out", required=True, help="run directory, replaced")
        parser.add_argument("--frontend", choices=("selfhost", "reference"), default="selfhost")
        parser.add_argument("--mode", choices=("dev", "release"), default="dev")
        parser.add_argument("--units", choices=("module", "whole"), help="default: module for dev, whole for release")
        parser.add_argument("--entry", choices=("direct", "make"), default="direct")
        parser.add_argument("--target", help="OS-ARCH; default: this host as BTRSmith's make/Config.mk spells it")
        parser.add_argument(
            "--scenarios",
            default=DEFAULT_SCENARIOS,
            help=f"comma-separated from {', '.join(('edit', *SCENARIOS))}, or all (default: {DEFAULT_SCENARIOS})",
        )
        parser.add_argument("--cold-samples", type=int, default=5)
        parser.add_argument("--incremental-samples", type=int, default=20)
        parser.add_argument("--dry-run", action="store_true", help="one sample of every scenario; never acceptance")
        parser.add_argument(
            "--timing-cold", action="store_true", help="keep BTRC_TIMING owner/worker lines of cold builds"
        )
        parser.add_argument("--native-jobs", type=int, default=8)
        parser.add_argument("--workers", default="1,2,4,8", help="compiler worker counts the workers sweep measures")
        parser.add_argument("--corpus-jobs", type=int, default=1, help="corpus programs transpiled at once")
        parser.add_argument("--batch-manifest", default=str(DEFAULT_BATCH_MANIFEST))
        parser.add_argument("--self-compile-entry", help="default: this host's compiler entry")
        parser.add_argument("--make", default="make", help="GNU make for --entry make")
        parser.add_argument("--keep", action="store_true", help="keep the copied workspace and build states")
        return parser

    @classmethod
    def parse(cls, argv: Sequence[str] | None = None) -> BenchSettings:
        parser = cls.parser()
        arguments = parser.parse_args(argv)
        try:
            return cls.from_arguments(arguments)
        except ValueError as error:
            parser.error(str(error))

    @classmethod
    def scenario_names(cls, text: str) -> tuple[str, ...]:
        requested: set[str] = set()
        for name in filter(None, (part.strip() for part in text.split(","))):
            if name == "all":
                requested.update(SCENARIOS)
            elif name == "edit":
                requested.update(f"edit-{fixture.name}" for fixture in EDIT_FIXTURES)
            elif name in SCENARIOS:
                requested.add(name)
            else:
                raise ValueError(f"unknown scenario {name!r}; choose from edit, all, {', '.join(SCENARIOS)}")
        if not requested:
            raise ValueError("--scenarios names no scenario")
        return tuple(name for name in SCENARIOS if name in requested)

    @classmethod
    def from_arguments(cls, arguments: argparse.Namespace) -> BenchSettings:
        scenarios = cls.scenario_names(arguments.scenarios)
        btrcc = None
        if arguments.frontend == "selfhost":
            if not arguments.btrcc:
                raise ValueError("--frontend selfhost needs --btrcc")
            btrcc = Path(arguments.btrcc).expanduser().resolve()
            if not btrcc.is_file():
                raise ValueError(f"--btrcc {btrcc} is not a file")
        workspace = Path(arguments.workspace).expanduser().resolve()
        if not (workspace / ENTRY).is_file():
            raise ValueError(f"--workspace {workspace} has no {ENTRY}")
        out = Path(arguments.out).expanduser().resolve()
        if out == workspace or workspace.is_relative_to(out) or out.is_relative_to(workspace):
            raise ValueError("--out must be outside the workspace and must not contain it")
        if arguments.entry == "make":
            direct = [name for name in scenarios if name in DIRECT_ONLY_SCENARIOS]
            if direct:
                raise ValueError(f"--entry make cannot run {', '.join(direct)}; they need --entry direct")
            if any(character.isspace() for character in str(out)):
                raise ValueError("--entry make needs an --out path without whitespace (it becomes BUILD_DIR)")
        try:
            workers = tuple(int(part) for part in arguments.workers.split(","))
        except ValueError as error:
            raise ValueError("--workers must be comma-separated integers") from error
        if any(count < 1 or count > 64 for count in workers) or len(set(workers)) != len(workers):
            raise ValueError("--workers must be distinct counts from 1 to 64")
        if min(arguments.cold_samples, arguments.incremental_samples, arguments.native_jobs, arguments.corpus_jobs) < 1:
            raise ValueError("sample counts, --native-jobs and --corpus-jobs must be positive")
        try:
            target = HostTarget.resolve(arguments.target)
        except ValueError as error:
            raise ValueError(f"--target: {error}") from error
        batch_manifest = Path(arguments.batch_manifest).expanduser().resolve()
        if "batch" in scenarios:
            manifest = BatchManifest.load(batch_manifest)
            if manifest.placeholder and not arguments.dry_run:
                raise ValueError(f"{batch_manifest} is a placeholder; fill in its entry points or pass --dry-run")
            manifest.check_sources(workspace)
        self_compile_entry = arguments.self_compile_entry or HostTarget.self_compile_entry()
        if "self-compile" in scenarios and not (REPO / self_compile_entry).is_file():
            raise ValueError(f"--self-compile-entry {self_compile_entry} is not a file in {REPO}")
        samples = 1 if arguments.dry_run else None
        return cls(
            btrcc=btrcc,
            workspace=workspace,
            out=out,
            frontend=arguments.frontend,
            mode=arguments.mode,
            units=arguments.units or ("module" if arguments.mode == "dev" else "whole"),
            entry=arguments.entry,
            target=target,
            scenarios=scenarios,
            cold_samples=samples or arguments.cold_samples,
            incremental_samples=samples or arguments.incremental_samples,
            dry_run=arguments.dry_run,
            timing_cold=arguments.timing_cold,
            native_jobs=arguments.native_jobs,
            workers=workers,
            corpus_jobs=arguments.corpus_jobs,
            batch_manifest=batch_manifest,
            self_compile_entry=self_compile_entry,
            make=arguments.make,
            keep=arguments.keep,
        )

    @property
    def flavor(self) -> Flavor:
        return Flavor(self.mode, self.units)

    def describe(self) -> dict[str, object]:
        return {
            name: str(value) if isinstance(value, Path) else list(value) if isinstance(value, tuple) else value
            for name, value in self.__dict__.items()
        }


class BuildCommands:
    """Every command line a run issues, derived from its settings alone."""

    def __init__(self, settings: BenchSettings, wrappers: Path) -> None:
        self.settings = settings
        self.wrappers = wrappers

    @staticmethod
    def python_module(module: str) -> list[str]:
        # -P keeps the copied workspace's own src/ and tools/ off sys.path;
        # PYTHONPATH names this checkout.
        return [sys.executable, "-P", "-m", module]

    def frontend(self) -> list[str]:
        if self.settings.frontend == "selfhost":
            return [str(self.settings.btrcc)]
        return self.python_module("src.compiler.python.main")

    def compile(
        self, paths: ProductPaths, flavor: Flavor, *, jobs: int | None = None, source: str = ENTRY
    ) -> list[str]:
        return [
            *self.frontend(),
            "--strict-imports",
            "--target",
            self.settings.target,
            *flavor.compiler_flags(),
            *(["--jobs", str(jobs)] if jobs is not None else []),
            "--emit-link-plan",
            str(paths.plan),
            "--emit-units",
            str(paths.units_prefix),
            source,
            "-o",
            str(paths.generated_c),
        ]

    def native(self, paths: ProductPaths, flavor: Flavor, objects: Path) -> list[str]:
        return [
            *self.python_module("tools.native_plan"),
            "--plan",
            str(paths.plan),
            "--generated-c",
            str(paths.generated_c),
            "--output",
            str(paths.executable),
            "--cc",
            CC,
            "--cxx",
            CXX,
            "--jobs",
            str(self.settings.native_jobs),
            *flavor.native_flags(),
            "--object-cache",
            str(objects),
            "--report-json",
            str(paths.native_report),
        ]

    def make(self, state: State, flavor: Flavor, goal: str) -> list[str]:
        """BTRSmith's product Make, pointed at this run's compiler, native builder and state."""
        paths = ProductPaths.make(state.build, self.settings.frontend)
        native = [
            *flavor.native_flags(),
            "--jobs",
            str(self.settings.native_jobs),
            "--report-json",
            str(paths.native_report),
        ]
        assignments = {
            "BUILD": flavor.mode,
            "BTRC_FRONTEND": self.settings.frontend,
            "BTRC_TARGET": self.settings.target,
            "BTRC_BUILD_FLAGS": shlex.join(flavor.compiler_flags()),
            "NATIVE_PLAN": shlex.quote(str(self.wrappers / "btrc-native-plan")),
            "NATIVE_PLAN_FLAGS": shlex.join(native),
            "BUILD_DIR": str(state.build),
            "BTRC_OBJECT_CACHE": str(state.objects),
            # No signing keychain: an ad hoc build signs nothing, as in CI.
            "CODESIGN_IDENTITY": "-",
        }
        if self.settings.frontend == "selfhost":
            assignments["BTRCC"] = shlex.quote(str(self.settings.btrcc))
        else:
            assignments["BTRCPY"] = shlex.quote(str(self.wrappers / "btrcpy"))
        return [self.settings.make, "-f", "make/Product.mk", goal, *(f"{k}={v}" for k, v in assignments.items())]

    def wrapper_scripts(self) -> dict[str, str]:
        """Make runs its tools by name; these run this checkout's."""
        lines = ["#!/bin/sh", f"PYTHONPATH={shlex.quote(str(REPO))}", "export PYTHONPATH"]
        return {
            name: "\n".join([*lines, f'exec {shlex.join(self.python_module(module))} "$@"', ""])
            for name, module in (("btrcpy", "src.compiler.python.main"), ("btrc-native-plan", "tools.native_plan"))
        }


@dataclass(frozen=True)
class SymbolSet:
    """The struct typedefs and function definitions one build's C declares."""

    structs: frozenset[str]
    functions: frozenset[str]

    @classmethod
    def scan(cls, files: Sequence[Path]) -> SymbolSet:
        structs: set[str] = set()
        functions: set[str] = set()
        for path in files:
            for line in path.read_text(errors="replace").split("\n"):
                if (struct := _STRUCT_TYPEDEF.match(line)) is not None:
                    structs.add(struct.group(1))
                elif (header := _FUNCTION_HEADER.match(line)) is not None:
                    functions.add(header.group(1))
        return cls(frozenset(structs), frozenset(functions))

    def added_since(self, earlier: SymbolSet) -> SymbolSet:
        return SymbolSet(self.structs - earlier.structs, self.functions - earlier.functions)


@dataclass(frozen=True)
class BuildRun:
    total_s: float
    compile_s: float | None
    native_s: float | None
    native: dict[str, object]
    timing: dict[str, object] | None = None
    usage: TimeReport | None = None


class RunDirectory:
    """Replace --out only when it is empty or an earlier run of this tool."""

    MARKER = ".budget-bench-run"
    KEPT = frozenset({MARKER, "report.json", "timing"})

    @classmethod
    def prepare(cls, out: Path) -> None:
        if out.is_symlink() or (out.exists() and not out.is_dir()):
            raise ValueError(f"--out {out} is not a directory")
        if out.exists():
            if any(out.iterdir()) and not (out / cls.MARKER).is_file():
                raise ValueError(f"--out {out} is not empty and was not written by this tool; refusing to replace it")
            shutil.rmtree(out)
        out.mkdir(parents=True)
        (out / cls.MARKER).write_text("tools/budget_bench.py run directory\n")

    @classmethod
    def prune(cls, out: Path) -> None:
        """Drop the workspace copy and build states, keeping the report and timing."""
        for child in out.iterdir():
            if child.name in cls.KEPT:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)


class TreeCopy:
    """Copy-on-write snapshots of a primed state where the file system has them."""

    @staticmethod
    def clone(source: Path, destination: Path) -> None:
        shutil.rmtree(destination, ignore_errors=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            command = ["/bin/cp", "-c", "-R", str(source), str(destination)]
        elif sys.platform.startswith("linux"):
            command = ["cp", "-a", "--reflink=auto", str(source), str(destination)]
        else:
            command = []
        if command and subprocess.run(command, capture_output=True).returncode == 0:
            return
        shutil.rmtree(destination, ignore_errors=True)
        shutil.copytree(source, destination, symlinks=True)


class BudgetBench:
    """Drive one copied workspace through the selected budget scenarios."""

    SMOKE_RERUNS = 2

    def __init__(self, settings: BenchSettings) -> None:
        self.settings = settings
        self.out = settings.out
        self.flavor = settings.flavor
        self.started = datetime.datetime.now(datetime.UTC)
        RunDirectory.prepare(self.out)
        self.workspace = self.out / "ws"
        shutil.copytree(settings.workspace, self.workspace, symlinks=True)
        self.commands = BuildCommands(settings, self.out / "bin")
        self.results: dict[str, Scenario] = {}
        self.revisions: dict[str, int] = {}
        self.provenance = self.collect_provenance()
        if settings.entry == "make":
            self.commands.wrappers.mkdir()
            for name, text in self.commands.wrapper_scripts().items():
                path = self.commands.wrappers / name
                path.write_text(text)
                path.chmod(0o755)

    # -- bookkeeping ---------------------------------------------------------

    def scenario(self, name: str) -> Scenario:
        """A scenario is reported from its first sample, so a failed run keeps what it measured."""
        print(f"\n{name}", flush=True)
        self.results[name] = Scenario(name)
        return self.results[name]

    def state(self, name: str) -> State:
        return State(self.out / name)

    def product(self, state: State) -> ProductPaths:
        if self.settings.entry == "make":
            return ProductPaths.make(state.build, self.settings.frontend)
        return ProductPaths.direct(state.build)

    def environment(self, state: State, *, timing: bool) -> dict[str, str]:
        environment = {
            **os.environ,
            "BTRC_HOME": str(REPO / "src"),
            "BTRC_CACHE_DIR": str(state.cache),
            "PYTHONPATH": str(REPO),
        }
        for name in ("BTRC_TIMING", "BTRCC_TIMING"):
            environment.pop(name, None)
        if timing:
            environment["BTRC_TIMING"] = "1"
        return environment

    @staticmethod
    def execute(
        command: Sequence[str], *, cwd: Path, env: dict[str, str], label: str
    ) -> tuple[float, subprocess.CompletedProcess[str]]:
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, errors="replace")
        elapsed = time.perf_counter() - started
        if completed.returncode != 0:
            output = (completed.stdout[-2000:] + completed.stderr[-4000:]).strip()
            raise RuntimeError(f"{label} failed ({completed.returncode}): {shlex.join(command)}\n{output}")
        return elapsed, completed

    def keep_timing(self, label: str | None, stderr: str) -> dict[str, object] | None:
        if label is None:
            return None
        directory = self.out / "timing"
        directory.mkdir(exist_ok=True)
        path = directory / f"{label}.txt"
        path.write_text(stderr)
        return {
            "file": str(path.relative_to(self.out)),
            "lines": [line.as_dict() for line in PhaseTiming.parse(stderr)],
        }

    def cold_label(self, name: str, index: int) -> str | None:
        return f"{name}-{index + 1}" if self.settings.timing_cold else None

    @staticmethod
    def native_summary(path: Path) -> dict[str, object]:
        if not path.is_file():
            return {}
        report = json.loads(path.read_text())
        return {
            "native_compiled_units": report.get("compiled_units"),
            "native_reused_units": report.get("reused_units"),
            "native_links": report.get("links"),
            "native_link_cache": report.get("link_cache_status"),
        }

    def record(self, scenario: Scenario, run: BuildRun, metrics: dict[str, object] | None = None) -> None:
        scenario.add(
            run.total_s, compile_s=run.compile_s, native_s=run.native_s, metrics={**run.native, **(metrics or {})}
        )
        if run.timing is not None:
            scenario.timing.append(run.timing)

    # -- builds --------------------------------------------------------------

    def compile(
        self,
        state: State,
        flavor: Flavor | None = None,
        *,
        paths: ProductPaths | None = None,
        source: str = ENTRY,
        jobs: int | None = None,
        timing_label: str | None = None,
        measure: bool = False,
    ) -> BuildRun:
        paths = paths or ProductPaths.direct(state.build)
        command = self.commands.compile(paths, flavor or self.flavor, jobs=jobs, source=source)
        if measure:
            command = [*TimeReport.command(), *command]
        elapsed, completed = self.execute(
            command,
            cwd=self.workspace,
            env=self.environment(state, timing=timing_label is not None),
            label=f"{self.settings.frontend} compile",
        )
        return BuildRun(
            elapsed,
            elapsed,
            0.0,
            {},
            self.keep_timing(timing_label, completed.stderr),
            TimeReport.parse(completed.stderr) if measure else None,
        )

    def native(
        self, state: State, flavor: Flavor | None = None, paths: ProductPaths | None = None
    ) -> tuple[float, dict[str, object]]:
        paths = paths or ProductPaths.direct(state.build)
        paths.native_report.unlink(missing_ok=True)
        elapsed, _ = self.execute(
            self.commands.native(paths, flavor or self.flavor, state.objects),
            cwd=self.workspace,
            env={**os.environ, "PYTHONPATH": str(REPO)},
            label="native plan",
        )
        return elapsed, self.native_summary(paths.native_report)

    def make(self, state: State, flavor: Flavor, goal: str, timing_label: str | None) -> BuildRun:
        paths = ProductPaths.make(state.build, self.settings.frontend)
        paths.native_report.unlink(missing_ok=True)
        environment = self.environment(state, timing=timing_label is not None)
        for name in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "GNUMAKEFLAGS"):
            environment.pop(name, None)
        elapsed, completed = self.execute(
            self.commands.make(state, flavor, goal), cwd=self.workspace, env=environment, label=f"make {goal}"
        )
        return BuildRun(
            elapsed,
            None,
            None,
            self.native_summary(paths.native_report),
            self.keep_timing(timing_label, completed.stderr),
        )

    def transpile(self, state: State, flavor: Flavor | None = None, *, timing_label: str | None = None) -> BuildRun:
        if self.settings.entry == "make":
            return self.make(state, flavor or self.flavor, "btrsmith-source", timing_label)
        return self.compile(state, flavor, timing_label=timing_label)

    def build(self, state: State, flavor: Flavor | None = None, *, timing_label: str | None = None) -> BuildRun:
        """A compile and native build of the product; `timing_label` keeps the compile's phase timing."""
        if self.settings.entry == "make":
            return self.make(state, flavor or self.flavor, "btrsmith-native", timing_label)
        compiled = self.compile(state, flavor, timing_label=timing_label)
        native_s, native = self.native(state, flavor)
        return BuildRun(compiled.total_s + native_s, compiled.total_s, native_s, native, compiled.timing)

    def apply(self, fixture: Fixture, revision: int) -> None:
        path = self.workspace / fixture.module
        text = path.read_text()
        current = fixture.render(self.revisions.get(fixture.name, 0))
        if text.count(current) != 1:
            raise RuntimeError(f"edit anchor for {fixture.name} is not unique in {fixture.module}")
        path.write_text(text.replace(current, fixture.render(revision), 1))
        self.revisions[fixture.name] = revision

    def advance(self, fixture: Fixture) -> None:
        self.apply(fixture, self.revisions.get(fixture.name, 0) + 1)

    # -- correctness ---------------------------------------------------------

    @staticmethod
    def function_bodies(files: Sequence[Path]) -> dict[str, set[str]]:
        """Every function body in a build's C, independent of how units split it."""
        bodies: dict[str, set[str]] = {}
        for unit in files:
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

    def smoke(self, executable: Path) -> tuple[str, str]:
        """The executable's smoke output and stderr, from one layout every build shares.

        BTRSmith binds its agent socket under the state directory, and a Unix
        socket path is limited to about 104 bytes: two builds smoked under
        different paths could differ in whether the agent channel opens.
        """
        layout = self.out / "smoke"
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
            [str(layout / "bin/BTRSmith")],
            cwd=layout,
            env=environment,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
        )
        return f"exit {completed.returncode}\n{completed.stdout}", completed.stderr

    def compare(self, scenario: Scenario, incremental: State, clean: State) -> None:
        """A clean build of the current tree must emit the incremental build's bodies and behavior."""
        incremental_paths, clean_paths = self.product(incremental), self.product(clean)
        incremental_bodies = self.function_bodies(incremental_paths.c_files(self.workspace))
        clean_bodies = self.function_bodies(clean_paths.c_files(self.workspace))
        same_bodies = clean_bodies == incremental_bodies
        # The smoke's teardown count follows the machine's timing, so one
        # binary can print two outputs. Outputs differ between the builds only
        # if no rerun of either reproduces one the other printed.
        incremental_smoke: set[str] = set()
        clean_smoke: set[str] = set()
        warnings: set[str] = set()
        reruns = -1
        while not incremental_smoke & clean_smoke and reruns < self.SMOKE_RERUNS:
            reruns += 1
            for executable, outputs in (
                (incremental_paths.executable, incremental_smoke),
                (clean_paths.executable, clean_smoke),
            ):
                output, stderr = self.smoke(executable)
                outputs.add(output)
                warnings.update(line.strip() for line in stderr.splitlines() if "unavailable" in line)
        shared = sorted(incremental_smoke & clean_smoke)
        same_smoke = bool(shared) and all("PASS" in output for output in shared)
        shown = shared[0] if shared else " | ".join(sorted(clean_smoke | incremental_smoke))
        scenario.note(
            f"clean-build check: {len(clean_bodies)} functions, bodies {'equal' if same_bodies else 'DIFFER'}; "
            f"smoke {'equal' if same_smoke else 'DIFFERS'}"
            f"{f' after {reruns} rerun(s)' if reruns else ''}: {shown.strip()!r}"
        )
        if warnings:
            scenario.note(f"smoke stderr: {'; '.join(sorted(warnings))}")
        if not (same_bodies and same_smoke):
            raise RuntimeError(f"{scenario.name}: incremental build differs from a clean build")

    def verify_against_clean(self, scenario: Scenario, warm: State) -> None:
        clean = self.state("clean")
        clean.reset(objects=True)
        self.build(clean)
        self.compare(scenario, warm, clean)
        shutil.rmtree(clean.root, ignore_errors=True)

    # -- scenarios -----------------------------------------------------------

    def run_cold(self) -> None:
        state = self.state("cold")
        transpile = self.scenario("cold-transpile")
        for index in range(self.settings.cold_samples):
            state.reset(objects=True)
            self.record(transpile, self.transpile(state, timing_label=self.cold_label(transpile.name, index)))
        cold = self.scenario(f"cold-{self.settings.mode}")
        for index in range(self.settings.cold_samples):
            state.reset(objects=True)
            self.record(cold, self.build(state, timing_label=self.cold_label(cold.name, index)))

    def run_release(self) -> None:
        state = self.state("cold")
        medians: dict[str, float | None] = {}
        for units in ("whole", "module"):
            scenario = self.scenario(f"release-{units}")
            for index in range(self.settings.cold_samples):
                state.reset(objects=True)
                run = self.build(state, Flavor("release", units), timing_label=self.cold_label(scenario.name, index))
                self.record(scenario, run)
            medians[units] = Distribution.median(scenario.samples)
        if medians["whole"] and medians["module"] is not None:
            ratio = medians["module"] / medians["whole"]
            release = self.results["release-module"]
            release.facts.update(ratio_to_whole=round(ratio, 4), budget=MODULE_UNIT_BUDGET)
            verdict = "met" if ratio <= MODULE_UNIT_BUDGET else "MISSED"
            release.note(f"module-unit / whole-program median {ratio:.3f} (budget <= {MODULE_UNIT_BUDGET}): {verdict}")

    def run_incremental(self) -> None:
        selected = set(self.settings.scenarios)
        warm = self.state("warm")
        warm.reset(objects=True)
        print("\npriming the warm state", flush=True)
        self.build(warm)
        self.build(warm)
        for fixture in EDIT_FIXTURES:
            name = f"edit-{fixture.name}"
            if name not in selected:
                continue
            scenario = self.scenario(name)
            for index in range(self.settings.incremental_samples):
                self.advance(fixture)
                self.record(scenario, self.build(warm, timing_label=f"{name}-{index + 1}"))
            self.verify_against_clean(scenario, warm)
        if "instance-edit" in selected:
            self.run_instance_edit(warm)
        if "interface-edit" in selected:
            self.run_interface_edit(warm)
        if "noop" in selected:
            scenario = self.scenario("noop")
            for index in range(self.settings.incremental_samples):
                self.record(scenario, self.build(warm, timing_label=f"noop-{index + 1}"))
        if "touch" in selected:
            scenario = self.scenario("touch")
            path = self.workspace / TOUCHED
            for _ in range(self.settings.incremental_samples):
                path.write_bytes(path.read_bytes())
                self.record(scenario, self.build(warm))

    def run_instance_edit(self, warm: State) -> None:
        scenario = self.scenario("instance-edit")
        fixture = INSTANCE_FIXTURE
        baseline = SymbolSet.scan(self.product(warm).c_files(self.workspace))
        added = SymbolSet(frozenset(), frozenset())
        for index in range(self.settings.incremental_samples):
            if self.revisions.get(fixture.name, 0):
                # Untimed: the original tree again, so the timed build adds the
                # instance and the call to a build that lacks them.
                self.apply(fixture, 0)
                self.build(warm)
            self.apply(fixture, index + 1)
            run = self.build(warm, timing_label=f"instance-edit-{index + 1}")
            added = SymbolSet.scan(self.product(warm).c_files(self.workspace)).added_since(baseline)
            if not added.structs:
                raise RuntimeError("instance-edit: the edited build declares no new generic instance")
            if not any(fixture.new_call in name for name in added.functions):
                raise RuntimeError(f"instance-edit: no new function named like {fixture.new_call!r} was reached")
            self.record(scenario, run, {"new_struct_types": len(added.structs), "new_functions": len(added.functions)})
        scenario.facts["new_struct_types"] = sorted(added.structs)
        self.verify_against_clean(scenario, warm)

    def run_interface_edit(self, warm: State) -> None:
        scenario = self.scenario("interface-edit")
        clean = self.state("clean")
        ratios: list[float] = []
        for index in range(self.settings.cold_samples):
            self.advance(INTERFACE_FIXTURE)
            run = self.build(warm, timing_label=f"interface-edit-{index + 1}")
            clean.reset(objects=True)
            clean_run = self.build(clean)
            self.compare(scenario, warm, clean)
            ratios.append(run.total_s / clean_run.total_s)
            self.record(scenario, run, {"clean_s": round(clean_run.total_s, 3), "ratio_to_clean": round(ratios[-1], 4)})
        shutil.rmtree(clean.root, ignore_errors=True)
        median = statistics.median(ratios)
        scenario.facts.update(
            ratio_median=round(median, 4), ratio_max=round(max(ratios), 4), budget=INTERFACE_EDIT_BUDGET
        )
        verdict = "met" if max(ratios) <= INTERFACE_EDIT_BUDGET else "MISSED"
        scenario.note(
            f"incremental / clean median {median:.3f}, max {max(ratios):.3f} (budget <= {INTERFACE_EDIT_BUDGET}): {verdict}"
        )

    def run_memory(self) -> None:
        scenario = self.scenario("memory")
        state = self.state("memory")
        state.reset(objects=True)
        jobs = 1 if self.flavor.units == "module" else None
        if TimeReport.available():
            run = self.compile(state, jobs=jobs, measure=True)
            usage = run.usage or TimeReport()
            scenario.facts.update(compile_s=round(run.total_s, 3), **usage.metrics("compiler_"))
            peak = usage.peak_footprint_bytes or usage.max_rss_bytes
            if peak is not None:
                scenario.note(f"{self.settings.frontend} --jobs 1 peak {peak} bytes ({peak / 2**30:.3f} GiB)")
            if usage.instructions_retired is not None:
                scenario.note(f"{self.settings.frontend} --jobs 1 instructions retired {usage.instructions_retired:,}")
        else:
            scenario.note(f"{TimeReport.TOOL} is missing: no compiler peak")
        state.reset(objects=True)
        _, aggregate = ProcessTreeSampler().run(lambda: self.build(state))
        scenario.facts["build_tree_rss_bytes"] = aggregate
        scenario.note(f"cold build sampled aggregate RSS peak {aggregate} bytes ({aggregate / 2**30:.3f} GiB)")

    def run_workers(self) -> None:
        state = self.state("workers")
        flavor = Flavor(self.settings.mode, "module")
        sampler = ProcessTreeSampler()
        measure = TimeReport.available()
        for count in self.settings.workers:
            scenario = self.scenario(f"workers-{count}")
            for index in range(self.settings.cold_samples):
                state.reset(objects=True)
                compiled, compile_rss = sampler.run(
                    lambda count=count, index=index, name=scenario.name: self.compile(
                        state, flavor, jobs=count, measure=measure, timing_label=self.cold_label(name, index)
                    )
                )
                (native_s, native), native_rss = sampler.run(lambda: self.native(state, flavor))
                usage = compiled.usage or TimeReport()
                self.record(
                    scenario,
                    BuildRun(compiled.total_s + native_s, compiled.total_s, native_s, native, compiled.timing),
                    {
                        "compile_tree_rss_bytes": compile_rss,
                        "native_tree_rss_bytes": native_rss,
                        **usage.metrics("compiler_"),
                    },
                )
        base = Distribution.median(self.results[f"workers-{self.settings.workers[0]}"].compile_samples())
        for count in self.settings.workers:
            scenario = self.results[f"workers-{count}"]
            median = Distribution.median(scenario.compile_samples())
            if base and median:
                scenario.facts["compile_speedup"] = round(base / median, 3)
                scenario.note(
                    f"compile median {median:.2f} s, {base / median:.2f}x the {self.settings.workers[0]}-worker median"
                )

    def run_batch(self) -> None:
        manifest = BatchManifest.load(self.settings.batch_manifest)
        manifest.check_sources(self.workspace)
        scenario = self.scenario("batch")
        scenario.facts.update(manifest=str(self.settings.batch_manifest), status=manifest.status)
        state = self.state("batch")
        primed = self.out / "batch-primed"
        state.reset(objects=True)
        print("  priming the shared application dependencies with a product build", flush=True)
        self.build(state)
        TreeCopy.clone(state.root, primed)
        sandbox = self.out / "batch-sandbox"
        for index in range(self.settings.cold_samples):
            if index:
                TreeCopy.clone(primed, state.root)
            compile_s = native_s = 0.0
            metrics: dict[str, object] = {}
            executables: list[tuple[BatchEntry, Path]] = []
            for entry in manifest.entries:
                directory = state.build / "batch" / entry.name
                directory.mkdir(parents=True)
                paths = ProductPaths.direct(directory, entry.name)
                compiled = self.compile(state, paths=paths, source=entry.source)
                built_s, _ = self.native(state, paths=paths)
                compile_s += compiled.total_s
                native_s += built_s
                metrics[f"build_s.{entry.name}"] = round(compiled.total_s + built_s, 3)
                executables.append((entry, paths.executable))
            # Test execution is recorded apart from the build it follows.
            failures: list[str] = []
            execution: dict[str, float] = {}
            for entry, executable in executables:
                execution[entry.name], failure = self.run_test(entry, executable, sandbox / entry.name)
                if failure is not None:
                    failures.append(failure)
            metrics.update({f"execution_s.{name}": round(seconds, 3) for name, seconds in execution.items()})
            scenario.add(
                compile_s + native_s,
                compile_s=compile_s,
                native_s=native_s,
                metrics={"execution_s": round(sum(execution.values()), 3), **metrics},
            )
            if failures:
                raise RuntimeError(f"{len(failures)} batch test(s) failed:\n" + "\n".join(failures))
        shutil.rmtree(primed, ignore_errors=True)

    def run_test(self, entry: BatchEntry, executable: Path, sandbox: Path) -> tuple[float, str | None]:
        """Run one batch executable from the workspace root with a private home; a failure is described."""
        shutil.rmtree(sandbox, ignore_errors=True)
        (sandbox / "tmp").mkdir(parents=True)
        environment = {
            **os.environ,
            "HOME": str(sandbox),
            "TMPDIR": str(sandbox / "tmp"),
            "BTRSMITH_STATE_DIRECTORY": str(sandbox),
            **dict(entry.environment),
        }
        started = time.perf_counter()
        completed = subprocess.run(
            [str(executable), *entry.arguments],
            cwd=self.workspace,
            env=environment,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=900,
        )
        elapsed = time.perf_counter() - started
        if completed.returncode == 0:
            return elapsed, None
        output = (completed.stdout[-1500:] + completed.stderr[-1500:]).strip()
        return elapsed, f"{entry.name} exited {completed.returncode}: {output}"

    def run_self_compile(self) -> None:
        scenario = self.scenario("self-compile")
        state = self.state("self-compile")
        source = REPO / self.settings.self_compile_entry
        scenario.facts["entry"] = self.settings.self_compile_entry
        measure = TimeReport.available()
        for _ in range(self.settings.cold_samples):
            state.reset(objects=False)
            output = state.build / "btrcc.c"
            # The macOS entry's SDK digest provider is a native package, so
            # the target is explicit, as the bootstrap of a host compiler is.
            command = [
                *self.commands.frontend(),
                "--strict-imports",
                "--target",
                self.settings.target,
                str(source),
                "-o",
                str(output),
            ]
            elapsed, completed = self.execute(
                [*TimeReport.command(), *command] if measure else command,
                cwd=REPO,
                env=self.environment(state, timing=False),
                label="self-compile",
            )
            usage = TimeReport.parse(completed.stderr) if measure else TimeReport()
            scenario.add(
                elapsed,
                compile_s=elapsed,
                native_s=0.0,
                metrics={**usage.metrics(""), "c_bytes": output.stat().st_size},
            )

    def run_corpus(self) -> None:
        from src.tests.corpus_files import language_test_files

        root = REPO / "src/tests"
        files = language_test_files(root)
        scenario = self.scenario("corpus")
        scenario.facts.update(files=len(files), jobs=self.settings.corpus_jobs)
        state = self.state("corpus")
        for _ in range(self.settings.cold_samples):
            state.reset(objects=False)
            slots: queue.Queue[Path] = queue.Queue()
            for slot in range(self.settings.corpus_jobs):
                (state.build / f"slot-{slot}").mkdir()
                slots.put(state.build / f"slot-{slot}")
            transpile = functools.partial(
                self.corpus_file, root=root, slots=slots, environment=self.environment(state, timing=False)
            )
            started = time.perf_counter()
            with ThreadPoolExecutor(self.settings.corpus_jobs) as pool:
                results = list(pool.map(transpile, files))
            elapsed = time.perf_counter() - started
            failures = [(relative, error) for relative, _, code, _, error in results if code != 0]
            if failures:
                names = ", ".join(relative for relative, _ in failures[:10])
                raise RuntimeError(
                    f"corpus: {len(failures)} of {len(files)} programs failed ({names}):\n{failures[0][1]}"
                )
            rss = [result[3] for result in results]
            scenario.add(
                elapsed,
                compile_s=elapsed,
                native_s=0.0,
                metrics={
                    "summed_file_s": round(sum(result[1] for result in results), 3),
                    "max_rss_bytes": max(rss),
                    "median_rss_bytes": int(statistics.median(rss)),
                },
            )

    def corpus_file(
        self, relative: str, *, root: Path, slots: queue.Queue[Path], environment: dict[str, str]
    ) -> tuple[str, float, int, int, str]:
        """One corpus transpile in a free output slot, with its own peak RSS from wait4's rusage."""
        slot = slots.get()
        try:
            command = [*self.commands.frontend(), str(root / relative), "-o", str(slot / "out.c")]
            error_path = slot / "stderr.txt"
            started = time.perf_counter()
            with error_path.open("w") as error:
                process = subprocess.Popen(command, cwd=REPO, env=environment, stdout=subprocess.DEVNULL, stderr=error)
                _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
            elapsed = time.perf_counter() - started
            message = error_path.read_text(errors="replace")[-2000:] if process.returncode else ""
        finally:
            slots.put(slot)
        rss = usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        return relative, elapsed, process.returncode, rss, message

    # -- run -----------------------------------------------------------------

    def collect_provenance(self) -> dict[str, object]:
        def output(*command: str) -> str | None:
            try:
                completed = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=60)
            except (OSError, subprocess.TimeoutExpired):
                return None
            return completed.stdout.strip() if completed.returncode == 0 else None

        provenance: dict[str, object] = {
            "compiler_revision": output("git", "-C", str(REPO), "rev-parse", "HEAD"),
            "compiler_dirty": bool(output("git", "-C", str(REPO), "status", "--porcelain")),
            "frontend_command": self.commands.frontend(),
            "host": platform.uname()._asdict(),
            "cpu_count": os.cpu_count(),
            "python": sys.version,
            "cc": (output(CC, "--version") or "").split("\n")[0],
            "time_tool": shlex.join(TimeReport.command()) if TimeReport.available() else None,
            "environment": {
                name: os.environ[name]
                for name in (
                    "BTRC_NATIVE_HEADER_READER",
                    "BTRC_NATIVE_TARGET",
                    "BTRC_NATIVE_SYSROOT",
                    "SDKROOT",
                    "PKG_CONFIG_PATH",
                )
                if name in os.environ
            },
        }
        if self.settings.btrcc is not None:
            with self.settings.btrcc.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            provenance["btrcc"] = {
                "path": str(self.settings.btrcc),
                "sha256": digest,
                "bytes": self.settings.btrcc.stat().st_size,
            }
        return provenance

    def report(self, failure: str | None) -> dict[str, object]:
        return {
            "schema": 2,
            "tool": "tools/budget_bench.py",
            "dry_run": self.settings.dry_run,
            "started": self.started.isoformat(timespec="seconds"),
            "finished": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "failure": failure,
            "configuration": self.settings.describe(),
            "provenance": self.provenance,
            "scenarios": {name: scenario.summary() for name, scenario in self.results.items()},
        }

    def run(self) -> dict[str, object]:
        selected = set(self.settings.scenarios)
        failure: str | None = None
        try:
            if "cold" in selected:
                self.run_cold()
            if "release" in selected:
                self.run_release()
            if selected & set(INCREMENTAL_SCENARIOS):
                self.run_incremental()
            if "memory" in selected:
                self.run_memory()
            if "workers" in selected:
                self.run_workers()
            if "batch" in selected:
                self.run_batch()
            if "self-compile" in selected:
                self.run_self_compile()
            if "corpus" in selected:
                self.run_corpus()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            failure = str(error)
            raise
        finally:
            report = self.report(failure)
            (self.out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            if failure is None and not self.settings.keep:
                RunDirectory.prune(self.out)
        self.print_table(report)
        return report

    @staticmethod
    def print_table(report: dict[str, object]) -> None:
        print(f"\n{'scenario':24} {'median':>8} {'p95':>8} {'max':>8}  samples")
        scenarios = report["scenarios"]
        assert isinstance(scenarios, dict)
        for name, summary in scenarios.items():
            if summary["median"] is None:
                continue
            print(
                f"{name:24} {summary['median']:8.2f} {summary['p95']:8.2f} {summary['max']:8.2f}  {len(summary['samples'])}"
            )


def main(argv: Sequence[str] | None = None) -> int:
    settings = BenchSettings.parse(argv)
    try:
        BudgetBench(settings).run()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"budget_bench: {error}", file=sys.stderr)
        print(f"report: {settings.out / 'report.json'}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
