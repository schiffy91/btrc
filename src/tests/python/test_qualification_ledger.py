"""The qualification ledger: schema validation, statistics, adapters and the report."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from tools.qualification.schema import (
    SCHEMA,
    EvidenceStatus,
    LedgerDocument,
    LedgerRecord,
    LedgerSchemaError,
    Parity,
    SubjectKind,
)
from tools.qualification.statistics import SampleStatistics, Statistic

# A cold-transpile sample set from a recorded budget_bench run (final-65057cb).
COLD_TRANSPILE = [45.885, 43.574, 43.759, 43.324, 43.076]
# Everything a passed P6 measurement must say about the host and the compiler it measured.
P6_HOST = {
    "source": "budget_bench",
    "recorded_at": "2026-09-24T10:00:00+00:00",
    "runner": "macos",
    "btrc_revision": "65057cb",
    "frontend": "selfhost",
    "os_build": "macOS 27.0 (27A5)",
    "device_class": "MacBookPro18,2 (Apple M1 Max)",
    "cpu": "8P+2E",
    "memory": "64 GiB",
    "c_compiler": "Apple clang version 17.0.0 -O2",
    "compiler_digest": "sha256:" + "0" * 64,
    "build_mode": "debug",
}
# Inventory evidence is current only as of a revision and a moment.
AUDIT = {"source": "inventory", "btrc_revision": "4e5c982", "recorded_at": "2026-09-21T12:00:00+00:00"}


def _record(**sections) -> dict:
    return {"schema": SCHEMA, "subject": {"kind": "scenario", "id": "cold-dev"}, **sections}


# --- statistics -------------------------------------------------------------


def test_nearest_rank_p95_of_five_cold_builds_is_the_slowest():
    summary = SampleStatistics.of(COLD_TRANSPILE)

    assert summary is not None
    assert (summary.count, summary.median, summary.p95, summary.maximum) == (5, 43.574, 45.885, 45.885)
    assert summary.minimum == 43.076


def test_nearest_rank_p95_of_twenty_edits_is_the_nineteenth():
    samples = [float(value) for value in range(20, 0, -1)]
    summary = SampleStatistics.of(samples)

    assert summary is not None
    assert summary.p95 == 19.0
    assert summary.median == 10.5
    assert summary.value(Statistic.MAX) == 20.0


def test_nearest_rank_never_interpolates():
    ordered = [1.0, 2.0, 3.0, 4.0]

    assert SampleStatistics.nearest_rank(ordered, 0.5) == 2.0
    assert SampleStatistics.nearest_rank(ordered, 0.51) == 3.0
    assert SampleStatistics.nearest_rank(ordered, 1.0) == 4.0
    assert SampleStatistics.nearest_rank([7.0], 0.95) == 7.0


def test_p99_and_p999_are_nearest_rank_and_budgetable():
    from tools.qualification.cli import QualificationCommand

    summary = SampleStatistics.of(float(value) for value in range(1000, 0, -1))

    assert (summary.p99, summary.p999, summary.maximum) == (990.0, 999.0, 1000.0)
    assert summary.value(Statistic.P99) == 990.0
    assert summary.value(Statistic("p99.9")) == 999.0
    budgets = QualificationCommand.budgets(["noop:p99<=33.3", "noop:p99.9<=75", "noop:median<=5"])
    assert [(budget.statistic.value, budget.limit) for budget in budgets["noop"]] == [
        ("p99", 33.3),
        ("p99.9", 75.0),
        ("median", 5.0),
    ]
    budget = {"statistic": "p99", "limit": 33.3}
    record = LedgerRecord.from_mapping(
        _record(measurement={"metric": "frame-time", "unit": "ms", "samples": [16.7], "budgets": [budget]})
    )
    assert record.measurement.budgets[0].statistic is Statistic.P99


def test_statistics_of_no_samples_is_absent_and_bad_input_is_rejected():
    assert SampleStatistics.of([]) is None
    with pytest.raises(ValueError, match="finite"):
        SampleStatistics.of([1.0, float("nan")])
    with pytest.raises(ValueError):
        SampleStatistics.nearest_rank([], 0.95)
    with pytest.raises(ValueError):
        SampleStatistics.nearest_rank([1.0], 0.0)


# --- schema -----------------------------------------------------------------


def test_a_complete_record_round_trips_through_every_section():
    data = {
        "schema": SCHEMA,
        "subject": {
            "kind": "ui-operation",
            "id": "ui.TextField.setText",
            "platform": "windows",
            "frontend": "selfhost",
            "group": "text-input",
            "title": "TextField.setText",
        },
        "classification": {
            "parity": "adapted",
            "implementation": "partial",
            "owner": "windows-ui",
            "regression": [
                "src/tests/python/test_text_field.py::test_set_text",
                "src/tests/python/test_text_field.py::test_set_text_preserves_selection",
            ],
            "links": ["N05", "N10", "E01", "UI2"],
            "configuration": "Windows 11 24H2, Win32 EDIT with TSF",
            "input": "hardware keyboard and IME composition",
            "decision": "D12",
            "note": "IME composition routes through TSF",
        },
        "evidence": {"status": "passed", "observed": "passed", "artifact": "raw/run-1/junit.xml"},
        "provenance": {
            "source": "junit",
            "recorded_at": "2026-09-30T12:00:00+00:00",
            "runner": "windows",
            "btrc_revision": "cd29c43",
            "frontend": "selfhost",
            "target_triple": "x86_64-pc-windows-msvc",
            "sdk_build": "10.0.26100.0",
            "os_build": "26100.1",
            "device_id": "ci-runner-7",
            "device_class": "x86_64",
            "cpu": "4 logical CPUs",
            "memory": "16 GiB",
            "c_compiler": "zig cc 0.14.0 -O2",
            "compiler_digest": "sha256:" + "1" * 64,
            "jobs": "4",
            "build_mode": "debug",
            "scale": "1.5",
        },
    }

    record = LedgerRecord.from_mapping(data)

    assert record.subject.kind is SubjectKind.UI_OPERATION
    assert record.classification is not None and record.classification.parity is Parity.ADAPTED
    assert record.classification.links == ("N05", "N10", "E01", "UI2")
    assert record.evidence is not None and record.evidence.status is EvidenceStatus.PASSED
    assert record.to_mapping() == data


def test_a_p6_record_keeps_raw_samples_components_and_budgets():
    record = LedgerRecord.from_mapping(
        _record(
            evidence={"status": "passed", "observed": "measured"},
            measurement={
                "metric": "wall-time",
                "unit": "s",
                "samples": COLD_TRANSPILE,
                "minimum_samples": 5,
                "components": {"compile": COLD_TRANSPILE, "native": [0, 0, 0, 0, 0]},
                "budgets": [{"statistic": "median", "limit": 45}, {"statistic": "p95", "limit": 46}],
            },
            provenance=P6_HOST,
        )
    )

    assert record.measurement is not None
    assert record.measurement.samples == tuple(COLD_TRANSPILE)
    assert record.measurement.shortfalls() == []
    assert LedgerRecord.from_mapping(record.to_mapping()) == record


@pytest.mark.parametrize(
    ("measurement", "message"),
    [
        ({"samples": COLD_TRANSPILE, "budgets": [{"statistic": "p95", "limit": 45}]}, "p95 45.885 exceeds 45 s"),
        ({"samples": COLD_TRANSPILE, "failures": 1}, "1 failed sample"),
        ({"samples": COLD_TRANSPILE[:2], "minimum_samples": 5}, "2 of 5 required samples"),
        ({"samples": []}, "no samples"),
    ],
)
def test_passed_evidence_requires_accepted_samples(measurement, message):
    data = _record(
        evidence={"status": "passed"},
        measurement={"metric": "wall-time", "unit": "s", **measurement},
    )

    with pytest.raises(LedgerSchemaError, match=message):
        LedgerRecord.from_mapping(data)
    unverified = {**data, "evidence": {"status": "implemented-unverified"}}
    assert LedgerRecord.from_mapping(unverified).measurement.shortfalls()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"surprise": 1}, r"record: unknown field\(s\) surprise"),
        ({"subject": {"kind": "scenario", "id": "x", "platfrom": "ios"}}, "unknown field"),
        ({"subject": {"kind": "widget", "id": "x"}}, "'widget' is not one of operation, journey"),
        ({"subject": {"kind": "scenario"}}, r"subject\.id: required"),
        ({"subject": {"kind": "scenario", "id": " padded"}}, "without padding"),
        ({"subject": {"kind": "scenario", "id": "x", "platform": "beos"}}, "is not one of macos"),
        ({"schema": "btrc.qualification.ledger/0"}, "is not 'btrc.qualification.ledger/1'"),
        ({"evidence": {"observed": "passed"}}, r"evidence\.status: required"),
        ({"evidence": {"status": "passed", "observed": "failed"}}, "cannot record an observed 'failed'"),
        ({"evidence": {"status": "passed", "covered_by": ["linux-devcontainer"]}}, "only to unavailable"),
        (
            {"classification": {"parity": "missing"}, "evidence": {"status": "passed"}},
            "a missing slot cannot be passed",
        ),
        ({"provenance": {"recorded_at": "2026-09-30T12:00:00"}}, "UTC offset"),
        ({"provenance": {"recorded_at": "yesterday"}}, "not ISO 8601"),
        (
            {"measurement": {"metric": "wall-time", "unit": "s", "samples": [1, 2], "components": {"native": [1]}}},
            "1 values for 2 samples",
        ),
        ({"measurement": {"metric": "wall-time", "unit": "s", "samples": [1, True]}}, "finite number"),
        (
            {
                "measurement": {
                    "metric": "m",
                    "unit": "s",
                    "samples": [1],
                    "budgets": [{"statistic": "p50", "limit": 1}],
                }
            },
            "'p50' is not one of median, p95, p99, p99.9, max",
        ),
        ({"classification": {"parity": "partial"}}, "'partial' is not one of equivalent"),
        ({"classification": {"implementation": "done"}}, "'done' is not one of missing, source-only, partial"),
        ({"classification": {"regression": "src/tests/stdlib/FileSystemText.btrc"}}, "is not a pytest node id"),
        ({"classification": {"regression": []}}, "expected at least one entry"),
        ({"classification": {"regression": ["a.py::t", "a.py::t"]}}, "unique"),
        ({"classification": {"links": ["text input"]}}, "is not an N-ID, E-ID or milestone"),
    ],
)
def test_schema_violations_fail_with_their_location(change, message):
    with pytest.raises(LedgerSchemaError, match=message):
        LedgerRecord.from_mapping({**_record(), **change})


@pytest.mark.parametrize(
    ("measurement", "provenance", "message"),
    [
        # The reviewer's probe: one sample, no budget, no minimum, no host.
        ({"samples": [99.0]}, None, "no budget declared; no minimum sample count declared; provenance lacks runner"),
        (
            {"samples": COLD_TRANSPILE, "minimum_samples": 5},
            P6_HOST,
            "no budget declared",
        ),
        (
            {"samples": COLD_TRANSPILE, "budgets": [{"statistic": "median", "limit": 45}]},
            P6_HOST,
            "no minimum sample count declared",
        ),
        (
            {"samples": COLD_TRANSPILE, "minimum_samples": 5, "budgets": [{"statistic": "median", "limit": 45}]},
            {key: value for key, value in P6_HOST.items() if key not in {"cpu", "c_compiler", "compiler_digest"}},
            "provenance lacks cpu, c_compiler, compiler_digest$",
        ),
    ],
)
def test_a_passed_scenario_needs_a_budget_a_minimum_and_its_host(measurement, provenance, message):
    data = _record(evidence={"status": "passed"}, measurement={"metric": "wall-time", "unit": "s", **measurement})
    if provenance is not None:
        data["provenance"] = provenance

    with pytest.raises(LedgerSchemaError, match=message):
        LedgerRecord.from_mapping(data)
    assert LedgerRecord.from_mapping({**data, "evidence": {"status": "implemented-unverified"}})


def test_only_a_selfhost_measurement_must_name_the_c_compiler_that_built_btrcc():
    reference = {key: value for key, value in P6_HOST.items() if key not in {"c_compiler", "compiler_digest"}} | {
        "frontend": "reference"
    }
    data = _record(
        subject={"kind": "scenario", "id": "cold-dev", "frontend": "reference"},
        evidence={"status": "passed"},
        measurement={
            "metric": "wall-time",
            "unit": "s",
            "samples": COLD_TRANSPILE,
            "minimum_samples": 5,
            "budgets": [{"statistic": "median", "limit": 90}],
        },
        provenance=reference,
    )

    assert LedgerRecord.from_mapping(data).evidence.status is EvidenceStatus.PASSED


INVENTORY = ("operation", "journey", "family-cell", "ui-operation", "ui-case")


@pytest.mark.parametrize("kind", INVENTORY)
def test_an_inventory_row_names_the_ios_family_or_one_target_slice(kind):
    with pytest.raises(LedgerSchemaError, match="names the iOS/iPadOS family as ios"):
        LedgerRecord.from_mapping({"schema": SCHEMA, "subject": {"kind": kind, "id": "x", "platform": "ipados"}})
    for platform, variant in (("ios", "release"), ("ios", "x86_64"), ("windows", "arm64-device"), ("macos", "arm64")):
        with pytest.raises(LedgerSchemaError, match="names its platform family or one target slice"):
            LedgerRecord.from_mapping(
                {"schema": SCHEMA, "subject": {"kind": kind, "id": "x", "platform": platform, "variant": variant}}
            )
    device = LedgerRecord.from_mapping(
        {"schema": SCHEMA, "subject": {"kind": kind, "id": "x", "platform": "ios", "variant": "arm64-device"}}
    )
    simulator = LedgerRecord.from_mapping(
        {"schema": SCHEMA, "subject": {"kind": kind, "id": "x", "platform": "ios", "variant": "arm64-simulator"}}
    )
    assert device.subject.key != simulator.subject.key
    ipad_run = LedgerRecord.from_mapping(
        {
            "schema": SCHEMA,
            "subject": {"kind": kind, "id": "x", "platform": "ios"},
            "evidence": {"status": "unavailable", "observed": "skipped", "reason": "no device"},
            "provenance": {**AUDIT, "device_class": "iPad Pro (M4)"},
        }
    )
    assert ipad_run.provenance.device_class == "iPad Pro (M4)"


@pytest.mark.parametrize("kind", INVENTORY)
def test_inventory_evidence_says_which_revision_it_is_current_for(kind):
    data = {
        "schema": SCHEMA,
        "subject": {"kind": kind, "id": "x", "platform": "windows"},
        "evidence": {"status": "source-only"},
    }

    with pytest.raises(LedgerSchemaError, match="needs provenance btrc_revision and recorded_at"):
        LedgerRecord.from_mapping(data)
    with pytest.raises(LedgerSchemaError, match="needs provenance recorded_at"):
        LedgerRecord.from_mapping({**data, "provenance": {"btrc_revision": "4e5c982"}})
    assert LedgerRecord.from_mapping({**data, "provenance": AUDIT})


def test_implementation_state_is_recorded_apart_from_qualification():
    def cell(implementation: str, status: str | None):
        data = {
            "schema": SCHEMA,
            "subject": {"kind": "family-cell", "id": "N05", "platform": "windows"},
            "classification": {"implementation": implementation, "links": ["N05", "UI2"]},
        }
        if status is not None:
            data |= {"evidence": {"status": status, "observed": "skipped", "reason": "no runner"}, "provenance": AUDIT}
        return LedgerRecord.from_mapping(data)

    # A missing provider whose runner is unavailable stays missing and unavailable, never unverified.
    both = cell("missing", "unavailable")
    assert both.classification.implementation.value == "missing"
    assert both.evidence.status is EvidenceStatus.UNAVAILABLE
    for implementation in ("missing", "source-only"):
        with pytest.raises(LedgerSchemaError, match=f"implementation is {implementation} cannot be implemented"):
            cell(implementation, "implemented-unverified")
    assert cell("partial", None).classification.implementation.value == "partial"
    assert cell("custom", None).classification.implementation.value == "custom"


def test_the_artifact_variant_keeps_simulator_and_device_results_apart():
    from tools.qualification.report import QualificationReport

    def edit(variant: str, device: str):
        return LedgerRecord.from_mapping(
            {
                "schema": SCHEMA,
                "subject": {"kind": "scenario", "id": "edit", "platform": "ios", "variant": variant},
                "evidence": {"status": "implemented-unverified", "observed": "measured"},
                "measurement": {"metric": "wall-time", "unit": "s", "samples": [14.0]},
                "provenance": {"device_class": device},
            }
        )

    report = QualificationReport([edit("arm64-simulator", "Mac16,1"), edit("arm64-device", "iPhone16,2")])

    assert len(report.rollup.slots) == 2
    assert [(row["variant"], row["slots"]) for row in report.evidence_rows()] == [
        ("arm64-device", 1),
        ("arm64-simulator", 1),
    ]


def test_frontend_in_provenance_must_agree_with_the_slot():
    data = {
        "schema": SCHEMA,
        "subject": {"kind": "ui-case", "id": "E1", "platform": "ios", "frontend": "reference"},
        "provenance": {"frontend": "selfhost"},
    }

    with pytest.raises(LedgerSchemaError, match="disagrees"):
        LedgerRecord.from_mapping(data)


def test_covered_by_may_be_empty_to_mark_an_uncovered_skip():
    record = LedgerRecord.from_mapping(
        _record(evidence={"status": "unavailable", "observed": "skipped", "reason": "no lldb", "covered_by": []})
    )

    assert record.evidence is not None and record.evidence.covered_by == ()
    assert record.to_mapping()["evidence"]["covered_by"] == []


def test_a_p0_inventory_row_loads_from_toml_without_nulls(tmp_path: Path):
    inventory = tmp_path / "inventory.toml"
    inventory.write_text(
        f"""
