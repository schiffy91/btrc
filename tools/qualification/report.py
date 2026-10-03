"""Roll a ledger up by slot and render the support/coverage report.

Every count is taken against a denominator -- the distinct slots of one kind
on one platform through one frontend and artifact variant -- so a slot
without evidence is shown as *unrecorded* rather than vanishing. Given the
frozen inventory denominators, the report also counts every declared slot
the ledger has no record for as *missing*, per release, and every slot outside
the union of its kind's releases as *undeclared*, and fails on either; the
coverage table counts each kind against that union. A slot classified as
``retired`` is counted in its own column of every table, never as unrecorded,
unclassified or missing; a ledger that retires no slot gets no such column,
so its report reads as it did before the disposition existed. The evidence table
carries the four outcome classes; the parity table carries the four
classification classes; the implementation table keeps the source state
(missing, source-only, partial, custom, implemented) apart from them;
measurements show raw sample counts with median, nearest-rank p95/p99/p99.9,
maximum, failures, component medians and the host that measured them;
skipped and unavailable slots are listed with the runners that cover them,
or as uncovered.

An inventory slot that names its regression tests takes its current evidence
from them: the latest result of each test on the slot's platform family,
preferring a run through the slot's own frontend. Hand-entered evidence that
says otherwise is counted as *disagrees*.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tools.qualification.denominators import DenominatorManifest
from tools.qualification.schema import (
    INVENTORY_KINDS,
    REGRESSION_KINDS,
    Classification,
    Evidence,
    EvidenceStatus,
    Implementation,
    LedgerRecord,
    Measurement,
    Parity,
    Platform,
    Provenance,
    Subject,
    SubjectKind,
)
from tools.qualification.statistics import SampleStatistics

_FAILED = frozenset({"failed", "error"})
type SlotKey = tuple[str, str, str, str, str]
type GroupKey = tuple[str, str, str, str]


@dataclass
class SlotState:
    """What the ledger says about one slot after every record is folded in."""

    subject: Subject
    classification: Classification | None = None
    evidence: Evidence | None = None
    measurement: Measurement | None = None
    provenance: Provenance | None = None
    order: int = -1
    derived: Evidence | None = None

    @property
    def current(self) -> Evidence | None:
        """The evidence the report counts: derived from the regression tests when they ran."""

        return self.derived or self.evidence

    @property
    def disagrees(self) -> bool:
        return self.derived is not None and self.evidence is not None and self.derived.status != self.evidence.status

    @property
    def retired(self) -> bool:
        """A reviewed decision removed this slot's declaration: it is listed apart, never qualified."""

        return self.classification is not None and self.classification.implementation is Implementation.RETIRED

    @property
    def failed(self) -> bool:
        if self.current is not None and self.current.observed in _FAILED:
            return True
        return self.measurement is not None and self.measurement.failures > 0


