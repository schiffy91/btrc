"""Turn the evidence the tree already produces into ledger records.

Each adapter emits one record per slot of a *declared* denominator, so a run
that is missing evidence still counts the slot (as unrecorded) instead of
shrinking the denominator:

- `BudgetBenchAdapter`: a ``tools.budget_bench`` ``report.json``, against
  ``budget_bench.SCENARIOS``.
- `JUnitAdapter`: a pytest ``--junitxml`` run, against its collected cases.
- `SkipReportAdapter`: a gate's ``build/skip-report*.json``, against every
  test the session collected, with each skip's coverage.
- `BoundaryReportAdapter`: ``boundary-check --report``, against every frozen
  boundary record in the manifest.
"""

from __future__ import annotations

import datetime
import math
import os
import platform as host_platform
import re
import subprocess
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

from tools.qualification.schema import (
    Budget,
    Evidence,
    EvidenceStatus,
    Frontend,
    LedgerRecord,
    LedgerSchemaError,
    Measurement,
    Platform,
    Provenance,
    Subject,
    SubjectKind,
)
from tools.qualification.statistics import SampleStatistics

REPO = Path(__file__).resolve().parents[2]
RUNNER_PLATFORMS = {
    "macos": Platform.MACOS,
    "linux": Platform.LINUX,
    "linux-devcontainer": Platform.LINUX,
    "windows": Platform.WINDOWS,
    "ios": Platform.IOS,
    "android": Platform.ANDROID,
}


class HostProvenance:
    """Describe this machine for a record, without private identifiers."""

    def __init__(self, repo: Path = REPO) -> None:
        self.repo = repo

    def detect(self, **given: str | None) -> Provenance:
        """Detected fields, overridden by every explicitly `given` one."""

        detected: dict[str, Any] = {
            "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "btrc_revision": self._run(["git", "rev-parse", "HEAD"], cwd=self.repo),
            "target_triple": os.environ.get("BTRC_NATIVE_TARGET"),
        }
        # Only identifying-free facts: a model name and chip, never a hostname or serial number.
        if host_platform.system() == "Darwin":
            version = self._run(["sw_vers", "-productVersion"])
            build = self._run(["sw_vers", "-buildVersion"])
            detected["os_build"] = f"macOS {version} ({build})" if version and build else None
            model = self._run(["sysctl", "-n", "hw.model"])
            chip = self._run(["sysctl", "-n", "machdep.cpu.brand_string"])
            detected["device_class"] = f"{model} ({chip})" if model and chip else model
            detected["thermal"] = self.thermal(self._run(["pmset", "-g", "therm"]))
            detected["power"] = self.power(self._run(["pmset", "-g", "batt"]))
        else:
            detected["os_build"] = f"{host_platform.system()} {host_platform.release()}"
            detected["device_class"] = host_platform.machine() or None
        for name, value in given.items():
            if value is not None:
                detected[name] = value
        if isinstance(detected.get("frontend"), str):
            detected["frontend"] = Frontend(detected["frontend"])
        return Provenance(**{name: value for name, value in detected.items() if value})

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


