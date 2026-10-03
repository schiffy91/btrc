"""Turn the evidence the tree already produces into ledger records.

Each adapter emits one record per slot of a *declared* denominator, so a run
that is missing evidence still counts the slot (as unrecorded) instead of
shrinking the denominator:

- `BudgetBenchAdapter`: a ``tools.budget_bench`` ``report.json``, against
  ``budget_bench.REPORTED_SCENARIOS``, with the host and compiler the run
  measured.
- `JUnitAdapter`: a pytest ``--junitxml`` run, against its collected cases.
- `SkipReportAdapter`: a gate's ``build/skip-report*.json``, against every
  test the session collected, with each skip's coverage.
- `BoundaryReportAdapter`: ``boundary-check --report``, against every frozen
  boundary record in the manifest.
"""

from __future__ import annotations

import datetime
import hashlib
import math
import os
import platform as host_platform
import re
import shlex
import subprocess
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping, Sequence
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
    "macos-hosted": Platform.MACOS,
    "linux": Platform.LINUX,
    "linux-devcontainer": Platform.LINUX,
    "windows": Platform.WINDOWS,
    "ios": Platform.IOS,
    "android": Platform.ANDROID,
}


class HostProvenance:
    """Describe this machine for a record, without private identifiers.

    A report that embeds ``detect(workspace=..., compiler=...)`` carries the
    host, BTRSmith revision and compiler digest it measured instead of
    whatever machine later ingests it. `tools.budget_bench`'s schema-2 report
    records its own provenance, which `BudgetBenchAdapter` translates.
    """

    def __init__(self, repo: Path = REPO) -> None:
        self.repo = repo

    def detect(self, *, workspace: Path | None = None, compiler: Path | None = None, **given: str | None) -> Provenance:
        """Detected fields, overridden by every explicitly `given` one.

        `workspace` is the BTRSmith checkout a run built, and `compiler` the
        btrcc binary it measured.
        """

        detected: dict[str, Any] = {
            "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "btrc_revision": self._run(["git", "rev-parse", "HEAD"], cwd=self.repo),
            "target_triple": os.environ.get("BTRC_NATIVE_TARGET"),
        }
        if workspace is not None:
            detected["btrsmith_revision"] = self._run(["git", "rev-parse", "HEAD"], cwd=workspace)
        if compiler is not None:
            detected["compiler_digest"] = self.digest(compiler)
        # Only identifying-free facts: a model name and chip, never a hostname or serial number.
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
        if isinstance(detected.get("frontend"), str):
            detected["frontend"] = Frontend(detected["frontend"])
        return Provenance(**{name: value for name, value in detected.items() if value})

    def summary(self) -> str:
        """The one-line host string manifests and bench reports record.

        Four fields -- chip, cores, memory, OS -- so the acceptance Mac reads
        exactly ``Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0`` (AGENTS.md), and any
        other host records what it is in the same shape.
        """

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


