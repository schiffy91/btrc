"""Host provenance summary, hardware detection, and order statistics for benchmarks."""

from __future__ import annotations

import datetime
import hashlib
import math
import os
import platform as host_platform
import re
import shlex
import statistics
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class Statistic(StrEnum):
    """A summary a budget can be stated against."""

    MEDIAN = "median"
    P95 = "p95"
    P99 = "p99"
    P999 = "p99.9"
    MAX = "max"


@dataclass(frozen=True, slots=True)
class SampleStatistics:
    """Median, nearest-rank p95/p99/p99.9, minimum and maximum of one non-empty sample set."""

    count: int
    median: float
    p95: float
    p99: float
    p999: float
    minimum: float
    maximum: float

    @classmethod
    def of(cls, samples: Iterable[float]) -> SampleStatistics | None:
        """Summarize `samples`, or return None when there are none."""

        ordered = sorted(float(sample) for sample in samples)
        if not ordered:
            return None
        if not all(math.isfinite(sample) for sample in ordered):
            raise ValueError("samples must be finite numbers")
        return cls(
            count=len(ordered),
            median=statistics.median(ordered),
            p95=cls.nearest_rank(ordered, 0.95),
            p99=cls.nearest_rank(ordered, 0.99),
            p999=cls.nearest_rank(ordered, 0.999),
            minimum=ordered[0],
            maximum=ordered[-1],
        )

    @staticmethod
    def nearest_rank(ordered: list[float], fraction: float) -> float:
        """The nearest-rank percentile of an ascending, non-empty sample list."""

        if not ordered:
            raise ValueError("nearest-rank percentile of no samples")
        if not 0.0 < fraction <= 1.0:
            raise ValueError("percentile fraction must be in (0, 1]")
        rank = max(1, math.ceil(fraction * len(ordered)))
        return ordered[rank - 1]

    def value(self, statistic: Statistic) -> float:
        """The summary a budget names."""

        values = {
            Statistic.MEDIAN: self.median,
            Statistic.P95: self.p95,
            Statistic.P99: self.p99,
            Statistic.P999: self.p999,
            Statistic.MAX: self.maximum,
        }
        return values[statistic]


@dataclass(frozen=True)
class Provenance:
    """The environment a measurement came from."""

    source: str | None = None
    recorded_at: str | None = None
    runner: str | None = None
    btrc_revision: str | None = None
    btrsmith_revision: str | None = None
    frontend: str | None = None
    target_triple: str | None = None
    sdk_build: str | None = None
    os_build: str | None = None
    device_id: str | None = None
    device_class: str | None = None
    cpu: str | None = None
    memory: str | None = None
    c_compiler: str | None = None
    compiler_digest: str | None = None
    jobs: str | None = None
    build_mode: str | None = None
    scale: str | None = None
    thermal: str | None = None
    power: str | None = None