class BudgetBenchAdapter:
    """One scenario record per declared budget_bench scenario."""

    COLD_MINIMUM = 5
    INCREMENTAL_MINIMUM = 20
    _PEAK = re.compile(r"peak footprint (-?\d+) bytes")
    _AGGREGATE = re.compile(r"aggregate RSS peak (\d+) bytes")

    def __init__(
        self,
        provenance: Provenance,
        *,
        platform: Platform = Platform.MACOS,
        budgets: Mapping[str, tuple[Budget, ...]] | None = None,
        artifact: str | None = None,
        recorded_at: str | None = None,
    ) -> None:
        self.provenance = replace(
            provenance,
            source="budget_bench",
            frontend=Frontend.SELFHOST,
            build_mode=provenance.build_mode or "debug",
            recorded_at=recorded_at or provenance.recorded_at,
        )
        self.platform = platform
        self.budgets = dict(budgets or {})
        self.artifact = artifact

    @staticmethod
    def declared() -> tuple[str, ...]:
        from tools.budget_bench import SCENARIOS

        return SCENARIOS

    def records(self, report: Mapping[str, Any], where: str = "budget_bench report") -> list[LedgerRecord]:
        declared = self.declared()
        unknown = sorted(set(report) - set(declared))
        if unknown:
            raise LedgerSchemaError(f"{where}: scenario(s) {', '.join(unknown)} are not budget_bench SCENARIOS")
        unknown_budgets = sorted(set(self.budgets) - set(declared))
        if unknown_budgets:
            raise LedgerSchemaError(f"budgets name unknown scenario(s) {', '.join(unknown_budgets)}")
        return [self.record(name, report.get(name), f"{where}.{name}") for name in declared]

    def record(self, name: str, summary: Mapping[str, Any] | None, where: str) -> LedgerRecord:
        subject = Subject(
            kind=SubjectKind.SCENARIO,
            id=name,
            platform=self.platform,
            frontend=Frontend.SELFHOST,
            group="budget_bench",
        )
        if summary is None:
            return LedgerRecord(subject=subject, provenance=self.provenance)
        measurement = self.measurement(name, summary, where)
        if measurement is None:
            evidence = Evidence(
                status=EvidenceStatus.UNAVAILABLE,
                observed="unmeasured",
                reason="the run reported no samples",
                artifact=self.artifact,
            )
            return LedgerRecord(subject=subject, evidence=evidence, provenance=self.provenance)
        shortfalls = measurement.shortfalls()
        evidence = Evidence(
            status=EvidenceStatus.IMPLEMENTED_UNVERIFIED if shortfalls else EvidenceStatus.PASSED,
            observed="measured",
            reason="; ".join(shortfalls) or None,
            artifact=self.artifact,
        )
        return LedgerRecord(subject=subject, evidence=evidence, measurement=measurement, provenance=self.provenance)

    def measurement(self, name: str, summary: Mapping[str, Any], where: str) -> Measurement | None:
        if name == "memory":
            return self._memory(summary)
        samples = summary.get("samples") or []
        if not samples:
            return None
        parts = summary.get("compile_native") or []
        if len(parts) != len(samples):
            raise LedgerSchemaError(f"{where}: {len(parts)} compile/native pairs for {len(samples)} samples")
        recomputed = SampleStatistics.of(samples)
        for field, value in (("median", recomputed.median), ("p95", recomputed.p95), ("max", recomputed.maximum)):
            reported = summary.get(field)
            if reported is None or not math.isclose(reported, value, abs_tol=1e-3):
                raise LedgerSchemaError(f"{where}.{field}: reported {reported}, its samples give {value:.3f}")
        return Measurement(
            metric="wall-time",
            unit="s",
            samples=tuple(samples),
            minimum_samples=self.COLD_MINIMUM if name.startswith("cold-") else self.INCREMENTAL_MINIMUM,
            components={"compile": tuple(part[0] for part in parts), "native": tuple(part[1] for part in parts)},
            budgets=self.budgets.get(name, ()),
        )

    def _memory(self, summary: Mapping[str, Any]) -> Measurement | None:
        notes = " ".join(summary.get("notes") or [])
        peak = self._PEAK.search(notes)
        if peak is None or int(peak.group(1)) < 0:
            return None
        aggregate = self._AGGREGATE.search(notes)
        return Measurement(
            metric="peak-footprint",
            unit="bytes",
            samples=(int(peak.group(1)),),
            minimum_samples=1,
            components={"aggregate-rss": (int(aggregate.group(1)),)} if aggregate else {},
            budgets=self.budgets.get("memory", ()),
        )


class JUnitAdapter:
    """One test record per JUnit test case, keyed by its pytest node id."""

    def __init__(self, provenance: Provenance, *, platform: Platform | None, repo: Path = REPO) -> None:
        self.provenance = replace(provenance, source="junit")
        self.platform = platform
        self.repo = repo

    def nodeid(self, classname: str, name: str) -> str:
        """Invert pytest's dotted ``classname`` back to ``path::Class::name`` where the file exists."""

        parts = classname.split(".") if classname else []
        for split in range(len(parts), 0, -1):
            candidate = Path(*parts[:split]).with_suffix(".py")
            if (self.repo / candidate).is_file():
                return "::".join([candidate.as_posix(), *parts[split:], name])
        return f"{classname}::{name}" if classname else name

    def records(self, path: Path, artifact: str | None = None) -> list[LedgerRecord]:
        try:
            root = ElementTree.parse(path).getroot()
        except ElementTree.ParseError as error:
            raise LedgerSchemaError(f"{path}: {error}") from None
        records: dict[str, LedgerRecord] = {}
        provenance = self.provenance
        suite = root if root.tag == "testsuite" else root.find("testsuite")
        if suite is not None and suite.get("timestamp"):
            moment = datetime.datetime.fromisoformat(suite.get("timestamp"))
            if moment.tzinfo is None:
                moment = moment.astimezone()
            provenance = replace(provenance, recorded_at=moment.isoformat(timespec="seconds"))
        for case in root.iter("testcase"):
            nodeid = self.nodeid(case.get("classname", ""), case.get("name", ""))
            records[nodeid] = LedgerRecord(
                subject=Subject(
                    kind=SubjectKind.TEST,
                    id=nodeid,
                    platform=self.platform,
                    group=nodeid.split("::", 1)[0],
                ),
                evidence=self.evidence(case, artifact),
                provenance=provenance,
            )
        return list(records.values())

    @staticmethod
    def evidence(case: ElementTree.Element, artifact: str | None) -> Evidence:
        for tag, observed in (("error", "error"), ("failure", "failed")):
            element = case.find(tag)
            if element is not None:
                return Evidence(
                    status=EvidenceStatus.IMPLEMENTED_UNVERIFIED,
                    observed=observed,
                    reason=element.get("message") or None,
                    artifact=artifact,
                )
        skipped = case.find("skipped")
        if skipped is not None:
            reason = (skipped.get("message") or "").removeprefix("Skipped: ") or None
            if skipped.get("type") == "pytest.xfail":
                return Evidence(EvidenceStatus.IMPLEMENTED_UNVERIFIED, "xfailed", reason, artifact)
            return Evidence(EvidenceStatus.UNAVAILABLE, "skipped", reason, artifact)
        return Evidence(EvidenceStatus.PASSED, "passed", None, artifact)


