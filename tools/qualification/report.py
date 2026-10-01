"""Roll a ledger up by slot and render the support/coverage report.

Every count is taken against a denominator -- the distinct slots of one kind
on one platform through one frontend -- so a slot without evidence is shown
as *unrecorded* rather than vanishing. The evidence table carries the four
outcome classes; the parity table carries the four classification classes;
measurements show raw sample counts with median, nearest-rank p95, maximum
and failures; skipped and unavailable slots are listed with the runners that
cover them, or as uncovered.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from tools.qualification.schema import (
    Classification,
    Evidence,
    EvidenceStatus,
    LedgerRecord,
    Measurement,
    Parity,
    Provenance,
    Subject,
    SubjectKind,
)

_INVENTORY_KINDS = frozenset(
    {
        SubjectKind.OPERATION,
        SubjectKind.JOURNEY,
        SubjectKind.FAMILY_CELL,
        SubjectKind.UI_OPERATION,
        SubjectKind.UI_CASE,
    }
)
_FAILED = frozenset({"failed", "error"})


@dataclass
class SlotState:
    """What the ledger says about one slot after every record is folded in."""

    subject: Subject
    classification: Classification | None = None
    evidence: Evidence | None = None
    measurement: Measurement | None = None
    provenance: Provenance | None = None

    @property
    def failed(self) -> bool:
        if self.evidence is not None and self.evidence.observed in _FAILED:
            return True
        return self.measurement is not None and self.measurement.failures > 0


class LedgerRollup:
    """Fold records into slot states: the last classification and the last evidence win independently."""

    def __init__(self, records: Iterable[LedgerRecord]) -> None:
        self.records = list(records)
        self.slots: dict[tuple[str, str, str, str], SlotState] = {}
        for record in self.records:
            state = self.slots.setdefault(record.subject.key, SlotState(record.subject))
            if record.subject.group or record.subject.title:
                state.subject = record.subject
            if record.classification is not None:
                state.classification = record.classification
            if record.evidence is not None:
                state.evidence = record.evidence
                state.measurement = record.measurement
                state.provenance = record.provenance or state.provenance
            elif record.measurement is not None:
                state.measurement = record.measurement

    def denominators(self) -> dict[tuple[str, str, str], list[SlotState]]:
        groups: dict[tuple[str, str, str], list[SlotState]] = defaultdict(list)
        for state in self.slots.values():
            subject = state.subject
            groups[(subject.kind.value, subject.platform or "", subject.frontend or "")].append(state)
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

    def __init__(self, records: Iterable[LedgerRecord]) -> None:
        self.rollup = LedgerRollup(records)

    def evidence_rows(self) -> list[dict[str, Any]]:
        rows = []
        for (kind, platform, frontend), states in self.rollup.denominators().items():
            counts = Counter(state.evidence.status for state in states if state.evidence is not None)
            rows.append(
                {
                    "kind": kind,
                    "platform": platform or None,
                    "frontend": frontend or None,
                    "slots": len(states),
                    **{status.value: counts.get(status, 0) for status in self.STATUSES},
                    "unrecorded": sum(1 for state in states if state.evidence is None),
                    "failed": sum(1 for state in states if state.failed),
                }
            )
        return rows

    def parity_rows(self) -> list[dict[str, Any]]:
        rows = []
        for (kind, platform, frontend), states in self.rollup.denominators().items():
            classified = [state.classification for state in states if state.classification is not None]
            if not classified:
                continue
            counts = Counter(classification.parity for classification in classified if classification.parity)
            rows.append(
                {
                    "kind": kind,
                    "platform": platform or None,
                    "frontend": frontend or None,
                    "slots": len(states),
                    **{parity.value: counts.get(parity, 0) for parity in self.PARITIES},
                    "unclassified": len(states) - sum(counts.values()),
                }
            )
        return rows

    def completeness_rows(self) -> list[dict[str, Any]]:
        """P0: every inventory row needs an owner, a regression and a current evidence status."""

        rows = []
        for (kind, platform, frontend), states in self.rollup.denominators().items():
            if SubjectKind(kind) not in _INVENTORY_KINDS:
                continue
            rows.append(
                {
                    "kind": kind,
                    "platform": platform or None,
                    "frontend": frontend or None,
                    "rows": len(states),
                    "without_owner": sum(1 for s in states if not (s.classification and s.classification.owner)),
                    "without_regression": sum(
                        1 for s in states if not (s.classification and s.classification.regression)
                    ),
                    "without_status": sum(1 for s in states if s.evidence is None),
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
            rows.append(
                {
                    "kind": state.subject.kind.value,
                    "id": state.subject.id,
                    "platform": state.subject.platform.value if state.subject.platform else None,
                    "frontend": state.subject.frontend.value if state.subject.frontend else None,
                    "metric": measurement.metric,
                    "unit": measurement.unit,
                    "samples": len(measurement.samples),
                    "median": summary.median if summary else None,
                    "p95": summary.p95 if summary else None,
                    "max": summary.maximum if summary else None,
                    "failures": measurement.failures,
                    "status": state.evidence.status.value if state.evidence else None,
                    "shortfalls": measurement.shortfalls(),
                }
            )
        return rows

    def unavailable_rows(self) -> list[dict[str, Any]]:
        """Skipped and unavailable slots grouped by reason, with the runners that cover them."""

        groups: Counter[tuple[str, str, str, str]] = Counter()
        for state in self.rollup.slots.values():
            evidence = state.evidence
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
            key = tuple(sorted(mapping.items()))
            seen.setdefault(key, mapping)
        return list(seen.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "records": len(self.rollup.records),
            "slots": len(self.rollup.slots),
            "evidence": self.evidence_rows(),
            "parity": self.parity_rows(),
            "completeness": self.completeness_rows(),
            "measurements": self.measurement_rows(),
            "unavailable": self.unavailable_rows(),
            "provenance": self.provenance_rows(),
        }

    def render_json(self) -> str:
        return json.dumps(self.to_json(), indent=2) + "\n"

    def render_markdown(self) -> str:
        lines = [
            "# Qualification report",
            "",
            f"{len(self.rollup.records)} records over {len(self.rollup.slots)} slots. Every count is taken "
            "against its denominator: the declared slots of one kind on one platform through one frontend. "
            "A slot without evidence is unrecorded, never dropped.",
            "",
            "## Evidence",
            "",
        ]
        columns = ("slots", *(status.value for status in self.STATUSES), "unrecorded", "failed")
        lines += self._table(("kind", "platform", "frontend", *columns), self.evidence_rows())
        if parity := self.parity_rows():
            columns = ("slots", *(parity_class.value for parity_class in self.PARITIES), "unclassified")
            lines += [
                "",
                "## Parity classification",
                "",
                *self._table(("kind", "platform", "frontend", *columns), parity),
            ]
        if completeness := self.completeness_rows():
            lines += [
                "",
                "## Inventory completeness",
                "",
                *self._table(
                    ("kind", "platform", "frontend", "rows", "without_owner", "without_regression", "without_status"),
                    completeness,
                ),
            ]
        if measurements := self.measurement_rows():
            rows = [
                {
                    **row,
                    "shortfalls": "; ".join(row["shortfalls"]) or "-",
                    **{name: self._number(row[name]) for name in ("median", "p95", "max")},
                }
                for row in measurements
            ]
            lines += [
                "",
                "## Measurements",
                "",
                *self._table(
                    (
                        "id",
                        "platform",
                        "frontend",
                        "metric",
                        "unit",
                        "samples",
                        "median",
                        "p95",
                        "max",
                        "failures",
                        "status",
                        "shortfalls",
                    ),
                    rows,
                ),
            ]
        if unavailable := self.unavailable_rows():
            lines += [
                "",
                "## Unavailable slots and their coverage",
                "",
                *self._table(("kind", "platform", "slots", "covered_by", "reason"), unavailable),
            ]
        if provenance := self.provenance_rows():
            names = ("source", "runner", "btrc_revision", "btrsmith_revision", "target_triple", "os_build")
            names += ("device_class", "build_mode", "thermal", "power", "recorded_at")
            lines += ["", "## Provenance", "", *self._table(names, provenance)]
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