class LedgerRollup:
    """Fold records into slot states: the last classification and the last evidence win independently."""

    def __init__(self, records: Iterable[LedgerRecord]) -> None:
        self.records = list(records)
        self.slots: dict[SlotKey, SlotState] = {}
        for order, record in enumerate(self.records):
            state = self.slots.setdefault(record.subject.key, SlotState(record.subject))
            if record.subject.group or record.subject.title:
                state.subject = record.subject
            if record.classification is not None:
                state.classification = record.classification
            if record.evidence is not None:
                state.evidence = record.evidence
                state.measurement = record.measurement
                state.provenance = record.provenance or state.provenance
                state.order = order
            elif record.measurement is not None:
                state.measurement = record.measurement
                state.provenance = record.provenance or state.provenance
        self._derive()

    @staticmethod
    def family(platform: Platform | None) -> Platform | None:
        """The platform family an inventory slot names: iPadOS runs count for iOS/iPadOS."""

        return Platform.IOS if platform is Platform.IPADOS else platform

    def _derive(self) -> None:
        tests: dict[tuple[str, Platform | None], list[SlotState]] = defaultdict(list)
        for state in self.slots.values():
            if state.subject.kind is SubjectKind.TEST and state.evidence is not None:
                tests[(state.subject.id, self.family(state.subject.platform))].append(state)
        for state in self.slots.values():
            classification = state.classification
            if state.subject.kind in REGRESSION_KINDS and classification and classification.regression:
                state.derived = self.derived(state.subject, classification.regression, tests)

    @staticmethod
    def derived(
        subject: Subject, regression: tuple[str, ...], tests: dict[tuple[str, Platform | None], list[SlotState]]
    ) -> Evidence | None:
        """Combine the latest result of each regression test; None when none of them ran here."""

        latest: dict[str, Evidence | None] = {}
        for nodeid in regression:
            # A slice row takes only its own artifact's runs: simulator and device never merge.
            runs = [
                run
                for run in tests.get((nodeid, subject.platform), ())
                if run.subject.frontend in (None, subject.frontend) and subject.variant in (None, run.subject.variant)
            ]
            best = max(runs, key=lambda run: (run.subject.frontend is not None, run.order), default=None)
            latest[nodeid] = best.evidence if best is not None else None
        found = {nodeid: evidence for nodeid, evidence in latest.items() if evidence is not None}
        if not found:
            return None
        unrun = [nodeid for nodeid, evidence in latest.items() if evidence is None]
        unavailable = {n: e for n, e in found.items() if e.status is EvidenceStatus.UNAVAILABLE}
        failing = {
            n: e for n, e in found.items() if e.status not in {EvidenceStatus.PASSED, EvidenceStatus.UNAVAILABLE}
        }
        reasons = [f"{nodeid}: {evidence.observed or evidence.status.value}" for nodeid, evidence in failing.items()]
        reasons += [f"{nodeid}: no result" for nodeid in unrun]
        reasons += [f"{nodeid}: {evidence.observed or 'unavailable'}" for nodeid, evidence in unavailable.items()]
        artifact = next((evidence.artifact for evidence in found.values() if evidence.artifact), None)
        if failing or unrun:
            observed = next(iter(failing.values())).observed if failing else "incomplete"
            return Evidence(EvidenceStatus.IMPLEMENTED_UNVERIFIED, observed, "; ".join(reasons), artifact)
        if unavailable:
            coverage = [evidence.covered_by for evidence in unavailable.values()]
            covered = None
            if all(runners is not None for runners in coverage):
                covered = tuple(sorted(set.intersection(*(set(runners) for runners in coverage))))
            return Evidence(EvidenceStatus.UNAVAILABLE, "skipped", "; ".join(reasons), artifact, covered)
        return Evidence(EvidenceStatus.PASSED, "passed", None, artifact)

    def denominators(self) -> dict[GroupKey, list[SlotState]]:
        groups: dict[GroupKey, list[SlotState]] = defaultdict(list)
        for state in self.slots.values():
            subject = state.subject
            key = (subject.kind.value, subject.platform or "", subject.frontend or "", subject.variant or "")
            groups[key].append(state)
        return dict(sorted(groups.items()))