schema = "{SCHEMA}"

[[records]]
subject = {{ kind = "operation", id = "Library.FileSystem.readText", platform = "windows", group = "FileSystem" }}
classification = {{ parity = "equivalent", owner = "platform-windows", regression = "src/tests/runner.py::test_btrc_file[FileSystemText]" }}
evidence = {{ status = "implemented-unverified" }}
provenance = {{ source = "inventory", btrc_revision = "4e5c982", recorded_at = 2026-09-21T12:00:00Z }}

[[records]]
subject = {{ kind = "journey", id = "library.import-folder", platform = "ios" }}
classification = {{ parity = "adapted", owner = "btrsmith-ios", decision = "D21", note = "document picker instead of a path" }}

[[records]]
[records.subject]
kind = "family-cell"
id = "text-input"
platform = "android"
[records.provenance]
recorded_at = 2026-09-30T12:00:00Z
source = "inventory"
"""
    )

    records = LedgerDocument.load(inventory)

    assert [record.subject.kind for record in records] == [
        SubjectKind.OPERATION,
        SubjectKind.JOURNEY,
        SubjectKind.FAMILY_CELL,
    ]
    assert records[1].evidence is None
    assert records[2].provenance is not None and records[2].provenance.recorded_at == "2026-09-30T12:00:00+00:00"


def test_jsonl_and_json_documents_round_trip_and_name_the_bad_line(tmp_path: Path):
    records = [
        LedgerRecord.from_mapping(_record()),
        LedgerRecord.from_mapping(
            {**_record(), "subject": {"kind": "test", "id": "src/tests/x.py::test_y", "platform": "linux"}}
        ),
    ]
    ledger = tmp_path / "run.jsonl"
    ledger.write_text(LedgerDocument.dumps_jsonl(records))
    document = tmp_path / "run.json"
    document.write_text(json.dumps({"schema": SCHEMA, "records": [record.to_mapping() for record in records]}))

    assert LedgerDocument.load(ledger) == records
    assert LedgerDocument.load(document) == records

    ledger.write_text(ledger.read_text() + '{"schema": "' + SCHEMA + '", "subject": {"kind": "test"}}\n')
    with pytest.raises(LedgerSchemaError, match=r"run\.jsonl:3\.subject\.id: required"):
        LedgerDocument.load(ledger)
    with pytest.raises(LedgerSchemaError, match=r"\.jsonl, \.json or \.toml"):
        LedgerDocument.load(tmp_path / "run.csv")


# --- budget_bench -----------------------------------------------------------


def test_budget_bench_reports_through_the_shared_nearest_rank_statistics():
    from tools.budget_bench import INCREMENTALLY_SAMPLED, REPORTED_SCENARIOS, Scenario

    scenario = Scenario("edit-navigation", samples=[float(value) for value in range(1, 21)])

    assert scenario.summary()["median"] == 10.5
    assert scenario.summary()["p95"] == 19.0
    assert scenario.summary()["max"] == 20.0
    assert Scenario("noop").summary()["p95"] is None
    assert REPORTED_SCENARIOS == (
        "cold-transpile",
        "cold-dev",
        "cold-release",
        "release-whole",
        "release-module",
        "edit-navigation",
        "edit-ui-controller",
        "edit-audio-preparation",
        "instance-edit",
        "interface-edit",
        "noop",
        "touch",
        "memory",
        "workers-1",
        "workers-2",
        "workers-4",
        "workers-8",
        "batch",
        "self-compile",
        "corpus",
    )
    assert set(INCREMENTALLY_SAMPLED) < set(REPORTED_SCENARIOS)


def _bench_summary(samples: list[float]) -> dict:
    summary = SampleStatistics.of(samples)
    return {
        "samples": samples,
        "compile_native": [[sample - 1.0, 1.0] for sample in samples],
        "median": round(summary.median, 3),
        "p95": round(summary.p95, 3),
        "max": round(summary.maximum, 3),
        "notes": [],
    }


QUICK_BENCH = {
    "cold-transpile": _bench_summary(COLD_TRANSPILE),
    "edit-navigation": _bench_summary([9.0 + index / 100 for index in range(20)]),
    "noop": _bench_summary([2.9, 3.0, 2.95]),
    "memory": {
        "samples": [],
        "compile_native": [],
        "median": None,
        "p95": None,
        "max": None,
        "notes": [
            "btrcc --jobs 1 peak footprint 3184183936 bytes (2.966 GiB)",
            "btrcc --jobs 1 instructions retired 1,234,567,890",
            "cold dev build sampled aggregate RSS peak 4000000000 bytes (3.725 GiB)",
        ],
    },
}
# What budget_bench embeds: HostProvenance.detect(workspace=..., compiler=...) plus the compiler that built btrcc.
BENCH_HOST = {key: value for key, value in P6_HOST.items() if key not in {"source", "frontend", "build_mode"}} | {
    "btrsmith_revision": "05ec9cb",
    "jobs": "btrcc default workers; native 8",
}


def _budgets():
    from tools.qualification.schema import Budget

    return {
        "cold-transpile": (Budget(Statistic.MEDIAN, 45.0),),
        "edit-navigation": (Budget(Statistic.MEDIAN, 10.0), Budget(Statistic.P95, 15.0)),
        "noop": (Budget(Statistic.MEDIAN, 5.0),),
        "memory": (Budget(Statistic.MAX, 3.5 * 2**30),),
    }


def _bench_records(budgets=None, report=None, **options):
    from tools.qualification.adapters import BudgetBenchAdapter
    from tools.qualification.schema import Provenance

    adapter = BudgetBenchAdapter(
        Provenance(runner="macos", btrc_revision="65057cb"),
        budgets=budgets,
        recorded_at="2026-09-24T10:00:00+00:00",
        **options,
    )
    return adapter.records(QUICK_BENCH if report is None else report)


def test_the_bench_adapter_counts_against_every_declared_scenario():
    from tools.budget_bench import REPORTED_SCENARIOS

    records = {record.subject.id: record for record in _bench_records()}

    assert tuple(records) == REPORTED_SCENARIOS
    assert records["cold-dev"].evidence is None
    # No budget, and the ingesting command knew nothing of the measured host: nothing passes.
    assert {record.evidence.status for record in records.values() if record.evidence} == {
        EvidenceStatus.IMPLEMENTED_UNVERIFIED
    }
    assert records["cold-transpile"].evidence.reason.startswith("no budget declared; provenance lacks os_build")
    assert records["edit-navigation"].measurement.components["native"] == (1.0,) * 20
    noop = records["noop"]
    assert noop.evidence.reason.startswith("3 of 20 required samples; no budget declared")
    memory = records["memory"].measurement
    assert (memory.metric, memory.unit, memory.samples) == ("peak-footprint", "bytes", (3184183936,))
    assert memory.components == {"aggregate-rss": (4000000000,), "instructions-retired": (1234567890,)}
    provenance = records["memory"].provenance
    assert (provenance.source, provenance.build_mode, provenance.frontend) == ("budget_bench", "debug", "selfhost")
    assert provenance.recorded_at == "2026-09-24T10:00:00+00:00"


def test_bench_budgets_and_the_embedded_host_decide_between_passed_and_unverified():
    from tools.qualification.schema import Budget

    report = {"provenance": BENCH_HOST, "scenarios": QUICK_BENCH}
    records = {record.subject.id: record for record in _bench_records(_budgets(), report)}

    assert records["cold-transpile"].evidence.status is EvidenceStatus.PASSED
    assert records["edit-navigation"].evidence.status is EvidenceStatus.PASSED
    assert records["memory"].evidence.status is EvidenceStatus.PASSED
    assert records["noop"].evidence.reason == "3 of 20 required samples"
    provenance = records["cold-transpile"].provenance
    # The run's own host wins over the ingesting command's checkout.
    assert (provenance.btrsmith_revision, provenance.cpu, provenance.memory) == ("05ec9cb", "8P+2E", "64 GiB")
    assert provenance.compiler_digest == BENCH_HOST["compiler_digest"]
    tight = {"edit-navigation": (Budget(Statistic.MEDIAN, 10.0), Budget(Statistic.P95, 9.1))}
    evidence = {record.subject.id: record for record in _bench_records(tight, report)}["edit-navigation"].evidence
    assert evidence.status is EvidenceStatus.IMPLEMENTED_UNVERIFIED
    assert evidence.reason == "p95 9.18 exceeds 9.1 s"


def test_explicit_flags_override_the_embedded_host_but_never_relabel_its_frontend():
    from tools.qualification.schema import Frontend, Provenance

    report = {"provenance": {**BENCH_HOST, "frontend": "selfhost"}, "scenarios": QUICK_BENCH}
    records = _bench_records(report=report, explicit=Provenance(runner="macos-quiet", btrsmith_revision="429d2e0"))
    assert {(record.provenance.runner, record.provenance.btrsmith_revision) for record in records} == {
        ("macos-quiet", "429d2e0")
    }

    with pytest.raises(LedgerSchemaError, match="measured the selfhost frontend, not reference"):
        _bench_records(report=report, explicit=Provenance(frontend=Frontend.REFERENCE))
    reference = _bench_records(explicit=Provenance(frontend=Frontend.REFERENCE))
    assert {(record.subject.frontend, record.provenance.frontend) for record in reference} == {
        (Frontend.REFERENCE, Frontend.REFERENCE)
    }


def test_failed_samples_and_rebuilt_units_reach_the_ledger():
    from tools.qualification.report import QualificationReport

    edits = _bench_summary([9.0 + index / 100 for index in range(18)])
    edits |= {
        "failures": 2,
        "failure_reasons": ["btrcc failed (1):\nerror: x", "incremental build differs from a clean build"],
        "rebuilt_units": [1] * 17 + [3],
    }
    report = {"provenance": BENCH_HOST, "scenarios": {"edit-navigation": edits}}

    record = next(record for record in _bench_records(_budgets(), report) if record.subject.id == "edit-navigation")

    assert record.measurement.failures == 2
    assert record.measurement.components["rebuilt-units"] == (1,) * 17 + (3,)
    assert record.evidence.status is EvidenceStatus.IMPLEMENTED_UNVERIFIED
    assert record.evidence.reason == (
        "2 failed sample(s); 18 of 20 required samples; btrcc failed (1):; incremental build differs from a clean build"
    )
    row = next(row for row in QualificationReport([record]).evidence_rows())
    assert row["failed"] == 1
    every_sample_failed = {"samples": [], "compile_native": [], "failures": 3, "notes": []}
    record = next(
        record for record in _bench_records(report={"noop": every_sample_failed}) if record.subject.id == "noop"
    )
    assert (record.evidence.status, record.measurement.failures) == (EvidenceStatus.IMPLEMENTED_UNVERIFIED, 3)
    with pytest.raises(LedgerSchemaError, match="rebuilt_units: expected one count per sample"):
        _bench_records(report={"noop": {**_bench_summary([1.0, 2.0]), "rebuilt_units": [1]}})
    with pytest.raises(LedgerSchemaError, match="3 reasons for 1 failures"):
        _bench_records(report={"noop": {**_bench_summary([1.0]), "failures": 1, "failure_reasons": ["a", "b", "c"]}})


def test_host_provenance_names_the_topology_memory_compiler_and_checkouts(tmp_path: Path):
    import platform as host_platform
    import re

    from tools.qualification.adapters import REPO, HostProvenance

    assert HostProvenance.cpu("8", "2", "10") == "8P+2E"
    assert HostProvenance.cpu(None, None, "10") == "10 cores"
    assert HostProvenance.memory(str(64 * 2**30)) == "64 GiB"
    assert HostProvenance.memory(str(65842312 * 1024)) == "62.8 GiB"
    assert HostProvenance.memory("unknown") is None
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal:       65842312 kB\nMemFree:        1 kB\n")
    assert HostProvenance.meminfo_bytes(meminfo) == str(65842312 * 1024)
    btrcc = tmp_path / "btrcc"
    btrcc.write_bytes(b"\x7fELF measured compiler")
    head = HostProvenance._run(["git", "rev-parse", "HEAD"], cwd=REPO)

    detected = HostProvenance().detect(workspace=REPO, compiler=btrcc, c_compiler="clang 19 -O2", jobs="1")

    assert detected.compiler_digest == "sha256:" + hashlib.sha256(btrcc.read_bytes()).hexdigest()
    assert detected.btrsmith_revision == head
    assert (detected.c_compiler, detected.jobs) == ("clang 19 -O2", "1")
    assert detected.memory is not None and detected.memory.endswith(" GiB")
    if host_platform.system() == "Darwin":
        assert re.fullmatch(r"\d+P\+\d+E|\d+ cores", detected.cpu)
    version = HostProvenance().c_compiler(sys.executable, "-O2")
    assert version is not None and version.startswith("Python ") and version.endswith(" -O2")


def test_the_bench_adapter_rejects_reports_it_cannot_vouch_for():
    from tools.qualification.adapters import BudgetBenchAdapter
    from tools.qualification.schema import Provenance

    adapter = BudgetBenchAdapter(Provenance())
    with pytest.raises(LedgerSchemaError, match="workers-3 are not scenarios budget_bench reports"):
        adapter.records({"workers-3": _bench_summary([1.0])})
    with pytest.raises(LedgerSchemaError, match="unknown field"):
        adapter.records({"scenarios": {}, "host": {}})
    with pytest.raises(LedgerSchemaError, match=r"provenance\.recorded_at: must carry a UTC offset"):
        adapter.records({"provenance": {"recorded_at": "2026-09-24T10:00:00"}, "scenarios": {}})
    tampered = {"noop": {**_bench_summary([1.0, 2.0, 3.0]), "p95": 2.0}}
    with pytest.raises(LedgerSchemaError, match=r"noop\.p95: reported 2\.0, its samples give 3\.000"):
        adapter.records(tampered)


def _schema_two_report(**changes) -> dict:
    """A report as tools.budget_bench writes it (schema 2), from the bench's own Scenario summaries."""

    from tools.budget_bench import Scenario

    edits = Scenario("edit-navigation")
    for index in range(20):
        edits.add(9.0 + index / 100, compile_s=8.0, native_s=1.0 + index / 100, metrics={"native_compiled_units": 1})
    interface = Scenario("interface-edit")
    for index in range(5):
        interface.add(20.0 + index, compile_s=18.0 + index, native_s=2.0, metrics={"ratio_to_clean": 0.5})
    through_make = Scenario("cold-dev")
    for index in range(5):
        through_make.add(60.0 + index)
    memory = Scenario("memory")
    memory.facts.update(
        compile_s=41.2,
        compiler_max_rss_bytes=3184183936,
        compiler_peak_footprint_bytes=3100000000,
        compiler_instructions_retired=1234567890,
        build_tree_rss_bytes=4000000000,
    )
    memory.note("selfhost module-unit compile --jobs 1 peak 3100000000 bytes (2.887 GiB)")
    report = {
        "schema": 2,
        "tool": "tools/budget_bench.py",
        "dry_run": False,
        "started": "2026-10-01T08:00:00+00:00",
        "finished": "2026-10-01T09:30:00+00:00",
        "failure": None,
        "configuration": {"frontend": "selfhost", "mode": "dev", "units": "module", "entry": "direct"},
        "provenance": {
            "compiler_revision": "65057cb",
            "compiler_dirty": False,
            "host": {"system": "Darwin", "node": "private-host-name", "release": "27.0.0", "machine": "arm64"},
            "cpu_count": 10,
            "environment": {"BTRC_NATIVE_TARGET": "arm64-apple-macosx15.0"},
            "btrcc": {"path": "/Users/someone/btrcc", "sha256": "0" * 64, "bytes": 20700000},
        },
        "scenarios": {scenario.name: scenario.summary() for scenario in (through_make, edits, interface, memory)},
    }
    report.update(changes)
    return report


