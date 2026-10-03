"""The qualification ledger record: one format for every piece of evidence.

Schema identifier: ``btrc.qualification.ledger/1``.

A ledger is a sequence of records. Each record names one *slot* -- one thing
that has to be qualified, on one platform slice, through one frontend -- and
may say how that slot is classified, what evidence currently stands behind it,
which raw samples were measured for it, and the environment that produced the
evidence. The same record carries:

- a P0 inventory row (``operation`` or ``journey``, per platform family, with
  parity, owner, regression and current evidence status);
- a UI-catalog shard row (``family-cell``, ``ui-operation``, ``ui-case``:
  family x platform cells, 162 x 5 x 2 operation slots, 47 x 5 x 2 case slots),
  with its implementation state kept apart from its qualification state;
- a P6 measurement (``scenario``, with raw samples, failures, budgets and the
  host that measured them);
- a test outcome (``test``) from a JUnit run or a gate's skip report;
- a frozen-boundary record (``boundary-record``) from ``boundary-check``.

Encodings
---------
``*.jsonl``  one record object per line (what the adapters write)
``*.json``   ``{"schema": "btrc.qualification.ledger/1", "records": [...]}``
``*.toml``   ``schema = "btrc.qualification.ledger/1"`` then one
             ``[[records]]`` table per record, with ``[records.subject]`` etc.
             An inventory can instead write one ``[[rows]]`` table per
             subject with one cell per target slice (`InventoryRows`).

TOML has no null, so an optional field is always expressed by omitting it; in
JSON, ``null`` means the same as absent. Unknown keys are rejected at every
level, so a misspelled field fails loudly instead of reading as missing.

Record fields
-------------
``schema``                 required; ``btrc.qualification.ledger/1``.

``subject``                required; the slot.
  ``kind``                 required; ``operation`` | ``journey`` |
                           ``family-cell`` | ``ui-operation`` | ``ui-case`` |
                           ``test`` | ``scenario`` | ``boundary-record``.
  ``id``                   required; stable within its kind: a stdlib
                           operation id, a journey id, a UI family, a UI
                           operation or case id, a pytest node id, a bench
                           scenario name, a boundary record id.
  ``platform``             ``macos`` | ``linux`` | ``windows`` | ``ios`` |
                           ``ipados`` | ``android``; absent when the slot is
                           not platform-specific. An inventory row names a
                           platform *family*, and iOS/iPadOS is one family, so
                           it says ``ios`` and never ``ipados``; an iPad run
                           shows in ``provenance.device_class``.
  ``frontend``             ``reference`` (the Python compiler) | ``selfhost``
                           (btrcc); absent when not frontend-specific.
  ``variant``              the artifact variant a test or measurement ran
                           as: ``arm64-simulator``, ``arm64-device``,
                           ``x86_64``, ``release``. It is part of the slot, so
                           simulator and device results never merge. An
                           inventory row names either the family alone or one
                           of the six P0 target slices (``TARGET_SLICES``):
                           windows ``x86_64``/``arm64``, ios
                           ``arm64-device``/``arm64-simulator``, android
                           ``arm64``/``x86_64``; no other variant.
  ``group``                reporting group: stdlib group, UI family, test
                           file, bench suite.
  ``title``                human label.

``classification``         the P0/UI0 disposition of the slot.
  ``parity``               ``equivalent`` | ``adapted`` | ``os-restricted`` |
                           ``missing``.
  ``implementation``       the source state, apart from any qualification:
                           ``missing`` (no provider) | ``source-only``
                           (declared, nothing behind it) | ``partial`` (a
                           provider implements a subset: UI's **P**) |
                           ``custom`` (custom controls stand in for native
                           ones: UI's **C**) | ``implemented`` |
                           ``retired`` (a reviewed decision removed the
                           declaration after its release froze the slot).
                           Retirement is a source state, so it lives here
                           rather than in ``parity`` (about behavior on a
                           platform) or ``evidence`` (what a
                           run showed); it is the one disposition every
                           inventory kind, family cells included, records
                           in this field. A retired slot names its
                           ``decision`` (``btrc-D056``) and carries neither
                           ``parity`` nor ``evidence``; the report lists it
                           apart, never as classified, unclassified or
                           missing.
  ``owner``                who answers for the slot.
  ``regression``           the pytest node id (``path::name``) that pins it,
                           or a list of them. The report derives an inventory
                           slot's evidence from those tests' latest results
                           on its platform, and flags hand-entered evidence
                           that disagrees.
  ``links``                cross-references to the UI roadmap: N-IDs, E-IDs
                           and milestones (``N05``, ``E03``, ``UI2``).
  ``configuration``        the supported OS/toolkit configuration.
  ``input``                the input mechanism the regression exercises.
  ``decision``             the adaptation or decision reference (``D12``,
                           a document anchor).
  ``note``                 free text.

``evidence``               what currently stands behind the slot.
  ``status``               required here; ``source-only`` (declared, no
                           implementation on the slot) | ``implemented-
                           unverified`` (implemented; no passing evidence, or
                           the evidence failed) | ``passed`` (a test or
                           measurement ran and met its acceptance criteria) |
                           ``unavailable`` (the evidence could not be obtained
                           here: skipped, missing tool, device or runner).
  ``observed``             the source's raw outcome word: ``passed``,
                           ``failed``, ``error``, ``skipped``, ``xfailed``,
                           ``measured``, ``checked``, ...
  ``reason``               skip reason, failure summary, restriction.
  ``artifact``             where the raw evidence lives.
  ``covered_by``           only with ``unavailable``: the runners that do
                           cover the slot; an empty list means uncovered.

``measurement``            P6 raw samples; never replaced by a summary.
  ``metric``, ``unit``     required here; e.g. ``wall-time`` in ``s``.
  ``samples``              required here; numbers in run order.
  ``failures``             samples that failed and are therefore not in
                           ``samples``; default 0.
  ``minimum_samples``      how many samples acceptance requires (P6: 5 cold,
                           20 edit/no-op).
  ``components``           name -> numbers, each list as long as
                           ``samples`` (compile/native split, rebuilt units,
                           instructions retired).
  ``budgets``              list of ``{statistic: median|p95|p99|p99.9|max,
                           limit}``.

``provenance``             the environment the evidence came from.
  ``source``               the producing adapter or tool: ``budget_bench``,
                           ``junit``, ``skip-report``, ``boundary-check``,
                           ``inventory``, ...
  ``recorded_at``          ISO 8601 with a UTC offset.
  ``runner``               ``macos`` | ``linux-devcontainer`` | ``windows`` |
                           ``ios`` | ``android`` | another named executor.
  ``btrc_revision``, ``btrsmith_revision``, ``frontend``, ``target_triple``,
  ``sdk_build``, ``os_build``, ``device_id``, ``device_class``, ``cpu``
  (``8P+2E``), ``memory`` (``64 GiB``), ``c_compiler`` (what built the
  measured btrcc: ``Apple clang 17.0.0 -O2``), ``compiler_digest``
  (``sha256:`` of the measured compiler binary), ``jobs`` (worker counts),
  ``build_mode``, ``scale``, ``thermal``, ``power``: strings.

Slots, denominators and merging
-------------------------------
A slot's key is ``(kind, id, platform, frontend, variant)``. A denominator is
the set of distinct slot keys of one kind, so it is fixed by what was
*declared* -- inventory rows, the bench's declared scenarios, a run's
collected tests -- and never shrinks because evidence is missing: an adapter
emits a record without ``evidence`` for a declared slot it has no evidence
for, and the report counts that slot as *unrecorded*. Inventory denominators
are frozen per release in ``tools/qualification/denominators.toml``, so a
deleted row is a missing slot rather than a smaller denominator. When several
records name one slot, the last ``classification`` and the last ``evidence``
in ledger order win independently, so a later test result never erases an
inventory row's owner.

Invariants
----------
- ``passed`` with a measurement requires samples, no failures, at least
  ``minimum_samples`` samples, and every budget met.
- A ``passed`` ``scenario`` also needs a measurement with a budget and a
  declared ``minimum_samples``, and provenance naming its runner,
  btrc_revision, frontend, build_mode, os_build, device_class, cpu and
  memory -- plus c_compiler and compiler_digest for the selfhost frontend.
- ``passed`` never accompanies an observed ``failed``, ``error`` or
  ``skipped`` outcome.
- ``missing`` parity, and ``missing`` or ``source-only`` implementation, is
  never ``passed`` or ``implemented-unverified``.
- ``retired`` implementation names a ``decision`` and comes with no
  ``parity`` and no ``evidence``.
- ``covered_by`` appears only on ``unavailable`` evidence.
- An inventory row never says ``ipados``, names a ``variant`` only when it is
  one of its family's ``TARGET_SLICES``, and its
  evidence carries provenance with ``btrc_revision`` and ``recorded_at``, so
  whether it is current can be checked.
- ``provenance.frontend``, when ``subject.frontend`` is also given, agrees.
"""

