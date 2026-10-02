"""Tracked per-platform baselines and regression comparison."""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

BASELINE_PATH = Path("src/tests/fixtures/benchmarks/baseline.json")
SCHEMA_VERSION = 1

# Relative slack per metric kind. Timings are compared as best-of-N wall or CPU
# time and still move with the host, so they get room; sizes are exact and
# parity is a boolean contract. A peak is a compile's peak memory in bytes: its
# footprint on macOS, its maximum resident set elsewhere. The self-host
# `--jobs 1` peak sits 35 MiB under its 3 GiB M11 budget, so growth past 2% is a
# regression; that workload repeats to within 0.7% however loaded the host is.
# Identical small compiles still differ by a few hundred KiB of allocator
# regions and 16 KiB pages (a 4 MiB compile by up to 9%), so a peak's slack is
# never under PEAK_FLOOR bytes.
TOLERANCES: dict[str, float] = {
    "ms": 0.35,
    "bytes": 0.03,
    "lines": 0.03,
    "parity": 0.0,
    "count": 0.0,
    "peak": 0.02,
    "info": 0.0,
}
IMPROVEMENT_NOTE = 0.20
PEAK_FLOOR = 1 << 20
INFORMATIONAL_PREFIXES = ("btrcc.phase.",)


@dataclass(frozen=True)
class Finding:
    name: str
    baseline: float | None
    current: float
    status: str  # "ok" | "regression" | "slower" | "improvement" | "new"

    @property
    def ratio(self) -> float | None:
        if self.baseline in (None, 0):
            return None
        return self.current / self.baseline