def test_the_bench_adapter_reads_the_schema_two_report_budget_bench_writes():
    from tools.budget_bench import REPORTED_SCENARIOS
    from tools.qualification.schema import Budget, Provenance

    host = Provenance(**{name: P6_HOST[name] for name in ("os_build", "device_class", "cpu", "memory", "c_compiler")})
    budgets = {"edit-navigation": (Budget(Statistic.MEDIAN, 10.0),), "interface-edit": (Budget(Statistic.MAX, 30.0),)}
    records = {record.subject.id: record for record in _bench_records(budgets, _schema_two_report(), explicit=host)}

    assert tuple(records) == REPORTED_SCENARIOS
    provenance = records["edit-navigation"].provenance
    assert (provenance.btrc_revision, provenance.frontend.value, provenance.build_mode) == (
        "65057cb",
        "selfhost",
        "debug",
    )
    assert provenance.compiler_digest == "sha256:" + "0" * 64
    assert provenance.target_triple == "arm64-apple-macosx15.0"
    assert provenance.recorded_at == "2026-10-01T09:30:00+00:00"
    assert "private-host-name" not in json.dumps(provenance.to_mapping())
    assert records["edit-navigation"].evidence.status is EvidenceStatus.PASSED
    assert records["edit-navigation"].measurement.components["native"][0] == 1.0
    # Interface edits take --cold-samples, so five are enough.
    assert records["interface-edit"].evidence.status is EvidenceStatus.PASSED
    assert records["interface-edit"].measurement.minimum_samples == 5
    # A build through BTRSmith's make has no compile/native split.
    assert records["cold-dev"].measurement.components == {}
    memory = records["memory"].measurement
    assert (memory.metric, memory.samples) == ("peak-footprint", (3100000000,))
    assert memory.components == {"aggregate-rss": (4000000000,), "instructions-retired": (1234567890,)}
    assert records["batch"].evidence is None