from __future__ import annotations

import datetime
import json
import math
import re
import tomllib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.qualification.statistics import SampleStatistics, Statistic

SCHEMA = "btrc.qualification.ledger/1"


class LedgerSchemaError(ValueError):
    """A record or document does not conform to the ledger schema."""


class SubjectKind(StrEnum):
    """The denominators a slot can belong to."""

    OPERATION = "operation"
    JOURNEY = "journey"
    FAMILY_CELL = "family-cell"
    UI_OPERATION = "ui-operation"
    UI_CASE = "ui-case"
    TEST = "test"
    SCENARIO = "scenario"
    BOUNDARY_RECORD = "boundary-record"


class Platform(StrEnum):
    """The platform slices a slot can be qualified on."""

    MACOS = "macos"
    LINUX = "linux"
    WINDOWS = "windows"
    IOS = "ios"
    IPADOS = "ipados"
    ANDROID = "android"


class Frontend(StrEnum):
    """The two compilers that must agree on everything observable."""

    REFERENCE = "reference"
    SELFHOST = "selfhost"


class Parity(StrEnum):
    """How a slot relates to the reference platform's behavior."""

    EQUIVALENT = "equivalent"
    ADAPTED = "adapted"
    OS_RESTRICTED = "os-restricted"
    MISSING = "missing"


