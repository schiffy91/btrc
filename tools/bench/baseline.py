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
# parity is a boolean contract.
TOLERANCES: dict[str, float] = {"ms": 0.35, "bytes": 0.03, "lines": 0.03, "parity": 0.0, "count": 0.0, "info": 0.0}
IMPROVEMENT_NOTE = 0.20


def platform_key() -> str:
    """One key per operating system and architecture family."""

    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        machine = "arm64"
    elif machine in {"x86_64", "amd64"}:
        machine = "x86_64"
    return f"{sys.platform}-{machine}"


INFORMATIONAL_PREFIXES = ("btrcc.phase.",)


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
    for kind in ("bytes", "lines", "parity", "count"):
        if tail == kind or tail.endswith("_" + kind):
            return kind
    raise ValueError(f"metric {name!r} does not end in a known kind")


@dataclass(frozen=True)
class Finding:
    name: str
    baseline: float | None
    current: float
    status: str  # "ok" | "regression" | "improvement" | "new"

    @property
    def ratio(self) -> float | None:
        if self.baseline in (None, 0):
            return None
        return self.current / self.baseline


def compare(
    current: dict[str, float], baseline: dict[str, float] | None, tolerance_ms: float | None = None
) -> list[Finding]:
    """Compare one run against a platform baseline metric by metric."""

    findings: list[Finding] = []
    for name in sorted(current):
        value = float(current[name])
        kind = metric_kind(name)
        reference = None if baseline is None else baseline.get(name)
        if reference is None:
            findings.append(Finding(name, None, value, "new"))
            continue
        reference = float(reference)
        tolerance = TOLERANCES[kind]
        if kind == "ms" and tolerance_ms is not None:
            tolerance = tolerance_ms
        if kind == "info":
            status = "ok"
        elif kind in {"parity", "count"}:
            status = "ok" if value == reference else "regression"
        elif reference == 0:
            status = "ok" if value == 0 else "regression"
        elif value > reference * (1.0 + tolerance):
            status = "regression"
        elif kind == "ms" and value < reference * (1.0 - IMPROVEMENT_NOTE):
            status = "improvement"
        else:
            status = "ok"
        findings.append(Finding(name, reference, value, status))
    return findings


def load(path: Path = BASELINE_PATH) -> dict:
    if not path.is_file():
        return {"schema": SCHEMA_VERSION, "platforms": {}}
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != SCHEMA_VERSION:
        raise ValueError(f"{path}: unsupported baseline schema {document.get('schema')!r}")
    return document


def platform_metrics(document: dict, key: str) -> dict[str, float] | None:
    entry = document.get("platforms", {}).get(key)
    return None if entry is None else dict(entry["metrics"])


def store(document: dict, key: str, metrics: dict[str, float], meta: dict, path: Path = BASELINE_PATH) -> None:
    """Record metrics for one platform, keeping every other platform as it is."""

    platforms = dict(document.get("platforms", {}))
    platforms[key] = {"recorded": meta, "metrics": {name: metrics[name] for name in sorted(metrics)}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "platforms": dict(sorted(platforms.items()))}, indent=2, sort_keys=False)
        + "\n",
        encoding="utf-8",
    )


def render(findings: list[Finding]) -> str:
    """A fixed-width table, worst news first."""

    order = {"regression": 0, "improvement": 1, "new": 2, "ok": 3}
    rows = sorted(findings, key=lambda finding: (order[finding.status], finding.name))
    width = max((len(finding.name) for finding in rows), default=10)
    lines = [f"{'metric':<{width}}  {'baseline':>12}  {'current':>12}  {'ratio':>6}  status"]
    for finding in rows:
        base = "-" if finding.baseline is None else _number(finding.baseline)
        ratio = "-" if finding.ratio is None else f"{finding.ratio:5.2f}x"
        lines.append(
            f"{finding.name:<{width}}  {base:>12}  {_number(finding.current):>12}  {ratio:>6}  {finding.status}"
        )
    return "\n".join(lines)


def _number(value: float) -> str:
    return f"{value:.0f}" if float(value).is_integer() else f"{value:.3f}"