def test_a_failed_or_dry_bench_run_is_never_accepted():
    from tools.qualification.adapters import BudgetBenchAdapter
    from tools.qualification.schema import Budget, Provenance

    host = Provenance(**{name: P6_HOST[name] for name in ("os_build", "device_class", "cpu", "memory", "c_compiler")})
    budgets = {"edit-navigation": (Budget(Statistic.MEDIAN, 10.0),)}
    failed = _schema_two_report(failure="noop: incremental build differs from a clean build\ndetail")
    evidence = {r.subject.id: r for r in _bench_records(budgets, failed, explicit=host)}["edit-navigation"].evidence
    assert evidence.status is EvidenceStatus.IMPLEMENTED_UNVERIFIED
    assert evidence.reason == "the run failed: noop: incremental build differs from a clean build"
    dry = _schema_two_report(dry_run=True)
    evidence = {r.subject.id: r for r in _bench_records(budgets, dry, explicit=host)}["edit-navigation"].evidence
    assert (evidence.status, evidence.reason) == (EvidenceStatus.IMPLEMENTED_UNVERIFIED, "a dry run")
    stand_in = _schema_two_report()
    stand_in["configuration"] = {**stand_in["configuration"], "stand_in": True}
    evidence = {r.subject.id: r for r in _bench_records(budgets, stand_in, explicit=host)}["edit-navigation"].evidence
    assert (evidence.status, evidence.reason) == (
        EvidenceStatus.IMPLEMENTED_UNVERIFIED,
        "a stand-in workspace, not BTRSmith",
    )

    adapter = BudgetBenchAdapter(Provenance())
    with pytest.raises(LedgerSchemaError, match="schema: 3 is not 2"):
        adapter.records(_schema_two_report(schema=3))
    with pytest.raises(LedgerSchemaError, match="unknown field"):
        adapter.records(_schema_two_report(host={}))
    with pytest.raises(LedgerSchemaError, match="workers-3 are not scenarios budget_bench reports"):
        adapter.records(_schema_two_report(scenarios={"workers-3": _bench_summary([1.0])}))