class HostProvenance:
    """Describe this machine for a report, without private identifiers."""

    def __init__(self, repo: Path = REPO) -> None:
        self.repo = repo

    def detect(self, *, workspace: Path | None = None, compiler: Path | None = None, **given: str | None) -> Provenance:
        """Detected fields, overridden by every explicitly `given` one."""

        detected: dict[str, object] = {
            "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "btrc_revision": self._run(["git", "rev-parse", "HEAD"], cwd=self.repo),
            "target_triple": os.environ.get("BTRC_NATIVE_TARGET"),
        }
        if workspace is not None:
            detected["btrsmith_revision"] = self._run(["git", "rev-parse", "HEAD"], cwd=workspace)
        if compiler is not None:
            detected["compiler_digest"] = self.digest(compiler)
        if host_platform.system() == "Darwin":
            version = self._run(["sw_vers", "-productVersion"])
            build = self._run(["sw_vers", "-buildVersion"])
            detected["os_build"] = f"macOS {version} ({build})" if version and build else None
            model = self._run(["sysctl", "-n", "hw.model"])
            chip = self._run(["sysctl", "-n", "machdep.cpu.brand_string"])
            detected["device_class"] = f"{model} ({chip})" if model and chip else model
            detected["cpu"] = self.darwin_cpu()
            detected["memory"] = self.memory(self._run(["sysctl", "-n", "hw.memsize"]))
            detected["thermal"] = self.thermal(self._run(["pmset", "-g", "therm"]))
            detected["power"] = self.power(self._run(["pmset", "-g", "batt"]))
        else:
            detected["os_build"] = f"{host_platform.system()} {host_platform.release()}"
            detected["device_class"] = host_platform.machine() or None
            logical = os.cpu_count()
            detected["cpu"] = f"{logical} logical CPUs" if logical else None
            detected["memory"] = self.memory(self.meminfo_bytes())
        for name, value in given.items():
            if value is not None:
                detected[name] = value
        return Provenance(**{name: value for name, value in detected.items() if value})

    def summary(self) -> str:
        """The one-line host string bench reports record."""

        if host_platform.system() == "Darwin":
            version = self._run(["sw_vers", "-productVersion"])
            fields = (
                self._run(["sysctl", "-n", "machdep.cpu.brand_string"]),
                self.darwin_cpu(),
                self.memory(self._run(["sysctl", "-n", "hw.memsize"])),
                f"macOS {version}" if version else None,
            )
        else:
            logical = os.cpu_count()
            fields = (
                self.cpuinfo_model(),
                f"{logical} logical CPUs" if logical else None,
                self.memory(self.meminfo_bytes()),
                f"{host_platform.system()} {host_platform.release()}",
            )
        chip, *rest = fields
        return ", ".join([chip or host_platform.machine() or "unknown CPU", *(field or "unknown" for field in rest)])

    def darwin_cpu(self) -> str | None:
        return self.cpu(
            self._run(["sysctl", "-n", "hw.perflevel0.physicalcpu"]),
            self._run(["sysctl", "-n", "hw.perflevel1.physicalcpu"]),
            self._run(["sysctl", "-n", "hw.physicalcpu"]),
        )

    @staticmethod
    def cpuinfo_model(path: Path = Path("/proc/cpuinfo")) -> str | None:
        """The first ``model name`` (x86) or ``Model`` (arm) line of /proc/cpuinfo."""

        try:
            text = path.read_text(errors="replace")
        except OSError:
            return None
        for line in text.splitlines():
            key, separator, value = line.partition(":")
            if separator and key.strip() in {"model name", "Model"} and value.strip():
                return value.strip()
        return None

    @staticmethod
    def cpu(performance: str | None, efficiency: str | None, physical: str | None) -> str | None:
        """Core topology: ``8P+2E`` on a hybrid chip, else the physical core count."""

        if performance and efficiency:
            return f"{performance}P+{efficiency}E"
        return f"{physical} cores" if physical else None

    @staticmethod
    def memory(total_bytes: str | None) -> str | None:
        """Installed memory in GiB: ``64 GiB``."""

        if not total_bytes or not total_bytes.isdigit():
            return None
        return f"{round(int(total_bytes) / 2**30, 1):g} GiB"

    @staticmethod
    def meminfo_bytes(path: Path = Path("/proc/meminfo")) -> str | None:
        try:
            match = re.search(r"^MemTotal:\s+(\d+) kB$", path.read_text(), re.MULTILINE)
        except OSError:
            return None
        return str(int(match.group(1)) * 1024) if match else None

    @staticmethod
    def digest(path: Path) -> str:
        """``sha256:`` of a compiler binary, which names exactly what was measured."""

        hasher = hashlib.sha256()
        with path.open("rb") as binary:
            for chunk in iter(lambda: binary.read(1 << 20), b""):
                hasher.update(chunk)
        return f"sha256:{hasher.hexdigest()}"

    def c_compiler(self, command: str, flags: str = "") -> str | None:
        """What built a btrcc: the first line of ``command --version`` and its flags."""

        version = self._run([*shlex.split(command), "--version"])
        if version is None:
            return None
        return " ".join(filter(None, (version.splitlines()[0], flags.strip())))

    @staticmethod
    def thermal(text: str | None) -> str | None:
        if not text:
            return None
        if "No thermal warning level has been recorded" in text:
            return "nominal"
        limits = re.findall(r"(\w+)\s*=\s*(\d+)", text)
        return ", ".join(f"{name}={value}" for name, value in limits) or None

    @staticmethod
    def power(text: str | None) -> str | None:
        match = re.search(r"drawing from '([^']+)'", text or "")
        return match.group(1) if match else None

    @staticmethod
    def _run(command: list[str], cwd: Path | None = None) -> str | None:
        try:
            completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        output = completed.stdout.strip()
        return output if completed.returncode == 0 and output else None