class Implementation(StrEnum):
    """What the source provides for a slot, independent of any test result."""

    MISSING = "missing"
    SOURCE_ONLY = "source-only"
    PARTIAL = "partial"
    CUSTOM = "custom"
    IMPLEMENTED = "implemented"
    RETIRED = "retired"


class EvidenceStatus(StrEnum):
    """What currently stands behind a slot."""

    SOURCE_ONLY = "source-only"
    IMPLEMENTED_UNVERIFIED = "implemented-unverified"
    PASSED = "passed"
    UNAVAILABLE = "unavailable"


_FAILED_OBSERVATIONS = frozenset({"failed", "error", "skipped"})
# Rows of a frozen inventory: one slot per platform family, never per variant.
INVENTORY_KINDS = frozenset(
    {
        SubjectKind.OPERATION,
        SubjectKind.JOURNEY,
        SubjectKind.FAMILY_CELL,
        SubjectKind.UI_OPERATION,
        SubjectKind.UI_CASE,
    }
)
# The six P0 target slices (PLAN.md Stage 22): an inventory row may name one
# of them, as its family plus that slice's artifact variant, instead of the
# family alone. iOS device and simulator are distinct artifacts even on arm64.
TARGET_SLICES = {
    "windows-x64": (Platform.WINDOWS, "x86_64"),
    "windows-arm64": (Platform.WINDOWS, "arm64"),
    "ios-device": (Platform.IOS, "arm64-device"),
    "ios-simulator": (Platform.IOS, "arm64-simulator"),
    "android-arm64": (Platform.ANDROID, "arm64"),
    "android-x86_64": (Platform.ANDROID, "x86_64"),
}
# Nothing stands behind such a slot, so no test can have verified it.
_UNIMPLEMENTED = frozenset({Implementation.MISSING, Implementation.SOURCE_ONLY})
# Inventory kinds whose evidence is the result of their regression tests.
REGRESSION_KINDS = INVENTORY_KINDS - {SubjectKind.FAMILY_CELL}
# What a passed P6 measurement must say about the host and build it measured.
SCENARIO_PROVENANCE = ("runner", "btrc_revision", "frontend", "build_mode", "os_build", "device_class", "cpu", "memory")
SELFHOST_PROVENANCE = ("c_compiler", "compiler_digest")
_NODE_ID = re.compile(r"^[^\s:]+::\S")
_LINK = re.compile(r"^[A-Z][A-Za-z]*\d+[a-z]?$")