class Baseline:
    """The tracked per-platform baseline document and comparison against it."""

    @staticmethod
    def platform_key() -> str:
        """One key per operating system and architecture family."""

        machine = platform.machine().lower()
        if machine in {"arm64", "aarch64"}:
            machine = "arm64"
        elif machine in {"x86_64", "amd64"}:
            machine = "x86_64"
        return f"{sys.platform}-{machine}"

    @staticmethod
    def metric_kind(name: str) -> str:
        """The comparison kind a metric name declares through its last component.

        Per-phase compiler timings are recorded for attribution but never gate: a
        mark that moves or a phase that splits changes where time is attributed
        without changing the compile, and the compile's own timing is compared.
        """

        if name.startswith(INFORMATIONAL_PREFIXES):
            return "info"
        tail = name.rsplit(".", 1)[-1]
        if tail.endswith("_ms"):
            return "ms"
        for kind in ("bytes", "lines", "parity", "count", "peak"):
            if tail == kind or tail.endswith("_" + kind):
                return kind
        raise ValueError(f"metric {name!r} does not end in a known kind")

    @classmethod
    def compare(
        cls,
        current: dict[str, float],
        baseline: dict[str, float] | None,
        tolerance_ms: float | None = None,
        tolerance_peak: float | None = None,
        *,
        gate_timings: bool = True,
    ) -> list[Finding]:
        """Compare one run against a platform baseline metric by metric.

        A peak's slack is its relative tolerance or PEAK_FLOOR bytes, whichever is
        larger, in both directions: a peak that falls past it is an improvement, so
        the baseline gets re-recorded and the guard does not drift loose.

        Without `gate_timings`, a timing past its slack is "slower", reported but
        not a regression. A pool of hosted runners is not one machine: GitHub's
        ubuntu-latest runs of the same tree differed by up to 2.15x on one timing
        and 1.45x across most of them, while sizes, lines, parity and peaks
        repeated exactly.
        """

        findings: list[Finding] = []
        for name in sorted(current):
            value = float(current[name])
            kind = cls.metric_kind(name)
            reference = None if baseline is None else baseline.get(name)
            if reference is None:
                findings.append(Finding(name, None, value, "new"))
                continue
            reference = float(reference)
            tolerance = TOLERANCES[kind]
            if kind == "ms" and tolerance_ms is not None:
                tolerance = tolerance_ms
            if kind == "peak" and tolerance_peak is not None:
                tolerance = tolerance_peak
            if kind == "info":
                status = "ok"
            elif kind in {"parity", "count"}:
                status = "ok" if value == reference else "regression"
            elif reference == 0:
                status = "ok" if value == 0 else "regression"
            elif kind == "peak":
                slack = max(reference * tolerance, PEAK_FLOOR)
                status = (
                    "regression" if value > reference + slack else "improvement" if value < reference - slack else "ok"
                )
            elif value > reference * (1.0 + tolerance):
                status = "regression" if gate_timings or kind != "ms" else "slower"
            elif kind == "ms" and value < reference * (1.0 - IMPROVEMENT_NOTE):
                status = "improvement"
            else:
                status = "ok"
            findings.append(Finding(name, reference, value, status))
        return findings

    @classmethod
    def over_budget(cls, current: dict[str, float], budget_gib: float | None) -> list[str]:
        """The workload peaks above an absolute budget, which no baseline can loosen.

        The relative slack guards against drift; the budget is the M11 criterion
        itself, and 2% of a 2.966 GiB peak is more than the 35 MiB left under it.
        """

        if budget_gib is None:
            return []
        return sorted(
            name
            for name, value in current.items()
            if name.startswith("btrcc.workload.") and cls.metric_kind(name) == "peak" and value > budget_gib * 2**30
        )

    @staticmethod
    def load(path: Path = BASELINE_PATH) -> dict:
        if not path.is_file():
            return {"schema": SCHEMA_VERSION, "platforms": {}}
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schema") != SCHEMA_VERSION:
            raise ValueError(f"{path}: unsupported baseline schema {document.get('schema')!r}")
        return document

    @staticmethod
    def platform_metrics(document: dict, key: str) -> dict[str, float] | None:
        entry = document.get("platforms", {}).get(key)
        return None if entry is None else dict(entry["metrics"])

    @staticmethod
    def store(
        document: dict,
        key: str,
        metrics: dict[str, float],
        meta: dict,
        path: Path = BASELINE_PATH,
        *,
        merge: bool = False,
    ) -> None:
        """Record metrics for one platform, keeping every other platform as it is.

        `merge` keeps the platform's metrics this run did not measure, so a
        peak-only run refreshes the peaks without re-recording every timing. The
        platform's original `recorded` stays, and each merge appends its own
        metadata, with the names it measured, to `updates`.
        """

        platforms = dict(document.get("platforms", {}))
        previous = platforms.get(key) if merge else None
        if previous is None:
            platforms[key] = {"recorded": meta, "metrics": {name: metrics[name] for name in sorted(metrics)}}
        else:
            merged = {**previous["metrics"], **metrics}
            platforms[key] = {
                "recorded": previous["recorded"],
                "updates": [*previous.get("updates", []), {**meta, "metrics": sorted(metrics)}],
                "metrics": {name: merged[name] for name in sorted(merged)},
            }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"schema": SCHEMA_VERSION, "platforms": dict(sorted(platforms.items()))}, indent=2, sort_keys=False
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def render(cls, findings: list[Finding]) -> str:
        """A fixed-width table, worst news first."""

        order = {"regression": 0, "slower": 1, "improvement": 2, "new": 3, "ok": 4}
        rows = sorted(findings, key=lambda finding: (order[finding.status], finding.name))
        width = max((len(finding.name) for finding in rows), default=10)
        lines = [f"{'metric':<{width}}  {'baseline':>12}  {'current':>12}  {'ratio':>6}  status"]
        for finding in rows:
            base = "-" if finding.baseline is None else cls.number(finding.baseline)
            ratio = "-" if finding.ratio is None else f"{finding.ratio:5.2f}x"
            lines.append(
                f"{finding.name:<{width}}  {base:>12}  {cls.number(finding.current):>12}  {ratio:>6}  {finding.status}"
            )
        return "\n".join(lines)

    @staticmethod
    def number(value: float) -> str:
        """One metric value as the tables print it: integers bare, else three places."""

        return f"{value:.0f}" if float(value).is_integer() else f"{value:.3f}"
