"""The qualification ledger: schema validation, statistics, adapters and the report."""

from __future__ import annotations

import json
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
            "owner": "windows-ui",
            "regression": "src/tests/python/test_text_field.py::test_set_text",
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
            "os_build": "26100.1",
            "device_class": "x86_64",
            "build_mode": "debug",
        },
    }

    record = LedgerRecord.from_mapping(data)

    assert record.subject.kind is SubjectKind.UI_OPERATION
    assert record.classification is not None and record.classification.parity is Parity.ADAPTED
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
            "'p50' is not one of median, p95, max",
        ),
    ],
)
def test_schema_violations_fail_with_their_location(change, message):
    with pytest.raises(LedgerSchemaError, match=message):
        LedgerRecord.from_mapping({**_record(), **change})


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
classification = {{ parity = "equivalent", owner = "platform-windows", regression = "src/tests/stdlib/FileSystemText.btrc" }}
evidence = {{ status = "implemented-unverified" }}

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