class SkipReportAdapter:
    """Every test a gate's session collected, with each skip's reason and coverage."""

    _STATUS: ClassVar[dict[str, EvidenceStatus]] = {
        "passed": EvidenceStatus.PASSED,
        "xpassed": EvidenceStatus.PASSED,
        "failed": EvidenceStatus.IMPLEMENTED_UNVERIFIED,
        "error": EvidenceStatus.IMPLEMENTED_UNVERIFIED,
        "xfailed": EvidenceStatus.IMPLEMENTED_UNVERIFIED,
        "skipped": EvidenceStatus.UNAVAILABLE,
    }

    def __init__(self, provenance: Provenance) -> None:
        self.provenance = provenance

    def records(self, report: Mapping[str, Any], artifact: str | None = None) -> list[LedgerRecord]:
        runner = report["runner"]
        host = report.get("host") or {}
        provenance = replace(
            self.provenance,
            source="skip-report",
            runner=runner,
            btrc_revision=report.get("revision") or self.provenance.btrc_revision,
            recorded_at=report.get("finished_at") or self.provenance.recorded_at,
            os_build=" ".join(filter(None, (host.get("system"), host.get("release")))) or self.provenance.os_build,
        )
        platform = RUNNER_PLATFORMS.get(runner)
        skips = {skip["nodeid"]: skip for skip in report.get("skips") or ()}
        records = []
        for nodeid, outcome in sorted((report.get("tests") or {}).items()):
            skip = skips.get(nodeid)
            if outcome == "skipped" and skip is not None:
                covered = skip.get("covered_by")
                reason = skip.get("reason") or None
                if not skip.get("expected", False):
                    reason = f"unexpected skip: {reason}"
                evidence = Evidence(
                    status=EvidenceStatus.UNAVAILABLE,
                    observed="skipped",
                    reason=reason,
                    artifact=artifact,
                    covered_by=tuple(covered) if covered is not None else None,
                )
            else:
                evidence = Evidence(status=self._STATUS[outcome], observed=outcome, artifact=artifact)
            records.append(
                LedgerRecord(
                    subject=Subject(
                        kind=SubjectKind.TEST,
                        id=nodeid,
                        platform=platform,
                        group=nodeid.split("::", 1)[0],
                    ),
                    evidence=evidence,
                    provenance=provenance,
                )
            )
        return records


class BoundaryReportAdapter:
    """Every frozen boundary record, checked or skipped as incompatible on this host."""

    SCHEMA = "btrc.boundary-check/1"

    def __init__(self, provenance: Provenance, *, platform: Platform | None) -> None:
        self.provenance = replace(provenance, source="boundary-check")
        self.platform = platform

    def records(self, report: Mapping[str, Any], artifact: str | None = None) -> list[LedgerRecord]:
        if report.get("schema") != self.SCHEMA:
            raise LedgerSchemaError(f"not a {self.SCHEMA} report")
        provenance = replace(self.provenance, recorded_at=report.get("created_at") or self.provenance.recorded_at)
        records = []
        for entry in report.get("records") or ():
            if entry["checked"]:
                evidence = Evidence(EvidenceStatus.PASSED, "checked", None, artifact)
            else:
                evidence = Evidence(
                    EvidenceStatus.UNAVAILABLE,
                    "skipped",
                    f"observed capability {entry['capability']} is incompatible on this host",
                    artifact,
                )
            records.append(
                LedgerRecord(
                    subject=Subject(
                        kind=SubjectKind.BOUNDARY_RECORD,
                        id=entry["id"],
                        platform=self.platform,
                        group=f"{entry['fixture']}/{entry['capability']}",
                    ),
                    evidence=evidence,
                    provenance=provenance,
                )
            )
        checked = sum(1 for entry in report.get("records") or () if entry["checked"])
        if len(records) != report.get("total_records") or checked != report.get("checked_records"):
            raise LedgerSchemaError("boundary report totals disagree with its records")
        return records