class FieldReader:
    """Strict field access over one mapping, with a location for every error.

    Ledger records and the denominators manifest both read through it.
    """

    def __init__(self, data: object, where: str, allowed: Iterable[str]) -> None:
        if not isinstance(data, Mapping):
            raise LedgerSchemaError(f"{where}: expected a table, got {type(data).__name__}")
        unknown = sorted(set(data) - set(allowed))
        if unknown:
            raise LedgerSchemaError(f"{where}: unknown field(s) {', '.join(unknown)}")
        self.data = data
        self.where = where

    def present(self, name: str) -> bool:
        return self.data.get(name) is not None

    def text(self, name: str, *, required: bool = False) -> str | None:
        value = self.data.get(name)
        if value is None:
            if required:
                raise LedgerSchemaError(f"{self.where}.{name}: required")
            return None
        if isinstance(value, datetime.datetime):
            value = value.isoformat()
        if not isinstance(value, str):
            raise LedgerSchemaError(f"{self.where}.{name}: expected a string")
        if not value.strip() or value != value.strip() or "\n" in value:
            raise LedgerSchemaError(f"{self.where}.{name}: must be non-empty single-line text without padding")
        return value

    def choice[E: StrEnum](self, name: str, enum: type[E], *, required: bool = False) -> E | None:
        value = self.text(name, required=required)
        if value is None:
            return None
        try:
            return enum(value)
        except ValueError:
            choices = ", ".join(member.value for member in enum)
            raise LedgerSchemaError(f"{self.where}.{name}: {value!r} is not one of {choices}") from None

    def integer(self, name: str, *, default: int | None = None, minimum: int = 0) -> int | None:
        value = self.data.get(name)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, int):
            raise LedgerSchemaError(f"{self.where}.{name}: expected an integer")
        if value < minimum:
            raise LedgerSchemaError(f"{self.where}.{name}: must be at least {minimum}")
        return value

    def numbers(self, name: str, *, required: bool = False) -> tuple[float, ...] | None:
        value = self.data.get(name)
        if value is None:
            if required:
                raise LedgerSchemaError(f"{self.where}.{name}: required")
            return None
        return self.number_list(value, f"{self.where}.{name}")

    @staticmethod
    def number_list(value: object, where: str) -> tuple[float, ...]:
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise LedgerSchemaError(f"{where}: expected a list of numbers")
        result = []
        for index, item in enumerate(value):
            if isinstance(item, bool) or not isinstance(item, int | float) or not math.isfinite(item):
                raise LedgerSchemaError(f"{where}[{index}]: expected a finite number")
            result.append(item)
        return tuple(result)

    def texts(self, name: str) -> tuple[str, ...] | None:
        value = self.data.get(name)
        if value is None:
            return None
        if not isinstance(value, Sequence) or isinstance(value, str):
            raise LedgerSchemaError(f"{self.where}.{name}: expected a list of strings")
        result = []
        for index, item in enumerate(value):
            if not isinstance(item, str) or not item.strip() or item != item.strip():
                raise LedgerSchemaError(f"{self.where}.{name}[{index}]: expected non-empty text")
            result.append(item)
        if len(set(result)) != len(result):
            raise LedgerSchemaError(f"{self.where}.{name}: entries must be unique")
        return tuple(result)

    def references(self, name: str, pattern: re.Pattern[str], what: str) -> tuple[str, ...] | None:
        """One reference or a list of them, each matching `pattern`."""

        value = self.data.get(name)
        if isinstance(value, str):
            value = [value]
        references = FieldReader({name: value}, self.where, (name,)).texts(name)
        for reference in references or ():
            if not pattern.match(reference) or "\n" in reference:
                raise LedgerSchemaError(f"{self.where}.{name}: {reference!r} is not {what}")
        if references == ():
            raise LedgerSchemaError(f"{self.where}.{name}: expected at least one entry")
        return references