class BudgetBenchAdapter:
    """One scenario record per scenario budget_bench can report.

    A report is what ``tools.budget_bench`` writes -- schema 2, ``{"schema":
    2, "configuration": {...}, "provenance": {...}, "scenarios": {...}, ...}``
    -- or a ledger-form one: the scenario table itself, or ``{"provenance":
    {...}, "scenarios": {...}}`` with a ledger provenance. A schema-2 run's
    provenance is translated: its btrc revision, frontend, mode, native
    target and btrcc digest, never its host name. A schema-2 run that failed
    or was a dry run is never accepted. Provenance layers from the ingesting
    command's detection (``--this-host``), through the report's own, to
    explicit flags; an explicit frontend that contradicts the report's is an
    error rather than a relabel. A scenario summary may add ``failures``
    (samples that failed and are not in ``samples``) with one
    ``failure_reasons`` entry each, and ``rebuilt_units`` (one count per
    sample). A ``compile_native`` pair may be null where a build through
    BTRSmith's make has no compile/native split.
    """

    COLD_MINIMUM = 5
    INCREMENTAL_MINIMUM = 20
    BENCH_SCHEMA = 2
    BENCH_FIELDS = frozenset(
        {"schema", "tool", "dry_run", "started", "finished", "failure", "configuration", "provenance", "scenarios"}
    )
    BUILD_MODES: ClassVar[dict[str, str]] = {"dev": "debug", "release": "release"}
    _PEAK = re.compile(r"peak footprint (-?\d+) bytes")
    _AGGREGATE = re.compile(r"aggregate RSS peak (\d+) bytes")
    _INSTRUCTIONS = re.compile(r"instructions retired ([\d,]+)")

    def __init__(
        self,
        provenance: Provenance,
        *,
        explicit: Provenance | None = None,
        platform: Platform | None = None,
        variant: str | None = None,
        budgets: Mapping[str, tuple[Budget, ...]] | None = None,
        artifact: str | None = None,
        recorded_at: str | None = None,
    ) -> None:
        self.base = replace(provenance, recorded_at=recorded_at or provenance.recorded_at)
        self.explicit = explicit or Provenance()
        self.platform = platform
        self.variant = variant
        self.budgets = dict(budgets or {})
        self.artifact = artifact

    @staticmethod
    def declared() -> tuple[str, ...]:
        from tools.budget_bench import REPORTED_SCENARIOS

        return REPORTED_SCENARIOS

    @staticmethod
    def incrementally_sampled() -> tuple[str, ...]:
        from tools.budget_bench import INCREMENTALLY_SAMPLED

        return INCREMENTALLY_SAMPLED

    def provenance(self, embedded: Provenance | None, where: str) -> Provenance:
        measured, claimed = (embedded.frontend if embedded else None), self.explicit.frontend
        if measured is not None and claimed is not None and measured is not claimed:
            raise LedgerSchemaError(f"{where}: the run measured the {measured.value} frontend, not {claimed.value}")
        merged = self.base.overlay(embedded).overlay(self.explicit)
        return replace(
            merged,
            source="budget_bench",
            frontend=merged.frontend or Frontend.SELFHOST,
            build_mode=merged.build_mode or "debug",
        )

    def records(self, report: Mapping[str, Any], where: str = "budget_bench report") -> list[LedgerRecord]:
        if not isinstance(report, Mapping):
            raise LedgerSchemaError(f"{where}: expected a table")
        embedded = None
        run_reasons: list[str] = []
        if "schema" in report:
            scenarios, embedded, run_reasons = self.bench_report(report, where)
        else:
            if report.get("provenance") is not None:
                embedded = Provenance.from_mapping(report["provenance"], f"{where}.provenance")
            if "scenarios" in report:
                unknown = sorted(set(report) - {"provenance", "scenarios"})
                if unknown:
                    raise LedgerSchemaError(f"{where}: unknown field(s) {', '.join(unknown)}")
                scenarios = report["scenarios"]
                if not isinstance(scenarios, Mapping):
                    raise LedgerSchemaError(f"{where}.scenarios: expected a table")
            else:
                scenarios = {name: summary for name, summary in report.items() if name != "provenance"}
        declared = self.declared()
        unknown = sorted(set(scenarios) - set(declared))
        if unknown:
            raise LedgerSchemaError(f"{where}: scenario(s) {', '.join(unknown)} are not scenarios budget_bench reports")
        unknown_budgets = sorted(set(self.budgets) - set(declared))
        if unknown_budgets:
            raise LedgerSchemaError(f"budgets name unknown scenario(s) {', '.join(unknown_budgets)}")
        provenance = self.provenance(embedded, where)
        platform = self.platform or RUNNER_PLATFORMS.get(provenance.runner or "") or Platform.MACOS
        subjects = {
            name: Subject(
                kind=SubjectKind.SCENARIO,
                id=name,
                platform=platform,
                frontend=provenance.frontend,
                variant=self.variant,
                group="budget_bench",
            )
            for name in declared
        }
        return [
            self.record(subjects[name], scenarios.get(name), f"{where}.{name}", provenance, run_reasons)
            for name in declared
        ]

    def bench_report(self, report: Mapping[str, Any], where: str) -> tuple[Mapping[str, Any], Provenance, list[str]]:
        """A schema-2 report's scenarios, its translated provenance, and why none of it may pass."""

        if report.get("schema") != self.BENCH_SCHEMA:
            raise LedgerSchemaError(f"{where}.schema: {report.get('schema')!r} is not {self.BENCH_SCHEMA}")
        unknown = sorted(set(report) - self.BENCH_FIELDS)
        if unknown:
            raise LedgerSchemaError(f"{where}: unknown field(s) {', '.join(unknown)}")
        scenarios = report.get("scenarios")
        if not isinstance(scenarios, Mapping):
            raise LedgerSchemaError(f"{where}.scenarios: expected a table")
        tables = {}
        for name in ("configuration", "provenance"):
            table = report.get(name) or {}
            if not isinstance(table, Mapping):
                raise LedgerSchemaError(f"{where}.{name}: expected a table")
            tables[name] = table
        configuration, measured = tables["configuration"], tables["provenance"]
        btrcc = measured.get("btrcc") or {}
        environment = measured.get("environment") or {}
        if not isinstance(btrcc, Mapping) or not isinstance(environment, Mapping):
            raise LedgerSchemaError(f"{where}.provenance: btrcc and environment must be tables")
        mode = configuration.get("mode")
        translated = {
            "recorded_at": report.get("finished") or report.get("started"),
            "btrc_revision": measured.get("compiler_revision"),
            "frontend": configuration.get("frontend"),
            "build_mode": self.BUILD_MODES.get(mode, mode) if isinstance(mode, str) else mode,
            "target_triple": environment.get("BTRC_NATIVE_TARGET"),
            "compiler_digest": f"sha256:{btrcc['sha256']}" if btrcc.get("sha256") else None,
        }
        embedded = Provenance.from_mapping(
            {name: value for name, value in translated.items() if value is not None}, f"{where}.provenance"
        )
        reasons = []
        failure = report.get("failure")
        if failure is not None:
            if not isinstance(failure, str) or not failure.strip():
                raise LedgerSchemaError(f"{where}.failure: expected text or null")
            reasons.append(f"the run failed: {failure.strip().splitlines()[0]}")
        if report.get("dry_run"):
            reasons.append("a dry run")
        if configuration.get("stand_in"):
            reasons.append("a stand-in workspace, not BTRSmith")
        return scenarios, embedded, reasons

    def record(
        self,
        subject: Subject,
        summary: Mapping[str, Any] | None,
        where: str,
        provenance: Provenance,
        run_reasons: Sequence[str] = (),
    ) -> LedgerRecord:
        if summary is None:
            return LedgerRecord(subject=subject, provenance=provenance)
        if not isinstance(summary, Mapping):
            raise LedgerSchemaError(f"{where}: expected a table")
        failures, failure_reasons = self.failures(summary, where)
        measurement = self.measurement(subject.id, summary, failures, where)
        if measurement is None:
            evidence = Evidence(
                status=EvidenceStatus.UNAVAILABLE,
                observed="unmeasured",
                reason="the run reported no samples",
                artifact=self.artifact,
            )
            return LedgerRecord(subject=subject, evidence=evidence, provenance=provenance)
        shortfalls = [*LedgerRecord.acceptance_shortfalls(subject, measurement, provenance), *run_reasons]
        evidence = Evidence(
            status=EvidenceStatus.IMPLEMENTED_UNVERIFIED if shortfalls else EvidenceStatus.PASSED,
            observed="measured",
            reason="; ".join([*shortfalls, *failure_reasons]) or None,
            artifact=self.artifact,
        )
        return LedgerRecord(subject=subject, evidence=evidence, measurement=measurement, provenance=provenance)

    @staticmethod
    def failures(summary: Mapping[str, Any], where: str) -> tuple[int, list[str]]:
        """How many samples failed, and why, as the bench reported them."""

        count = summary.get("failures", 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise LedgerSchemaError(f"{where}.failures: expected a non-negative integer")
        reasons = summary.get("failure_reasons") or []
        if not isinstance(reasons, list) or not all(isinstance(reason, str) and reason.strip() for reason in reasons):
            raise LedgerSchemaError(f"{where}.failure_reasons: expected a list of text")
        if len(reasons) > count:
            raise LedgerSchemaError(f"{where}.failure_reasons: {len(reasons)} reasons for {count} failures")
        return count, [reason.strip().splitlines()[0] for reason in reasons]

    def measurement(self, name: str, summary: Mapping[str, Any], failures: int, where: str) -> Measurement | None:
        if name == "memory":
            return self._memory(summary, where)
        samples = summary.get("samples") or []
        if not samples and not failures:
            return None
        parts = summary.get("compile_native") or []
        if len(parts) != len(samples):
            raise LedgerSchemaError(f"{where}: {len(parts)} compile/native pairs for {len(samples)} samples")
        recomputed = SampleStatistics.of(samples)
        if recomputed is not None:
            for field, value in (("median", recomputed.median), ("p95", recomputed.p95), ("max", recomputed.maximum)):
                reported = summary.get(field)
                if reported is None or not math.isclose(reported, value, abs_tol=1e-3):
                    raise LedgerSchemaError(f"{where}.{field}: reported {reported}, its samples give {value:.3f}")
        split = [part for part in parts if part is not None]
        components = {}
        if len(split) == len(parts):
            components = {"compile": tuple(part[0] for part in split), "native": tuple(part[1] for part in split)}
        rebuilt = summary.get("rebuilt_units")
        if rebuilt is not None:
            if not isinstance(rebuilt, list) or len(rebuilt) != len(samples):
                raise LedgerSchemaError(f"{where}.rebuilt_units: expected one count per sample")
            if not all(isinstance(count, int) and not isinstance(count, bool) and count >= 0 for count in rebuilt):
                raise LedgerSchemaError(f"{where}.rebuilt_units: expected non-negative integers")
            components["rebuilt-units"] = tuple(rebuilt)
        return Measurement(
            metric="wall-time",
            unit="s",
            samples=tuple(samples),
            failures=failures,
            minimum_samples=self.INCREMENTAL_MINIMUM if name in self.incrementally_sampled() else self.COLD_MINIMUM,
            components=components,
            budgets=self.budgets.get(name, ()),
        )

    def _memory(self, summary: Mapping[str, Any], where: str) -> Measurement | None:
        """The compiler's peak, from a schema-2 scenario's facts or else an older report's notes."""

        facts = summary.get("facts") or {}
        if not isinstance(facts, Mapping):
            raise LedgerSchemaError(f"{where}.facts: expected a table")
        measured = {
            "peak": facts.get("compiler_peak_footprint_bytes") or facts.get("compiler_max_rss_bytes"),
            "aggregate-rss": facts.get("build_tree_rss_bytes"),
            "instructions-retired": facts.get("compiler_instructions_retired"),
        }
        for name, value in measured.items():
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise LedgerSchemaError(f"{where}.facts: {name} must be a non-negative integer")
        if measured["peak"] is None:
            notes = " ".join(summary.get("notes") or [])
            peak = self._PEAK.search(notes)
            if peak is None or int(peak.group(1)) < 0:
                return None
            aggregate = self._AGGREGATE.search(notes)
            instructions = self._INSTRUCTIONS.search(notes)
            measured = {
                "peak": int(peak.group(1)),
                "aggregate-rss": int(aggregate.group(1)) if aggregate else None,
                "instructions-retired": int(instructions.group(1).replace(",", "")) if instructions else None,
            }
        components = {name: (value,) for name, value in measured.items() if name != "peak" and value is not None}
        return Measurement(
            metric="peak-footprint",
            unit="bytes",
            samples=(measured["peak"],),
            minimum_samples=1,
            components=components,
            budgets=self.budgets.get("memory", ()),
        )


class JUnitAdapter:
    """One test record per JUnit test case, keyed by its pytest node id."""

    def __init__(
        self, provenance: Provenance, *, platform: Platform | None, variant: str | None = None, repo: Path = REPO
    ) -> None:
        self.provenance = replace(provenance, source="junit")
        self.platform = platform
        self.variant = variant
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
                    variant=self.variant,
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