# --- JUnit, skip reports and boundary reports ------------------------------

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites name="pytest tests"><testsuite name="pytest" errors="1" failures="1" skipped="2" tests="6"
 timestamp="2026-10-01T00:14:56.482277-07:00">
<testcase classname="src.tests.python.test_qualification_ledger" name="test_a" />
<testcase classname="src.tests.python.test_qualification_ledger.TestGroup" name="test_b[x-1]" />
<testcase classname="src.tests.python.test_qualification_ledger" name="test_c"><failure message="assert 1 == 2" /></testcase>
<testcase classname="src.tests.python.test_qualification_ledger" name="test_d"><error message="fixture failed" /></testcase>
<testcase classname="src.tests.python.test_qualification_ledger" name="test_e">
 <skipped type="pytest.skip" message="needs lldb">src/tests/x.py:1: needs lldb</skipped></testcase>
<testcase classname="src.tests.python.test_qualification_ledger" name="test_f">
 <skipped type="pytest.xfail" message="known defect" /></testcase>
<testcase classname="no.such.module" name="test_g" />
</testsuite></testsuites>
"""


def _junit_records(tmp_path: Path):
    from tools.qualification.adapters import JUnitAdapter
    from tools.qualification.schema import Platform, Provenance

    path = tmp_path / "junit.xml"
    path.write_text(JUNIT)
    return JUnitAdapter(Provenance(runner="macos"), platform=Platform.MACOS).records(path, "raw/junit.xml")


def test_junit_cases_become_test_slots_keyed_by_node_id(tmp_path: Path):
    records = {record.subject.id: record for record in _junit_records(tmp_path)}
    module = "src/tests/python/test_qualification_ledger.py"

    assert set(records) == {
        f"{module}::test_a",
        f"{module}::TestGroup::test_b[x-1]",
        f"{module}::test_c",
        f"{module}::test_d",
        f"{module}::test_e",
        f"{module}::test_f",
        "no.such.module::test_g",
    }
    outcomes = {nodeid: (record.evidence.status.value, record.evidence.observed) for nodeid, record in records.items()}
    assert outcomes[f"{module}::test_a"] == ("passed", "passed")
    assert outcomes[f"{module}::test_c"] == ("implemented-unverified", "failed")
    assert outcomes[f"{module}::test_d"] == ("implemented-unverified", "error")
    assert outcomes[f"{module}::test_e"] == ("unavailable", "skipped")
    assert outcomes[f"{module}::test_f"] == ("implemented-unverified", "xfailed")
    assert records[f"{module}::test_e"].evidence.reason == "needs lldb"
    assert records[f"{module}::test_a"].provenance.recorded_at == "2026-10-01T00:14:56-07:00"
    assert records[f"{module}::test_a"].subject.group == module


def test_a_skip_report_becomes_test_slots_with_their_coverage():
    from tools.qualification.adapters import SkipReportAdapter
    from tools.qualification.schema import Provenance

    report = {
        "schema": "btrc.skip-report/1",
        "runner": "macos",
        "revision": "cd29c43",
        "finished_at": "2026-10-01T08:00:00+00:00",
        "host": {"system": "Darwin", "release": "27.0.0"},
        "tests": {"a.py::t1": "passed", "a.py::t2": "skipped", "a.py::t3": "skipped", "a.py::t4": "failed"},
        "skips": [
            {
                "nodeid": "a.py::t2",
                "reason": "requires /dev/full",
                "expected": True,
                "covered_by": ["linux-devcontainer"],
            },
            {"nodeid": "a.py::t3", "reason": "surprise", "expected": False, "covered_by": None},
        ],
    }

    records = {record.subject.id: record for record in SkipReportAdapter(Provenance()).records(report)}

    assert records["a.py::t2"].evidence.covered_by == ("linux-devcontainer",)
    assert records["a.py::t3"].evidence.covered_by is None
    assert records["a.py::t3"].evidence.reason == "unexpected skip: surprise"
    assert records["a.py::t4"].evidence.status is EvidenceStatus.IMPLEMENTED_UNVERIFIED
    provenance = records["a.py::t1"].provenance
    assert (provenance.source, provenance.runner, provenance.btrc_revision) == ("skip-report", "macos", "cd29c43")
    assert provenance.os_build == "Darwin 27.0.0"
    assert records["a.py::t1"].subject.platform.value == "macos"


def _boundary_report(tmp_path: Path) -> dict:
    from types import SimpleNamespace

    from tools.compiler_codegen.main import CompilerCodegenCommand

    records = [
        SimpleNamespace(id=f"{fixture}.{capability}.{channel}", fixture=fixture, capability=capability)
        for fixture in ("arith", "strings")
        for capability in ("python.c", "observed.gcc")
        for channel in ("bytes", "observation")
    ]
    check = SimpleNamespace(checked_records=6, skipped_capabilities=("observed.gcc@strings",))
    path = tmp_path / "boundary-report.json"
    CompilerCodegenCommand._write_boundary_report(path, SimpleNamespace(records=records), check)
    return json.loads(path.read_text())


def test_the_boundary_report_records_the_delta_this_host_did_not_check(tmp_path: Path):
    from tools.qualification.adapters import BoundaryReportAdapter
    from tools.qualification.report import QualificationReport
    from tools.qualification.schema import Platform, Provenance

    report = _boundary_report(tmp_path)

    assert (report["total_records"], report["checked_records"]) == (8, 6)
    assert [record["id"] for record in report["records"] if not record["checked"]] == [
        "strings.observed.gcc.bytes",
        "strings.observed.gcc.observation",
    ]
    records = BoundaryReportAdapter(Provenance(), platform=Platform.MACOS).records(report)
    rows = QualificationReport(records).evidence_rows()
    assert rows == [
        {
            "kind": "boundary-record",
            "platform": "macos",
            "frontend": None,
            "variant": None,
            "slots": 8,
            "passed": 6,
            "implemented-unverified": 0,
            "source-only": 0,
            "unavailable": 2,
            "unrecorded": 0,
            "failed": 0,
        }
    ]
    with pytest.raises(LedgerSchemaError, match="disagree"):
        BoundaryReportAdapter(Provenance(), platform=Platform.MACOS).records({**report, "checked_records": 7})


# --- the report -------------------------------------------------------------


def test_the_report_renders_four_outcome_counts_with_stable_denominators(tmp_path: Path):
    from tools.qualification.report import QualificationReport

    bench = _bench_records(_budgets(), {"provenance": BENCH_HOST, "scenarios": QUICK_BENCH})
    report = QualificationReport([*bench, *_junit_records(tmp_path)])
    rows = {row["kind"]: row for row in report.evidence_rows()}

    assert rows["scenario"] == {
        "kind": "scenario",
        "platform": "macos",
        "frontend": "selfhost",
        "variant": None,
        "slots": 20,
        "passed": 3,
        "implemented-unverified": 1,
        "source-only": 0,
        "unavailable": 0,
        "unrecorded": 16,
        "failed": 0,
    }
    assert rows["test"]["slots"] == 7
    assert (rows["test"]["passed"], rows["test"]["implemented-unverified"], rows["test"]["unavailable"]) == (3, 3, 1)
    assert rows["test"]["failed"] == 2
    markdown = report.render_markdown()
    assert (
        "| kind | platform | frontend | variant | slots | passed | implemented-unverified | source-only | unavailable |"
        in markdown
    )
    assert "| scenario | macos | selfhost | - | 20 | 3 | 1 | 0 | 0 | 16 | 0 |" in markdown
    assert (
        "| edit-navigation | macos | selfhost | - | wall-time | s | 20 | 9.095 | 9.180 | 9.190 | 9.190 | 9.190 | 0 "
        "| passed | - | compile 8.095; native 1.000 | P1 |" in markdown
    )
    assert "| memory | macos | selfhost | - | peak-footprint | bytes | 1 | 3184183936 |" in markdown
    assert "instructions-retired 1234567890" in markdown
    assert json.loads(report.render_json())["slots"] == 27


def test_every_measurement_names_the_host_that_measured_it():
    from tools.qualification.report import QualificationReport
    from tools.qualification.schema import Provenance

    bench = _bench_records(
        _budgets(),
        {"provenance": BENCH_HOST, "scenarios": QUICK_BENCH},
        explicit=Provenance(sdk_build="MacOSX27.0.sdk (25A5)", device_id="quiet-mac", scale="BTRSmith 05ec9cb"),
    )
    report = QualificationReport(bench)

    measured = {row["id"]: row for row in report.measurement_rows()}
    host = measured["cold-transpile"]["provenance"]
    assert (host["cpu"], host["memory"], host["c_compiler"]) == ("8P+2E", "64 GiB", P6_HOST["c_compiler"])
    assert (host["sdk_build"], host["frontend"], host["device_id"], host["scale"]) == (
        "MacOSX27.0.sdk (25A5)",
        "selfhost",
        "quiet-mac",
        "BTRSmith 05ec9cb",
    )
    assert measured["edit-navigation"]["components"] == {"compile": pytest.approx(8.095), "native": 1.0}
    markdown = report.render_markdown()
    header = next(line for line in markdown.splitlines() if line.startswith("| host | source |"))
    for column in ("sdk build", "frontend", "device id", "scale", "cpu", "memory", "c compiler", "compiler digest"):
        assert f"| {column} |" in header
    assert "| P1 | budget_bench |" in markdown
    assert "MacOSX27.0.sdk (25A5)" in markdown and "quiet-mac" in markdown


def _inventory_row(kind: str, identifier: str, platform: str, **sections) -> LedgerRecord:
    return LedgerRecord.from_mapping(
        {"schema": SCHEMA, "subject": {"kind": kind, "id": identifier, "platform": platform}, **sections}
    )


def test_p0_rows_take_their_evidence_from_their_regression_tests(tmp_path: Path):
    from tools.qualification.report import QualificationReport

    module = "src/tests/python/test_qualification_ledger.py"
    junit = _junit_records(tmp_path)  # macos: test_a passed, test_c failed, test_e skipped
    ipad = LedgerRecord.from_mapping(
        {
            "schema": SCHEMA,
            "subject": {"kind": "test", "id": f"{module}::test_ios", "platform": "ipados", "variant": "arm64-device"},
            "evidence": {"status": "passed", "observed": "passed"},
        }
    )
    owner = {"parity": "equivalent", "owner": "platform"}
    inventory = [
        # Hand-entered as source-only, but its regression passes: derived passed, and it disagrees.
        _inventory_row(
            "operation",
            "Library.FileSystem.readText",
            "macos",
            classification={**owner, "regression": f"{module}::test_a"},
            evidence={"status": "source-only"},
            provenance=AUDIT,
        ),
        # One of two regressions failed.
        _inventory_row(
            "operation",
            "Library.FileSystem.writeText",
            "macos",
            classification={
                **owner,
                "regression": [
                    f"{module}::test_a",
                    f"{module}::test_c",
                ],
            },
        ),
        # Skipped regression: unavailable, not passed.
        _inventory_row(
            "journey", "library.import-folder", "macos", classification={**owner, "regression": f"{module}::test_e"}
        ),
        # An iPad run counts for the iOS/iPadOS family.
        _inventory_row(
            "operation",
            "Library.FileSystem.readText",
            "ios",
            classification={**owner, "regression": f"{module}::test_ios"},
        ),
        # Never run anywhere in this ledger: no current status, and no parity either.
        _inventory_row(
            "operation",
            "Library.Tray.show",
            "macos",
            classification={"owner": "platform", "regression": f"{module}::test_z"},
        ),
    ]

    report = QualificationReport([*inventory, *junit, ipad])
    slots = report.rollup.slots

    def current(kind, identifier, platform):
        return slots[(kind, identifier, platform, "", "")].current

    assert current("operation", "Library.FileSystem.readText", "macos").status is EvidenceStatus.PASSED
    written = current("operation", "Library.FileSystem.writeText", "macos")
    assert (written.status, written.observed) == (EvidenceStatus.IMPLEMENTED_UNVERIFIED, "failed")
    assert written.reason == f"{module}::test_c: failed"
    assert current("journey", "library.import-folder", "macos").status is EvidenceStatus.UNAVAILABLE
    assert current("operation", "Library.FileSystem.readText", "ios").status is EvidenceStatus.PASSED
    assert current("operation", "Library.Tray.show", "macos") is None
    completeness = {(row["kind"], row["platform"]): row for row in report.completeness_rows()}
    assert completeness[("operation", "macos")] == {
        "kind": "operation",
        "platform": "macos",
        "frontend": None,
        "variant": None,
        "rows": 3,
        "without_parity": 1,
        "without_owner": 0,
        "without_regression": 0,
        "without_status": 1,
        "disagrees": 1,
    }
    markdown = report.render_markdown()
    assert "| kind | platform | frontend | variant | rows | without parity | without owner |" in markdown


def test_ui_catalog_and_p0_rows_roll_up_against_the_frozen_denominators():
    from tools.qualification.denominators import DenominatorManifest
    from tools.qualification.report import QualificationReport

    manifest = DenominatorManifest.load()
    frozen = manifest.by_kind()
    rows = []
    for denominator in manifest.denominators:
        for identifier in denominator.ids:
            for platform, variant in denominator.targets():
                for frontend in denominator.frontends or (None,):
                    subject = {"kind": denominator.kind.value, "id": identifier, "platform": platform.value}
                    if variant is not None:
                        subject["variant"] = variant
                    if frontend is not None:
                        subject["frontend"] = frontend.value
                    rows.append({"schema": SCHEMA, "subject": subject})
    # The source inventory's P/C/M classification of one family on its five platforms.
    rows += [
        {
            "schema": SCHEMA,
            "subject": {"kind": "family-cell", "id": "N25", "platform": platform},
            "classification": {"implementation": state, "links": ["N25", "UI5"]},
        }
        for platform, state in zip(
            ("macos", "linux", "windows", "ios", "android"), ("partial", "custom", "missing", "missing", "missing")
        )
    ]
    records = [LedgerRecord.from_mapping(row) for row in rows]

    report = QualificationReport(records, manifest)
    evidence = report.evidence_rows()

    assert {kind: denominator.frozen_slots for kind, denominator in frozen.items()} == {
        SubjectKind.FAMILY_CELL: 300,
        SubjectKind.UI_OPERATION: 1620,
        SubjectKind.UI_CASE: 470,
        SubjectKind.OPERATION: 1938,
    }
    assert sum(row["slots"] for row in evidence if row["kind"] == "operation") == 1938
    assert sum(row["slots"] for row in evidence if row["kind"] == "ui-operation") == 1620
    assert sum(row["slots"] for row in evidence if row["kind"] == "ui-case") == 470
    assert sum(row["slots"] for row in evidence if row["kind"] == "family-cell") == 300
    assert all(row["unrecorded"] == row["slots"] for row in evidence)
    assert report.problems() == []
    assert [(row["kind"], row["missing_slots"], row["undeclared"]) for row in report.denominator_rows()] == [
        ("family-cell", 0, 0),
        ("ui-operation", 0, 0),
        ("ui-case", 0, 0),
        ("operation", 0, 0),
    ]
    implementation = {row["platform"]: row for row in report.implementation_rows()}
    assert (implementation["macos"]["partial"], implementation["linux"]["custom"]) == (1, 1)
    assert implementation["windows"]["missing"] == 1 and implementation["windows"]["unclassified"] == 59
    assert "## Implementation state" in report.render_markdown()

    # Deleting one row does not shrink the denominator: it is a missing slot, and the report fails.
    dropped = [record for record in records if record.subject.key != ("ui-case", "E03", "ios", "selfhost", "")]
    problems = QualificationReport(dropped, manifest).problems()
    assert problems == ["ui-case: 1 of 470 declared slots have no record (e.g. E03 ios selfhost)"]
    stray = _inventory_row("ui-case", "E48", "ios")
    assert QualificationReport([*records, stray], manifest).problems() == [
        "ui-case: 1 slots are outside release ui0-source-inventory-2026-09-21"
    ]


def test_the_tracked_denominators_match_their_sources():
    from tools.qualification.denominators import DenominatorManifest

    manifest = DenominatorManifest.load()

    assert manifest.drift() == []
    counts = {
        denominator.kind.value: (len(denominator.ids), denominator.frozen_slots)
        for denominator in manifest.denominators
    }
    assert counts == {
        "family-cell": (60, 300),
        "ui-operation": (162, 1620),
        "ui-case": (47, 470),
        "operation": (323, 1938),
    }
    ids = manifest.by_kind()[SubjectKind.UI_CASE].ids
    assert (ids[0], ids[-1], len(set(ids))) == ("E01", "E47", 47)


def _frozen_copy(tmp_path: Path, *, drop: str | None = None, rewrite=None) -> Path:
    """The tracked manifest re-rooted at `tmp_path`, with one source row dropped or a frozen value edited."""

    from tools.qualification.denominators import MANIFEST, REPO

    documents = ("docs/design/native-ui-parity.md", "docs/design/native-ui-api-inventory.md")
    for document in (*documents, "docs/design/platform-inventory.toml"):
        text = (REPO / document).read_text(encoding="utf-8")
        if drop is not None:
            text = "\n".join(line for line in text.splitlines() if not line.startswith(drop))
        (tmp_path / document).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / document).write_text(text, encoding="utf-8")
    manifest = MANIFEST.read_text(encoding="utf-8")
    if rewrite is not None:
        manifest = rewrite(manifest)
    path = tmp_path / "denominators.toml"
    path.write_text(manifest, encoding="utf-8")
    return path


def test_a_shrunken_source_or_a_lowered_freeze_fails_the_denominator_check(tmp_path: Path, capsys):
    from tools.qualification.cli import QualificationCommand
    from tools.qualification.denominators import DenominatorManifest

    copy = _frozen_copy(tmp_path)
    assert DenominatorManifest.load(copy, repo=tmp_path).drift() == []

    shrunk = _frozen_copy(tmp_path, drop="| E47 —")
    assert DenominatorManifest.load(shrunk, repo=tmp_path).drift() == [
        "ui-case denominator (release ui0-source-inventory-2026-09-21): its source yields 46 ids, frozen at 47"
    ]
    lowered = _frozen_copy(
        tmp_path, rewrite=lambda text: text.replace("ids = 47\nslots = 470", "ids = 46\nslots = 460")
    )
    assert "its source yields 47 ids, frozen at 46" in DenominatorManifest.load(lowered, repo=tmp_path).drift()[0]
    renamed = _frozen_copy(tmp_path)
    document = tmp_path / "docs/design/native-ui-parity.md"
    document.write_text(document.read_text(encoding="utf-8").replace("| E47 —", "| E48 —"), encoding="utf-8")
    assert "different ids than the frozen sha256" in DenominatorManifest.load(renamed, repo=tmp_path).drift()[0]
    miscounted = _frozen_copy(tmp_path, rewrite=lambda text: text.replace("slots = 470", "slots = 47"))
    assert (
        "slots = 47, but ids x platforms x frontends = 470"
        in DenominatorManifest.load(miscounted, repo=tmp_path).drift()[0]
    )

    assert QualificationCommand().run(["denominators"]) == 0
    assert "ui-case: 47 ids from docs/design/native-ui-parity.md" in capsys.readouterr().out


def test_a_p0_denominator_freezes_from_its_checked_inventory_ledger(tmp_path: Path):
    from tools.qualification.denominators import Denominator, DenominatorManifest

    rows = [
        f'''[[records]]
subject = {{ kind = "operation", id = "{identifier}", platform = "{platform}" }}
classification = {{ parity = "equivalent", owner = "platform-{platform}" }}
'''
        for identifier in ("Library.FileSystem.readText", "Library.FileSystem.writeText", "Library.Tray.show")
        for platform in ("windows", "ios", "android")
    ]
    ledger = tmp_path / "p0-inventory.toml"
    ledger.write_text(f'schema = "{SCHEMA}"\n\n' + "\n".join(rows), encoding="utf-8")
    digest = Denominator.digest(["Library.FileSystem.readText", "Library.FileSystem.writeText", "Library.Tray.show"])
    manifest = tmp_path / "denominators.toml"
    manifest.write_text(
        f'''schema = "btrc.qualification.denominators/1"

[[denominators]]
kind = "operation"
release = "p0-test"
platforms = ["windows", "ios", "android"]
frontends = []
ids = 3
slots = 9
sha256 = "{digest}"
source = {{ ledger = "p0-inventory.toml" }}
''',
        encoding="utf-8",
    )

    assert DenominatorManifest.load(manifest, repo=tmp_path).drift() == []
    ledger.write_text(ledger.read_text().replace("Library.Tray.show", "Library.FileSystem.readText"))
    assert DenominatorManifest.load(manifest, repo=tmp_path).drift() == [
        "operation denominator (release p0-test): its source yields 2 ids, frozen at 3"
    ]
    with pytest.raises(LedgerSchemaError, match="iOS/iPadOS is one family"):
        manifest.write_text(manifest.read_text().replace('"ios", "android"', '"ipados", "android"'))
        DenominatorManifest.load(manifest, repo=tmp_path)


def test_a_sliced_p0_denominator_declares_each_id_once_per_target_slice(tmp_path: Path):
    from tools.qualification.denominators import Denominator, DenominatorManifest
    from tools.qualification.report import QualificationReport
    from tools.qualification.schema import TARGET_SLICES

    rows = [
        f'''[[records]]
subject = {{ kind = "operation", id = "{identifier}", platform = "{platform}", variant = "{variant}" }}
classification = {{ parity = "{"os-restricted" if name.startswith("ios") else "equivalent"}" }}
'''
        for identifier in ("Library.Process", "Library.Vector")
        for name, (platform, variant) in TARGET_SLICES.items()
    ]
    ledger = tmp_path / "p0-inventory.toml"
    ledger.write_text(f'schema = "{SCHEMA}"\n\n' + "\n".join(rows), encoding="utf-8")
    slices = ", ".join(f'"{name}"' for name in TARGET_SLICES)
    manifest = tmp_path / "denominators.toml"
    manifest.write_text(
        f'''schema = "btrc.qualification.denominators/1"

[[denominators]]
kind = "operation"
release = "p0-test"
platforms = ["windows", "ios", "android"]
slices = [{slices}]
frontends = []
ids = 2
slots = 12
sha256 = "{Denominator.digest(["Library.Process", "Library.Vector"])}"
source = {{ ledger = "p0-inventory.toml" }}
''',
        encoding="utf-8",
    )

    loaded = DenominatorManifest.load(manifest, repo=tmp_path)
    assert loaded.drift() == []
    assert ("operation", "Library.Process", "ios", "", "arm64-simulator") in loaded.denominators[0].slot_keys()
    report = QualificationReport(LedgerDocument.load(ledger), loaded)
    assert report.problems() == []
    parity = {(row["platform"], row["variant"]): row for row in report.parity_rows()}
    assert len(parity) == 6
    assert parity[("ios", "arm64-device")]["os-restricted"] == 2
    assert parity[("android", "x86_64")]["equivalent"] == 2

    # Every slice is its own slot: a ledger that drops the simulator is short two slots.
    ledger.write_text("\n\n".join(row for row in ledger.read_text().split("\n\n") if "arm64-simulator" not in row))
    assert QualificationReport(LedgerDocument.load(ledger), loaded).problems() == [
        "operation: 2 of 12 declared slots have no record (e.g. Library.Process ios arm64-simulator, "
        "Library.Vector ios arm64-simulator)"
    ]
    miscounted = manifest.read_text().replace("slots = 12", "slots = 6")
    manifest.write_text(miscounted)
    assert "ids x slices x frontends = 12" in DenominatorManifest.load(manifest, repo=tmp_path).drift()[0]
    for edit, message in (
        ('"android-x86_64"]', "is not one of"),
        ('platforms = ["windows", "ios", "android"]', "the slices' families in slice order"),
    ):
        broken = miscounted.replace(
            edit, '"android-x86"]' if edit.startswith('"android') else 'platforms = ["windows", "android", "ios"]'
        )
        manifest.write_text(broken)
        with pytest.raises(LedgerSchemaError, match=message):
            DenominatorManifest.load(manifest, repo=tmp_path)


def test_inventory_rows_expand_to_one_record_per_slice_cell(tmp_path: Path):
    ledger = tmp_path / "inventory.toml"
    ledger.write_text(
        f'''schema = "{SCHEMA}"
provenance = {{ recorded_at = "2026-10-02T00:00:00+00:00", btrc_revision = "c7f785e" }}

[[rows]]
kind = "operation"
id = "Library.Process"
group = "stdlib"
regression = ["src/tests/python/test_stdlib_process_security.py::test_x"]
owner = "P3"
windows-x64 = {{ parity = "adapted", implementation = "missing", owner = "W1", status = "source-only", reason = "no Win32 backend" }}
ios-simulator = {{ parity = "os-restricted", implementation = "missing", status = "source-only", reason = "no fork" }}
android-arm64 = {{ parity = "equivalent", implementation = "implemented", status = "implemented-unverified" }}
''',
        encoding="utf-8",
    )

    records = LedgerDocument.load(ledger)

    assert [(r.subject.platform.value, r.subject.variant) for r in records] == [
        ("windows", "x86_64"),
        ("ios", "arm64-simulator"),
        ("android", "arm64"),
    ]
    assert [r.classification.owner for r in records] == ["W1", "P3", "P3"]
    assert {r.classification.regression for r in records} == {
        ("src/tests/python/test_stdlib_process_security.py::test_x",)
    }
    assert records[1].evidence.reason == "no fork" and records[1].subject.group == "stdlib"
    assert all(r.provenance.btrc_revision == "c7f785e" for r in records)

    for edit, message in (
        ('windows-x64 = {{', "unknown field"),
        ('status = "implemented-unverified"', "a missing slot cannot be implemented-unverified"),
        ("provenance = {{", "needs provenance btrc_revision and recorded_at"),
    ):
        text = ledger.read_text(encoding="utf-8")
        if edit.startswith("windows"):
            text = text.replace("windows-x64 = {", "windows-x86 = {")
        elif edit.startswith("status"):
            text = text.replace('parity = "equivalent"', 'parity = "missing"')
        else:
            text = text.replace("provenance = {", "# provenance = {")
        broken = tmp_path / "broken.toml"
        broken.write_text(text, encoding="utf-8")
        with pytest.raises(LedgerSchemaError, match=message):
            LedgerDocument.load(broken)


def test_unavailable_slots_are_listed_with_their_coverage():
    from tools.qualification.report import QualificationReport

    def skipped(nodeid: str, covered_by):
        evidence = {"status": "unavailable", "observed": "skipped", "reason": "why"}
        if covered_by is not None:
            evidence["covered_by"] = covered_by
        return LedgerRecord.from_mapping(
            {"schema": SCHEMA, "subject": {"kind": "test", "id": nodeid, "platform": "macos"}, "evidence": evidence}
        )

    rows = QualificationReport(
        [
            skipped("a", ["linux-devcontainer"]),
            skipped("b", ["linux-devcontainer"]),
            skipped("c", []),
            skipped("d", None),
        ]
    ).unavailable_rows()

    assert [(row["covered_by"], row["slots"]) for row in rows] == [
        ("linux-devcontainer", 2),
        ("unclassified", 1),
        ("uncovered", 1),
    ]


# --- the store and the command ---------------------------------------------


@pytest.mark.parametrize("root", ["/tmp/qualification", "/private/tmp/q", "/var/tmp/q"])
def test_the_store_refuses_temporary_roots(root):
    from tools.qualification.store import QualificationStore, QualificationStoreError

    with pytest.raises(QualificationStoreError, match="temporary directories"):
        QualificationStore.resolve_root(root, environ={})


def test_the_store_defaults_under_the_btrc_cache(monkeypatch):
    from tools.qualification.store import QualificationStore, QualificationStoreError

    monkeypatch.delenv("BTRC_QUALIFICATION_DIR", raising=False)
    assert QualificationStore.resolve_root(environ={}) == Path.home() / ".cache" / "btrc" / "qualification"
    assert QualificationStore.resolve_root(environ={"BTRC_QUALIFICATION_DIR": "/srv/q"}) == Path("/srv/q")
    with pytest.raises(QualificationStoreError, match="absolute"):
        QualificationStore.resolve_root("relative/q", environ={})


def test_ingest_keeps_raw_inputs_and_report_reads_every_ledger(tmp_path: Path, capsys):
    from tools.qualification.cli import QualificationCommand
    from tools.qualification.store import QualificationStore, QualificationStoreError

    store = QualificationStore(tmp_path / "qualification")
    bench = tmp_path / "report.json"
    bench.write_text(json.dumps(QUICK_BENCH))
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT)

    status = QualificationCommand(store).run(
        ["ingest", "--run", "r1", "--budget-bench", str(bench), "--junit", str(junit), "--runner", "macos"]
    )

    assert status == 0, capsys.readouterr().err
    kept = sorted(path.name.split("-", 1)[1] for path in (store.root / "raw" / "r1").iterdir())
    assert kept == ["junit.xml", "report.json"]
    ledger = store.ledger_path("r1")
    records = LedgerDocument.load(ledger)
    assert len(records) == 27
    assert all(record.evidence is None or record.evidence.artifact.startswith(str(store.root)) for record in records)
    capsys.readouterr()

    assert QualificationCommand(store).run(["report", "--all-ledgers", "--format", "json"]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert {row["kind"]: row["slots"] for row in rendered["evidence"]} == {"scenario": 20, "test": 7}
    with pytest.raises(QualificationStoreError, match="run id"):
        store.ledger_path("../escape")
    assert QualificationCommand(store).run(["report", "--budget", "noop:p50<=3", "--budget-bench", str(bench)]) == 2


def test_the_report_command_fails_on_missing_frozen_slots_and_relabelled_runs(tmp_path: Path, capsys):
    from tools.qualification.cli import QualificationCommand
    from tools.qualification.store import QualificationStore

    store = QualificationStore(tmp_path / "qualification")
    bench = tmp_path / "report.json"
    bench.write_text(json.dumps({"provenance": {**BENCH_HOST, "frontend": "selfhost"}, "scenarios": QUICK_BENCH}))
    budgets = ["--budget", "cold-transpile:median<=45", "--budget", "memory:max<=3758096384"]

    assert QualificationCommand(store).run(["report", "--budget-bench", str(bench), *budgets]) == 0
    assert "| cold-transpile | macos | selfhost | - | wall-time | s | 5 | 43.574 |" in capsys.readouterr().out
    assert QualificationCommand(store).run(["report", "--budget-bench", str(bench), "--denominators"]) == 1
    assert "family-cell: 300 of 300 declared slots have no record" in capsys.readouterr().err
    assert QualificationCommand(store).run(["report", "--budget-bench", str(bench), "--frontend", "reference"]) == 2
    assert "the run measured the selfhost frontend, not reference" in capsys.readouterr().err
