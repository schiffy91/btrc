"""One ledger bundle from every piece of evidence a CI run left.

``python3 -m tools.qualification bundle`` reads a directory of downloaded
workflow artifacts, one subdirectory per artifact as ``actions/download-
artifact`` writes them, and writes::

    <output>/bundle.json    what went in, what the tier plan expected, what is awaiting
    <output>/ledger.jsonl   every record the adapters derived (btrc.qualification.ledger/1)
    <output>/raw/<artifact>/<file>   each input, byte for byte

The artifact name says what an input is and which job made it:

``skip-report-<workflow>-<job>[-<row>]``   pytest skip reports (``*.json``)
``junit-<workflow>-<job>[-<row>]``         pytest ``--junitxml`` output (``*.xml``)
``boundary-report-<workflow>-<job>-<row>`` ``boundary-check --report`` (``*.json``)
``bench-results``                          ``tools.bench`` ``results.json``

Any other artifact (release archives) is listed as ignored. The tier manifest
(`tools.qualification.tiers`) names every report the tier must leave; a
missing one, or an input no adapter accepts, is a problem and fails the
command after the bundle is written, so a red bundle job still uploads what
it found. Hardware-tier runners are recorded as awaiting, with the number of
hosted skips whose covered_by names them.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import shutil
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.qualification.adapters import RUNNER_PLATFORMS, BoundaryReportAdapter, JUnitAdapter, SkipReportAdapter
from tools.qualification.schema import (
    Evidence,
    EvidenceStatus,
    LedgerDocument,
    LedgerRecord,
    LedgerSchemaError,
    Measurement,
    Platform,
    Provenance,
    Subject,
    SubjectKind,
)
from tools.qualification.skips import SkipLedgerError, SkipReport
from tools.qualification.tiers import TierManifest

BUNDLE_SCHEMA = "btrc.ledger-bundle/1"
# The runner each tiered workflow's jobs classify their skips as.
WORKFLOW_RUNNERS = {"ci": "linux-devcontainer", "macos": "macos-hosted", "windows": "windows"}
BENCH_ARTIFACT = "bench-results"


@dataclass(frozen=True)
class BundleInput:
    """One evidence file inside one downloaded artifact."""

    artifact: str
    path: Path
    kind: str

    @property
    def workflow(self) -> str | None:
        for kind in ("skip-report", "junit", "boundary-report"):
            if self.artifact.startswith(f"{kind}-"):
                return self.artifact.removeprefix(f"{kind}-").split("-", 1)[0]
        return "ci" if self.kind == "bench" else None


@dataclass
class BundleOutcome:
    output: Path
    records: int
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems and self.records > 0


class ToolsBenchAdapter:
    """One scenario record per ``tools.bench`` metric of a hosted ``bench-check`` run.

    These are regression guards against the tracked baseline, measured on a
    pool of unlike hosted machines, not P6 budget measurements: each record
    keeps its sample and says why it is not acceptance evidence.
    """

    UNITS = {"ms": "ms", "bytes": "bytes", "lines": "lines", "parity": "parity", "count": "count", "peak": "bytes"}
    PLATFORMS = {"darwin": Platform.MACOS, "linux": Platform.LINUX, "windows": Platform.WINDOWS}

    def __init__(self, provenance: Provenance, runner: str) -> None:
        self.provenance = provenance
        self.runner = runner

    @classmethod
    def unit(cls, name: str) -> str:
        from tools.bench.baseline import Baseline

        try:
            kind = Baseline.metric_kind(name)
        except ValueError:
            kind = "info"
        if kind == "info":
            tail = name.rsplit(".", 1)[-1]
            kind = "ms" if tail.endswith("_ms") else tail.rsplit("_", 1)[-1]
        return cls.UNITS.get(kind, "value")

    def records(self, document: Mapping[str, Any], artifact: str) -> list[LedgerRecord]:
        meta, metrics = document.get("meta"), document.get("metrics")
        if not isinstance(meta, Mapping) or not isinstance(metrics, Mapping):
            raise LedgerSchemaError(f"{artifact}: not a tools.bench results file (meta and metrics)")
        platform = self.PLATFORMS.get(str(meta.get("platform", "")).split("-", 1)[0])
        provenance = Provenance.from_mapping(
            {
                **self.provenance.to_mapping(),
                "source": "tools.bench",
                "runner": self.runner,
                **{
                    name: str(meta[key])
                    for name, key in (("btrc_revision", "revision"), ("recorded_at", "recorded_at"), ("c_compiler", "cc"))
                    if meta.get(key)
                },
            },
            f"{artifact}.meta",
        )
        records = []
        for name, value in sorted(metrics.items()):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise LedgerSchemaError(f"{artifact}: metric {name} is not a number")
            subject = Subject(kind=SubjectKind.SCENARIO, id=name, platform=platform, group="tools.bench")
            measurement = Measurement(metric=name.rsplit(".", 1)[-1], unit=self.unit(name), samples=(float(value),))
            shortfalls = LedgerRecord.acceptance_shortfalls(subject, measurement, provenance)
            reason = "; ".join(["a hosted bench-check regression guard, not a P6 budget measurement", *shortfalls])
            evidence = Evidence(EvidenceStatus.IMPLEMENTED_UNVERIFIED, "measured", reason, artifact)
            records.append(LedgerRecord(subject=subject, evidence=evidence, measurement=measurement, provenance=provenance))
        return records


class LedgerBundle:
    """Turn one run's artifacts into one bundle, checked against its tier's plan."""

    KINDS = (("skip-report-", "skip-report", "*.json"), ("junit-", "junit", "*.xml"), ("boundary-report-", "boundary-report", "*.json"))

    def __init__(
        self,
        artifacts: Path,
        manifest: TierManifest,
        tier: str,
        revision: str,
        run: str | None = None,
    ) -> None:
        self.artifacts = artifacts
        self.manifest = manifest
        self.tier = tier
        self.revision = revision
        self.run = run

    def inputs(self) -> tuple[list[BundleInput], list[str]]:
        """Every evidence file under the artifacts directory, and the artifacts that hold none."""

        found: list[BundleInput] = []
        ignored: list[str] = []
        directories = sorted(path for path in self.artifacts.iterdir() if path.is_dir()) if self.artifacts.is_dir() else []
        for directory in directories:
            name = directory.name
            if name == BENCH_ARTIFACT:
                found += [BundleInput(name, path, "bench") for path in sorted(directory.rglob("*.json"))]
                continue
            kind = next(((kind, glob) for prefix, kind, glob in self.KINDS if name.startswith(prefix)), None)
            if kind is None:
                ignored.append(name)
                continue
            found += [BundleInput(name, path, kind[0]) for path in sorted(directory.rglob(kind[1]))]
        return found, ignored

    def provenance(self, item: BundleInput) -> Provenance:
        return Provenance(
            btrc_revision=self.revision,
            runner=WORKFLOW_RUNNERS.get(item.workflow or ""),
            source=None,
        )

    def records(self, item: BundleInput, artifact: str) -> list[LedgerRecord]:
        provenance = self.provenance(item)
        platform = RUNNER_PLATFORMS.get(provenance.runner or "")
        if item.kind == "skip-report":
            return SkipReportAdapter(provenance).records(SkipReport.load(item.path), artifact)
        if item.kind == "junit":
            return JUnitAdapter(provenance, platform=platform, repo=self.manifest.root).records(item.path, artifact)
        document = json.loads(item.path.read_text(encoding="utf-8"))
        if item.kind == "boundary-report":
            return BoundaryReportAdapter(provenance, platform=platform).records(document, artifact)
        return ToolsBenchAdapter(provenance, provenance.runner or "linux-devcontainer").records(document, artifact)

    def build(self, output: Path) -> BundleOutcome:
        if output.exists() and any(output.iterdir()):
            raise LedgerSchemaError(f"{output} is not empty; a bundle is written once")
        raw = output / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        expected = self.manifest.expected_reports(self.tier)
        owner = {name: job for job, names in expected.items() for name in names}
        inputs, ignored = self.inputs()
        problems: list[str] = []
        records: list[LedgerRecord] = []
        listed = []
        for item in inputs:
            relative = item.path.relative_to(self.artifacts / item.artifact)
            kept = raw / item.artifact / relative
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item.path, kept)
            artifact = kept.relative_to(output).as_posix()
            try:
                derived = self.records(item, artifact)
            except (LedgerSchemaError, SkipLedgerError, json.JSONDecodeError, KeyError, TypeError) as error:
                problems.append(f"{artifact}: {error}")
                derived = []
            records += derived
            listed.append(
                {
                    "artifact": item.artifact,
                    "file": artifact,
                    "kind": item.kind,
                    "job": owner.get(item.artifact),
                    "sha256": hashlib.sha256(item.path.read_bytes()).hexdigest(),
                    "records": len(derived),
                }
            )
        present = {item.artifact for item in inputs}
        missing = sorted(name for name in owner if name not in present)
        problems += [f"missing {name} (from {owner[name]})" for name in missing]
        if not records:
            problems.append("no evidence records: the artifacts directory held no report")
        awaiting = self.awaiting(records)
        (output / "ledger.jsonl").write_text(LedgerDocument.dumps_jsonl(records), encoding="utf-8")
        document = {
            "schema": BUNDLE_SCHEMA,
            "revision": self.revision,
            "tier": self.tier,
            "run": self.run,
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "ledger": "ledger.jsonl",
            "counts": {
                "records": len(records),
                "inputs": len(inputs),
                **{f"{kind}s": count for kind, count in sorted(Counter(item.kind for item in inputs).items())},
            },
            "expected": expected,
            "missing": missing,
            "extra": sorted(present - set(owner)),
            "ignored": ignored,
            "inputs": listed,
            "awaiting": awaiting,
            "problems": problems,
        }
        (output / "bundle.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return BundleOutcome(output, len(records), problems)

    def awaiting(self, records: list[LedgerRecord]) -> list[dict[str, Any]]:
        """Each hardware-tier runner, with the hosted skips whose coverage it owes."""

        owed: Counter[str] = Counter()
        for record in records:
            evidence = record.evidence
            if evidence is not None and evidence.covered_by:
                owed.update(set(evidence.covered_by))
        return [
            {
                "id": runner.id,
                "runner": runner.runner,
                "description": runner.description,
                "status": "awaiting",
                "owed_skips": owed[runner.runner],
            }
            for runner in self.manifest.hardware
        ]