def _compact(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Drop absent fields so every encoding, TOML included, omits them alike."""

    return {key: value for key, value in mapping.items() if value is not None}


@dataclass(frozen=True, slots=True)
class Subject:
    """The slot a record is about."""

    kind: SubjectKind
    id: str
    platform: Platform | None = None
    frontend: Frontend | None = None
    group: str | None = None
    title: str | None = None
    variant: str | None = None

    FIELDS = ("kind", "id", "platform", "frontend", "variant", "group", "title")

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        """The slot identity: kind, id, platform, frontend and artifact variant."""

        return (self.kind.value, self.id, self.platform or "", self.frontend or "", self.variant or "")

    def problem(self) -> str | None:
        """Why this cannot be a slot, or None: an inventory slot is one platform family."""

        if self.kind in INVENTORY_KINDS and self.platform is Platform.IPADOS:
            return (
                f"a {self.kind.value} row names the iOS/iPadOS family as ios; record an iPad in provenance.device_class"
            )
        if self.kind in INVENTORY_KINDS and self.variant is not None:
            if (self.platform, self.variant) not in TARGET_SLICES.values():
                slices = ", ".join(TARGET_SLICES)
                return f"a {self.kind.value} row names its platform family or one target slice ({slices})"
        return None

    @classmethod
    def from_mapping(cls, data: object, where: str) -> Subject:
        fields = FieldReader(data, where, cls.FIELDS)
        return cls(
            kind=fields.choice("kind", SubjectKind, required=True),
            id=fields.text("id", required=True),
            platform=fields.choice("platform", Platform),
            frontend=fields.choice("frontend", Frontend),
            variant=fields.text("variant"),
            group=fields.text("group"),
            title=fields.text("title"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return _compact(
            {
                "kind": self.kind.value,
                "id": self.id,
                "platform": self.platform.value if self.platform else None,
                "frontend": self.frontend.value if self.frontend else None,
                "variant": self.variant,
                "group": self.group,
                "title": self.title,
            }
        )


@dataclass(frozen=True, slots=True)
class Classification:
    """The P0/UI0 disposition of a slot."""

    parity: Parity | None = None
    implementation: Implementation | None = None
    owner: str | None = None
    regression: tuple[str, ...] | None = None
    links: tuple[str, ...] | None = None
    configuration: str | None = None
    input: str | None = None
    decision: str | None = None
    note: str | None = None

    FIELDS = (
        "parity",
        "implementation",
        "owner",
        "regression",
        "links",
        "configuration",
        "input",
        "decision",
        "note",
    )

    @classmethod
    def from_mapping(cls, data: object, where: str) -> Classification:
        fields = FieldReader(data, where, cls.FIELDS)
        return cls(
            parity=fields.choice("parity", Parity),
            implementation=fields.choice("implementation", Implementation),
            owner=fields.text("owner"),
            regression=fields.references("regression", _NODE_ID, "a pytest node id (path::name)"),
            links=fields.references("links", _LINK, "an N-ID, E-ID or milestone such as N05, E03 or UI2"),
            configuration=fields.text("configuration"),
            input=fields.text("input"),
            decision=fields.text("decision"),
            note=fields.text("note"),
        )

    def to_mapping(self) -> dict[str, Any]:
        # One regression is written as the node id itself, several as a list.
        regression: str | list[str] | None = list(self.regression) if self.regression else None
        if regression is not None and len(regression) == 1:
            regression = regression[0]
        return _compact(
            {
                "parity": self.parity.value if self.parity else None,
                "implementation": self.implementation.value if self.implementation else None,
                "owner": self.owner,
                "regression": regression,
                "links": list(self.links) if self.links else None,
                "configuration": self.configuration,
                "input": self.input,
                "decision": self.decision,
                "note": self.note,
            }
        )


@dataclass(frozen=True, slots=True)
class Evidence:
    """What currently stands behind a slot."""

    status: EvidenceStatus
    observed: str | None = None
    reason: str | None = None
    artifact: str | None = None
    covered_by: tuple[str, ...] | None = None

    FIELDS = ("status", "observed", "reason", "artifact", "covered_by")

    @classmethod
    def from_mapping(cls, data: object, where: str) -> Evidence:
        fields = FieldReader(data, where, cls.FIELDS)
        return cls(
            status=fields.choice("status", EvidenceStatus, required=True),
            observed=fields.text("observed"),
            reason=cls._reason(fields),
            artifact=fields.text("artifact"),
            covered_by=fields.texts("covered_by"),
        )

    @staticmethod
    def _reason(fields: FieldReader) -> str | None:
        # Skip and failure reasons are quoted from tools verbatim, and those
        # span lines; only the identifiers above must be single-line.
        value = fields.data.get("reason")
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise LedgerSchemaError(f"{fields.where}.reason: expected non-empty text")
        return value

    def to_mapping(self) -> dict[str, Any]:
        return _compact(
            {
                "status": self.status.value,
                "observed": self.observed,
                "reason": self.reason,
                "artifact": self.artifact,
                "covered_by": list(self.covered_by) if self.covered_by is not None else None,
            }
        )


@dataclass(frozen=True, slots=True)
class Budget:
    """An acceptance limit on one summary of a sample set."""

    statistic: Statistic
    limit: float

    FIELDS = ("statistic", "limit")

    @classmethod
    def from_mapping(cls, data: object, where: str) -> Budget:
        fields = FieldReader(data, where, cls.FIELDS)
        limit = fields.data.get("limit")
        if isinstance(limit, bool) or not isinstance(limit, int | float) or not math.isfinite(limit) or limit < 0:
            raise LedgerSchemaError(f"{where}.limit: expected a finite non-negative number")
        return cls(statistic=fields.choice("statistic", Statistic, required=True), limit=limit)

    def met_by(self, statistics: SampleStatistics) -> bool:
        return statistics.value(self.statistic) <= self.limit

    def to_mapping(self) -> dict[str, Any]:
        return {"statistic": self.statistic.value, "limit": self.limit}


@dataclass(frozen=True, slots=True)
class Measurement:
    """Raw samples for one slot, kept as measured."""

    metric: str
    unit: str
    samples: tuple[float, ...]
    failures: int = 0
    minimum_samples: int | None = None
    components: Mapping[str, tuple[float, ...]] = field(default_factory=dict)
    budgets: tuple[Budget, ...] = ()

    FIELDS = ("metric", "unit", "samples", "failures", "minimum_samples", "components", "budgets")

    @classmethod
    def from_mapping(cls, data: object, where: str) -> Measurement:
        fields = FieldReader(data, where, cls.FIELDS)
        samples = fields.numbers("samples", required=True)
        components: dict[str, tuple[float, ...]] = {}
        raw_components = fields.data.get("components")
        if raw_components is not None:
            if not isinstance(raw_components, Mapping):
                raise LedgerSchemaError(f"{where}.components: expected a table of number lists")
            for name, values in raw_components.items():
                if not isinstance(name, str) or not name.strip():
                    raise LedgerSchemaError(f"{where}.components: names must be non-empty text")
                numbers = FieldReader.number_list(values, f"{where}.components.{name}")
                if len(numbers) != len(samples):
                    raise LedgerSchemaError(
                        f"{where}.components.{name}: {len(numbers)} values for {len(samples)} samples"
                    )
                components[name] = numbers
        raw_budgets = fields.data.get("budgets")
        if raw_budgets is not None and (not isinstance(raw_budgets, Sequence) or isinstance(raw_budgets, str)):
            raise LedgerSchemaError(f"{where}.budgets: expected a list of tables")
        budgets = tuple(
            Budget.from_mapping(budget, f"{where}.budgets[{index}]") for index, budget in enumerate(raw_budgets or ())
        )
        return cls(
            metric=fields.text("metric", required=True),
            unit=fields.text("unit", required=True),
            samples=samples,
            failures=fields.integer("failures", default=0),
            minimum_samples=fields.integer("minimum_samples", minimum=1),
            components=components,
            budgets=budgets,
        )

    @property
    def statistics(self) -> SampleStatistics | None:
        return SampleStatistics.of(self.samples)

    def shortfalls(self) -> list[str]:
        """Every reason these samples fall short of acceptance; empty when accepted."""

        problems = []
        summary = self.statistics
        if summary is None:
            problems.append("no samples")
        if self.failures:
            problems.append(f"{self.failures} failed sample(s)")
        if self.minimum_samples is not None and len(self.samples) < self.minimum_samples:
            problems.append(f"{len(self.samples)} of {self.minimum_samples} required samples")
        if summary is not None:
            for budget in self.budgets:
                if not budget.met_by(summary):
                    value = summary.value(budget.statistic)
                    problems.append(f"{budget.statistic.value} {value:g} exceeds {budget.limit:g} {self.unit}")
        return problems

    def to_mapping(self) -> dict[str, Any]:
        return _compact(
            {
                "metric": self.metric,
                "unit": self.unit,
                "samples": list(self.samples),
                "failures": self.failures,
                "minimum_samples": self.minimum_samples,
                "components": {name: list(values) for name, values in self.components.items()} or None,
                "budgets": [budget.to_mapping() for budget in self.budgets] or None,
            }
        )


@dataclass(frozen=True, slots=True)
class Provenance:
    """The environment a piece of evidence came from."""

    source: str | None = None
    recorded_at: str | None = None
    runner: str | None = None
    btrc_revision: str | None = None
    btrsmith_revision: str | None = None
    frontend: Frontend | None = None
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

    FIELDS = (
        "source",
        "recorded_at",
        "runner",
        "btrc_revision",
        "btrsmith_revision",
        "frontend",
        "target_triple",
        "sdk_build",
        "os_build",
        "device_id",
        "device_class",
        "cpu",
        "memory",
        "c_compiler",
        "compiler_digest",
        "jobs",
        "build_mode",
        "scale",
        "thermal",
        "power",
    )
    TEXT_FIELDS = tuple(name for name in FIELDS if name not in {"recorded_at", "frontend"})

    @classmethod
    def from_mapping(cls, data: object, where: str) -> Provenance:
        fields = FieldReader(data, where, cls.FIELDS)
        recorded_at = fields.text("recorded_at")
        if recorded_at is not None:
            try:
                moment = datetime.datetime.fromisoformat(recorded_at)
            except ValueError:
                raise LedgerSchemaError(f"{where}.recorded_at: {recorded_at!r} is not ISO 8601") from None
            if moment.tzinfo is None:
                raise LedgerSchemaError(f"{where}.recorded_at: must carry a UTC offset")
        return cls(
            recorded_at=recorded_at,
            frontend=fields.choice("frontend", Frontend),
            **{name: fields.text(name) for name in cls.TEXT_FIELDS},
        )

    def to_mapping(self) -> dict[str, Any]:
        return _compact(
            {
                name: (value.value if isinstance(value, StrEnum) else value)
                for name in self.FIELDS
                if (value := getattr(self, name)) is not None
            }
        )

    def overlay(self, other: Provenance | None) -> Provenance:
        """These fields, replaced by every field `other` states."""

        if other is None:
            return self
        return replace(self, **{name: value for name in self.FIELDS if (value := getattr(other, name)) is not None})

    def lacking(self, names: Iterable[str]) -> list[str]:
        return [name for name in names if getattr(self, name) is None]


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    """One slot with its classification, evidence, samples and provenance."""

    subject: Subject
    classification: Classification | None = None
    evidence: Evidence | None = None
    measurement: Measurement | None = None
    provenance: Provenance | None = None

    FIELDS = ("schema", "subject", "classification", "evidence", "measurement", "provenance")

    def __post_init__(self) -> None:
        if problem := self.problem():
            raise LedgerSchemaError(problem)

    def problem(self) -> str | None:
        """The first cross-field invariant this record breaks, or None."""

        if problem := self.subject.problem():
            return problem
        evidence = self.evidence
        if evidence is not None and evidence.status is EvidenceStatus.PASSED:
            if evidence.observed in _FAILED_OBSERVATIONS:
                return f"passed evidence cannot record an observed {evidence.observed!r}"
        if (
            evidence is not None
            and evidence.covered_by is not None
            and evidence.status is not EvidenceStatus.UNAVAILABLE
        ):
            return "covered_by belongs only to unavailable evidence"
        classification = self.classification
        if classification is not None and classification.implementation is Implementation.RETIRED:
            if classification.decision is None:
                return "a retired slot names the decision that retired it"
            if classification.parity is not None:
                return "a retired slot has no parity class"
            if evidence is not None:
                return "a retired slot carries no evidence"
        if (
            classification is not None
            and evidence is not None
            and evidence.status in {EvidenceStatus.PASSED, EvidenceStatus.IMPLEMENTED_UNVERIFIED}
        ):
            if classification.parity is Parity.MISSING:
                return f"a missing slot cannot be {evidence.status.value}"
            if (implementation := classification.implementation) in _UNIMPLEMENTED:
                return f"a slot whose implementation is {implementation.value} cannot be {evidence.status.value}"
        if (
            self.provenance is not None
            and self.provenance.frontend is not None
            and self.subject.frontend is not None
            and self.provenance.frontend is not self.subject.frontend
        ):
            return "provenance frontend disagrees with the subject's"
        if evidence is not None and self.subject.kind in INVENTORY_KINDS:
            lacking = (self.provenance or Provenance()).lacking(("btrc_revision", "recorded_at"))
            if lacking:
                return f"evidence on a {self.subject.kind.value} row needs provenance {' and '.join(lacking)}"
        if evidence is not None and evidence.status is EvidenceStatus.PASSED:
            if shortfalls := self.acceptance_shortfalls(self.subject, self.measurement, self.provenance):
                return f"passed evidence falls short: {'; '.join(shortfalls)}"
        return None

    @staticmethod
    def acceptance_shortfalls(
        subject: Subject, measurement: Measurement | None, provenance: Provenance | None
    ) -> list[str]:
        """Every reason `passed` evidence for these samples would be refused; empty when it is accepted."""

        if subject.kind is not SubjectKind.SCENARIO:
            return measurement.shortfalls() if measurement is not None else []
        if measurement is None:
            return ["no measurement"]
        problems = measurement.shortfalls()
        if not measurement.budgets:
            problems.append("no budget declared")
        if measurement.minimum_samples is None:
            problems.append("no minimum sample count declared")
        provenance = provenance or Provenance()
        required = SCENARIO_PROVENANCE
        if (subject.frontend or provenance.frontend) is Frontend.SELFHOST:
            required += SELFHOST_PROVENANCE
        if lacking := provenance.lacking(required):
            problems.append(f"provenance lacks {', '.join(lacking)}")
        return problems

    @classmethod
    def from_mapping(cls, data: object, where: str = "record") -> LedgerRecord:
        fields = FieldReader(data, where, cls.FIELDS)
        schema = fields.text("schema", required=True)
        if schema != SCHEMA:
            raise LedgerSchemaError(f"{where}.schema: {schema!r} is not {SCHEMA!r}")
        if not fields.present("subject"):
            raise LedgerSchemaError(f"{where}.subject: required")
        sections = fields.data
        subject = Subject.from_mapping(sections["subject"], f"{where}.subject")
        classification = (
            Classification.from_mapping(sections["classification"], f"{where}.classification")
            if fields.present("classification")
            else None
        )
        evidence = (
            Evidence.from_mapping(sections["evidence"], f"{where}.evidence") if fields.present("evidence") else None
        )
        measurement = (
            Measurement.from_mapping(sections["measurement"], f"{where}.measurement")
            if fields.present("measurement")
            else None
        )
        provenance = (
            Provenance.from_mapping(sections["provenance"], f"{where}.provenance")
            if fields.present("provenance")
            else None
        )
        try:
            return cls(subject, classification, evidence, measurement, provenance)
        except LedgerSchemaError as error:
            raise LedgerSchemaError(f"{where}: {error}") from None

    def to_mapping(self) -> dict[str, Any]:
        return _compact(
            {
                "schema": SCHEMA,
                "subject": self.subject.to_mapping(),
                "classification": self.classification.to_mapping() if self.classification else None,
                "evidence": self.evidence.to_mapping() if self.evidence else None,
                "measurement": self.measurement.to_mapping() if self.measurement else None,
                "provenance": self.provenance.to_mapping() if self.provenance else None,
            }
        )


class LedgerDocument:
    """Read and write whole ledgers in the three encodings."""

    @classmethod
    def load(cls, path: Path) -> list[LedgerRecord]:
        """Every record in `path`, validated; the suffix selects the encoding."""

        suffix = path.suffix.lower()
        if suffix == ".jsonl":
            records = []
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as error:
                    raise LedgerSchemaError(f"{path}:{number}: {error.msg}") from None
                records.append(LedgerRecord.from_mapping(data, f"{path}:{number}"))
            return records
        if suffix == ".json":
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise LedgerSchemaError(f"{path}: {error.msg}") from None
            return cls.from_document(document, str(path))
        if suffix == ".toml":
            try:
                document = tomllib.loads(path.read_text(encoding="utf-8"))
            except tomllib.TOMLDecodeError as error:
                raise LedgerSchemaError(f"{path}: {error}") from None
            return cls.from_document(document, str(path))
        raise LedgerSchemaError(f"{path}: a ledger is .jsonl, .json or .toml")

    @staticmethod
    def from_document(document: object, where: str) -> list[LedgerRecord]:
        fields = FieldReader(document, where, ("schema", "records", *InventoryRows.DOCUMENT_FIELDS))
        schema = fields.text("schema", required=True)
        if schema != SCHEMA:
            raise LedgerSchemaError(f"{where}.schema: {schema!r} is not {SCHEMA!r}")
        records = fields.data.get("records") or []
        if not isinstance(records, Sequence) or isinstance(records, str):
            raise LedgerSchemaError(f"{where}.records: expected a list of records")
        loaded = []
        for index, record in enumerate(records):
            if isinstance(record, Mapping) and "schema" not in record:
                record = {"schema": SCHEMA, **record}
            loaded.append(LedgerRecord.from_mapping(record, f"{where}.records[{index}]"))
        return loaded + InventoryRows.expand(fields, where)

    @staticmethod
    def dumps_jsonl(records: Iterable[LedgerRecord]) -> str:
        return "".join(json.dumps(record.to_mapping(), sort_keys=True) + "\n" for record in records)


class InventoryRows:
    """The compact TOML form of a sliced inventory: one table per subject, one cell per target slice.

    A P0 inventory repeats its subject, regression and provenance on every
    slice, so a ledger document may also hold::

        provenance = { recorded_at = "2026-10-02T00:00:00+00:00", btrc_revision = "c7f785e" }

        [[rows]]
        kind = "operation"
        id = "Library.Process"
        group = "stdlib"
        regression = ["src/tests/python/test_stdlib_process_security.py::test_..."]
        windows-x64 = { parity = "adapted", implementation = "missing", owner = "W1", status = "source-only", reason = "..." }
        ...

    Each row is the subject's ``kind``, ``id``, ``group`` and ``title``, any
    classification field the slices share, and a cell named for each slice in
    `TARGET_SLICES`. A cell holds that slice's classification fields and its
    evidence fields (``status`` for the evidence status), so a cell field
    overrides the row's. Every row expands, in slice order, to one ordinary
    `LedgerRecord` per cell -- the slice's family plus its artifact variant --
    carrying the document's ``provenance``, and is validated as one. Rows
    follow the document's ``records``.
    """

    DOCUMENT_FIELDS = ("provenance", "rows")
    SUBJECT_FIELDS = ("kind", "id", "group", "title")
    EVIDENCE_FIELDS = ("status", "observed", "reason", "artifact")

    @classmethod
    def expand(cls, document: FieldReader, where: str) -> list[LedgerRecord]:
        rows = document.data.get("rows") or []
        if not isinstance(rows, Sequence) or isinstance(rows, str):
            raise LedgerSchemaError(f"{where}.rows: expected a list of tables")
        provenance = document.data.get("provenance")
        if provenance is not None:
            Provenance.from_mapping(provenance, f"{where}.provenance")
        records = []
        for index, row in enumerate(rows):
            records += cls.records(row, provenance, f"{where}.rows[{index}]")
        return records

    @classmethod
    def records(cls, row: object, provenance: object, where: str) -> list[LedgerRecord]:
        fields = FieldReader(row, where, (*cls.SUBJECT_FIELDS, *Classification.FIELDS, *TARGET_SLICES))
        shared = {name: value for name, value in fields.data.items() if name in Classification.FIELDS}
        subject = {name: value for name, value in fields.data.items() if name in cls.SUBJECT_FIELDS}
        cells = [name for name in TARGET_SLICES if name in fields.data]
        if not cells:
            raise LedgerSchemaError(f"{where}: a row needs at least one slice cell ({', '.join(TARGET_SLICES)})")
        records = []
        for name in cells:
            cell = FieldReader(fields.data[name], f"{where}.{name}", (*Classification.FIELDS, *cls.EVIDENCE_FIELDS))
            platform, variant = TARGET_SLICES[name]
            record: dict[str, Any] = {
                "schema": SCHEMA,
                "subject": {**subject, "platform": platform.value, "variant": variant},
                "classification": {
                    **shared,
                    **{key: value for key, value in cell.data.items() if key in Classification.FIELDS},
                },
            }
            evidence = {key: value for key, value in cell.data.items() if key in cls.EVIDENCE_FIELDS}
            if evidence:
                record["evidence"] = evidence
            if provenance is not None:
                record["provenance"] = provenance
            records.append(LedgerRecord.from_mapping(record, f"{where}.{name}"))
        return records