class QualificationReport:
    """The aggregate tables, as JSON for tools or Markdown for people."""

    STATUSES = (
        EvidenceStatus.PASSED,
        EvidenceStatus.IMPLEMENTED_UNVERIFIED,
        EvidenceStatus.SOURCE_ONLY,
        EvidenceStatus.UNAVAILABLE,
    )
    PARITIES = (Parity.EQUIVALENT, Parity.ADAPTED, Parity.OS_RESTRICTED, Parity.MISSING)
    IMPLEMENTATIONS = tuple(
        implementation for implementation in Implementation if implementation is not Implementation.RETIRED
    )
    GROUP = ("kind", "platform", "frontend", "variant")

    def __init__(self, records: Iterable[LedgerRecord], denominators: DenominatorManifest | None = None) -> None:
        self.rollup = LedgerRollup(records)
        self.denominators = denominators
        # Tables gain a retired column only when the ledger retires a slot, so a ledger without
        # retirements reports exactly as before the disposition existed.
        self.retires = any(state.retired for state in self.rollup.slots.values())

    def _retired(self, states: Iterable[SlotState]) -> dict[str, int]:
        """The retired column of a row, present only when the ledger retires a slot."""

        return {"retired": sum(1 for state in states if state.retired)} if self.retires else {}

    def _columns(self, *columns: str) -> tuple[str, ...]:
        return (*columns, "retired") if self.retires else columns

    @staticmethod
    def _group(key: GroupKey) -> dict[str, Any]:
        return {name: value or None for name, value in zip(QualificationReport.GROUP, key)}

    def evidence_rows(self) -> list[dict[str, Any]]:
        rows = []
        for key, states in self.rollup.denominators().items():
            counts = Counter(state.current.status for state in states if state.current is not None)
            rows.append(
                {
                    **self._group(key),
                    "slots": len(states),
                    **{status.value: counts.get(status, 0) for status in self.STATUSES},
                    "unrecorded": sum(1 for state in states if state.current is None and not state.retired),
                    **self._retired(states),
                    "failed": sum(1 for state in states if state.failed),
                }
            )
        return rows

    def parity_rows(self) -> list[dict[str, Any]]:
        rows = []
        for key, states in self.rollup.denominators().items():
            classified = [state.classification for state in states if state.classification is not None]
            if not any(classification.parity for classification in classified):
                continue
            counts = Counter(classification.parity for classification in classified if classification.parity)
            retired = sum(1 for state in states if state.retired)
            rows.append(
                {
                    **self._group(key),
                    "slots": len(states),
                    **{parity.value: counts.get(parity, 0) for parity in self.PARITIES},
                    "unclassified": len(states) - sum(counts.values()) - retired,
                    **self._retired(states),
                }
            )
        return rows

    def implementation_rows(self) -> list[dict[str, Any]]:
        """UI0's source inventory: implementation state, never folded into qualification.

        ``retired`` is its own column, so a retired slot is never unclassified.
        """

        rows = []
        for key, states in self.rollup.denominators().items():
            states_with = [s.classification.implementation for s in states if s.classification is not None]
            counts = Counter(implementation for implementation in states_with if implementation is not None)
            if not counts:
                continue
            rows.append(
                {
                    **self._group(key),
                    "slots": len(states),
                    **{implementation.value: counts.get(implementation, 0) for implementation in self.IMPLEMENTATIONS},
                    "unclassified": len(states) - sum(counts.values()),
                    **self._retired(states),
                }
            )
        return rows

    def completeness_rows(self) -> list[dict[str, Any]]:
        """P0: every inventory row needs parity, an owner, a regression and a current evidence status.

        A retired row needs none of them: it is counted apart.
        """

        rows = []
        for key, slots in self.rollup.denominators().items():
            if SubjectKind(key[0]) not in INVENTORY_KINDS:
                continue
            states = [state for state in slots if not state.retired]
            rows.append(
                {
                    **self._group(key),
                    "rows": len(slots),
                    "without_parity": sum(1 for s in states if not (s.classification and s.classification.parity)),
                    "without_owner": sum(1 for s in states if not (s.classification and s.classification.owner)),
                    "without_regression": sum(
                        1 for s in states if not (s.classification and s.classification.regression)
                    ),
                    "without_status": sum(1 for s in states if s.current is None),
                    "disagrees": sum(1 for s in states if s.disagrees),
                    **self._retired(slots),
                }
            )
        return rows

    def measurement_rows(self) -> list[dict[str, Any]]:
        rows = []
        for state in sorted(self.rollup.slots.values(), key=lambda state: state.subject.key):
            measurement = state.measurement
            if measurement is None:
                continue
            summary = measurement.statistics
            components = {}
            for name, values in measurement.components.items():
                component = SampleStatistics.of(values)
                components[name] = component.median if component else None
            rows.append(
                {
                    "kind": state.subject.kind.value,
                    "id": state.subject.id,
                    "platform": state.subject.platform.value if state.subject.platform else None,
                    "frontend": state.subject.frontend.value if state.subject.frontend else None,
                    "variant": state.subject.variant,
                    "metric": measurement.metric,
                    "unit": measurement.unit,
                    "samples": len(measurement.samples),
                    "median": summary.median if summary else None,
                    "p95": summary.p95 if summary else None,
                    "p99": summary.p99 if summary else None,
                    "p99.9": summary.p999 if summary else None,
                    "max": summary.maximum if summary else None,
                    "failures": measurement.failures,
                    "status": state.current.status.value if state.current else None,
                    "shortfalls": LedgerRecord.acceptance_shortfalls(state.subject, measurement, state.provenance),
                    "components": components,
                    "provenance": state.provenance.to_mapping() if state.provenance else None,
                }
            )
        return rows

    def unavailable_rows(self) -> list[dict[str, Any]]:
        """Skipped and unavailable slots grouped by reason, with the runners that cover them."""

        groups: Counter[tuple[str, str, str, str]] = Counter()
        for state in self.rollup.slots.values():
            evidence = state.current
            if evidence is None or evidence.status is not EvidenceStatus.UNAVAILABLE:
                continue
            if evidence.covered_by is None:
                covered = "unclassified"
            else:
                covered = ", ".join(evidence.covered_by) or "uncovered"
            reason = (evidence.reason or "no reason recorded").splitlines()[0]
            groups[(state.subject.kind.value, state.subject.platform or "", covered, reason)] += 1
        return [
            {"kind": kind, "platform": platform or None, "covered_by": covered, "reason": reason, "slots": count}
            for (kind, platform, covered, reason), count in sorted(groups.items())
        ]

    def provenance_rows(self) -> list[dict[str, Any]]:
        seen: dict[tuple, dict[str, Any]] = {}
        for record in self.rollup.records:
            if record.provenance is None:
                continue
            mapping = record.provenance.to_mapping()
            seen.setdefault(tuple(sorted(mapping.items())), mapping)
        return list(seen.values())

    def _recorded(self, kind: SubjectKind) -> set[SlotKey]:
        return {key for key in self.rollup.slots if key[0] == kind.value}

    def denominator_rows(self) -> list[dict[str, Any]]:
        """Each frozen release against the ledger: declared, present, missing, retired and undeclared slots.

        Missing slots are counted per release. Undeclared slots are counted
        against the union of every release of the kind, so a slot another
        release declares is never undeclared; every release of a kind shows
        the same undeclared count.
        """

        if self.denominators is None:
            return []
        rows = []
        for denominator in self.denominators.denominators:
            declared = denominator.slot_keys()
            recorded = self._recorded(denominator.kind)
            present = recorded & declared
            rows.append(
                {
                    "kind": denominator.kind.value,
                    "release": denominator.release,
                    "source": denominator.source,
                    "slots": denominator.frozen_slots,
                    "present": len(present),
                    "missing_slots": max(0, denominator.frozen_slots - len(present)),
                    **self._retired(self.rollup.slots[key] for key in present),
                    "undeclared": len(recorded - self.denominators.slot_keys(denominator.kind)),
                    "drift": denominator.drift(),
                    "missing_examples": [" ".join(filter(None, key[1:])) for key in sorted(declared - recorded)[:5]],
                }
            )
        return rows

    def coverage_rows(self) -> list[dict[str, Any]]:
        """Each inventory kind against every release in force for it: the count a full-coverage gate reads.

        ``slots`` is the union of the releases' declared slots, so a slot two
        releases share counts once. ``retired`` slots are present but resolve
        by their decision, not by a classification.
        """

        if self.denominators is None:
            return []
        rows = []
        for kind in self.denominators.kinds():
            declared = self.denominators.slot_keys(kind)
            recorded = self._recorded(kind)
            present = recorded & declared
            rows.append(
                {
                    "kind": kind.value,
                    "releases": [denominator.release for denominator in self.denominators.releases(kind)],
                    "slots": len(declared),
                    "present": len(present),
                    "missing_slots": len(declared - recorded),
                    **self._retired(self.rollup.slots[key] for key in present),
                    "undeclared": len(recorded - declared),
                }
            )
        return rows

    def problems(self) -> list[str]:
        """Why this report cannot stand as complete; empty when it can."""

        problems = []
        rows = self.denominator_rows()
        releases = Counter(row["kind"] for row in rows)
        for row in rows:
            problems += row["drift"]
            if row["missing_slots"]:
                examples = ", ".join(row["missing_examples"])
                # A kind with several releases names the release its missing slots belong to.
                release = f" of release {row['release']}" if releases[row["kind"]] > 1 else ""
                problems.append(
                    f"{row['kind']}: {row['missing_slots']} of {row['slots']} declared slots{release} "
                    f"have no record (e.g. {examples})"
                )
        for row in self.coverage_rows():
            if row["undeclared"]:
                releases = ", ".join(row["releases"])
                noun = "releases" if len(row["releases"]) > 1 else "release"
                problems.append(f"{row['kind']}: {row['undeclared']} slots are outside {noun} {releases}")
        retired = Counter(
            state.subject.kind.value for state in self.rollup.slots.values() if state.retired and state.current
        )
        problems += [f"{kind}: {count} retired slots carry evidence" for kind, count in sorted(retired.items())]
        return problems

    def to_json(self) -> dict[str, Any]:
        return {
            "records": len(self.rollup.records),
            "slots": len(self.rollup.slots),
            "evidence": self.evidence_rows(),
            "parity": self.parity_rows(),
            "implementation": self.implementation_rows(),
            "completeness": self.completeness_rows(),
            "denominators": self.denominator_rows(),
            "coverage": self.coverage_rows(),
            "measurements": self.measurement_rows(),
            "unavailable": self.unavailable_rows(),
            "provenance": self.provenance_rows(),
            "problems": self.problems(),
        }

    def render_json(self) -> str:
        return json.dumps(self.to_json(), indent=2) + "\n"

    def render_markdown(self) -> str:
        lines = [
            "# Qualification report",
            "",
            f"{len(self.rollup.records)} records over {len(self.rollup.slots)} slots. Every count is taken "
            "against its denominator: the declared slots of one kind on one platform through one frontend "
            "and artifact variant. A slot without evidence is unrecorded, never dropped.",
            "",
            "## Evidence",
            "",
        ]
        columns = self._columns("slots", *(status.value for status in self.STATUSES), "unrecorded", "failed")
        lines += self._table((*self.GROUP, *columns), self.evidence_rows())
        if denominators := self.denominator_rows():
            rows = [{**row, "drift": "; ".join(row["drift"]) or "-"} for row in denominators]
            names = self._columns(
                "kind", "release", "source", "slots", "present", "missing_slots", "undeclared", "drift"
            )
            lines += ["", "## Frozen denominators", "", *self._table(names, rows)]
            rows = [{**row, "releases": ", ".join(row["releases"])} for row in self.coverage_rows()]
            names = self._columns("kind", "releases", "slots", "present", "missing_slots", "undeclared")
            lines += ["", "## Coverage of every release in force", "", *self._table(names, rows)]
        if parity := self.parity_rows():
            columns = self._columns("slots", *(parity_class.value for parity_class in self.PARITIES), "unclassified")
            lines += ["", "## Parity classification", "", *self._table((*self.GROUP, *columns), parity)]
        if implementation := self.implementation_rows():
            columns = self._columns("slots", *(state.value for state in self.IMPLEMENTATIONS), "unclassified")
            lines += ["", "## Implementation state", "", *self._table((*self.GROUP, *columns), implementation)]
        if completeness := self.completeness_rows():
            columns = ("rows", "without_parity", "without_owner", "without_regression", "without_status", "disagrees")
            columns = self._columns(*columns)
            lines += ["", "## Inventory completeness", "", *self._table((*self.GROUP, *columns), completeness)]
        provenance = self.provenance_rows()
        hosts = {tuple(sorted(mapping.items())): f"P{index}" for index, mapping in enumerate(provenance, start=1)}
        if measurements := self.measurement_rows():
            rows = [
                {
                    **row,
                    "shortfalls": "; ".join(row["shortfalls"]) or "-",
                    "components": "; ".join(
                        f"{name} {self._number(value)}" for name, value in row["components"].items()
                    )
                    or "-",
                    "host": hosts.get(tuple(sorted((row["provenance"] or {}).items()))),
                    **{name: self._number(row[name]) for name in ("median", "p95", "p99", "p99.9", "max")},
                }
                for row in measurements
            ]
            names = ("id", "platform", "frontend", "variant", "metric", "unit", "samples", "median", "p95", "p99")
            names += ("p99.9", "max", "failures", "status", "shortfalls", "components", "host")
            lines += ["", "## Measurements", "", *self._table(names, rows)]
        if unavailable := self.unavailable_rows():
            lines += [
                "",
                "## Unavailable slots and their coverage",
                "",
                *self._table(("kind", "platform", "slots", "covered_by", "reason"), unavailable),
            ]
        if provenance:
            rows = [{"host": f"P{index}", **mapping} for index, mapping in enumerate(provenance, start=1)]
            lines += ["", "## Provenance", "", *self._table(("host", *Provenance.FIELDS), rows)]
        if problems := self.problems():
            lines += ["", "## Problems", "", *(f"- {problem}" for problem in problems)]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _number(value: float | None) -> str:
        if value is None:
            return "-"
        if isinstance(value, float) and value.is_integer() and abs(value) >= 1e6:
            return str(int(value))
        return f"{value:.3f}" if isinstance(value, float) else str(value)

    @staticmethod
    def _table(columns: tuple[str, ...], rows: list[dict[str, Any]]) -> list[str]:
        def cell(value: object) -> str:
            text = "-" if value is None or value == "" else str(value)
            return text.replace("|", "\\|")

        header = "| " + " | ".join(column.replace("_", " ") for column in columns) + " |"
        rule = "|" + "|".join("---:" if all(isinstance(row.get(c), int) for row in rows) else "---" for c in columns)
        return [header, rule + "|", *("| " + " | ".join(cell(row.get(c)) for c in columns) + " |" for row in rows)]
