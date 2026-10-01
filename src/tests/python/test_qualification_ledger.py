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


# --- budget_bench -----------------------------------------------------------


def test_budget_bench_reports_through_the_shared_nearest_rank_statistics():
    from tools.budget_bench import SCENARIOS, Scenario

    scenario = Scenario("edit-navigation", samples=[float(value) for value in range(1, 21)])

    assert scenario.summary()["median"] == 10.5
    assert scenario.summary()["p95"] == 19.0
    assert scenario.summary()["max"] == 20.0
    assert Scenario("noop").summary()["p95"] is None
    assert SCENARIOS == (
        "cold-transpile",
        "cold-dev",
        "edit-navigation",
        "edit-ui-controller",
        "edit-audio-preparation",
        "noop",
        "touch",
        "memory",
    )


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
            "cold dev build sampled aggregate RSS peak 4000000000 bytes (3.725 GiB)",
        ],
    },
}


def _bench_records(budgets=None):
    from tools.qualification.adapters import BudgetBenchAdapter
    from tools.qualification.schema import Provenance

    adapter = BudgetBenchAdapter(
        Provenance(runner="macos", btrc_revision="65057cb"),
        budgets=budgets,
        recorded_at="2026-09-24T10:00:00+00:00",
    )
    return adapter.records(QUICK_BENCH)


def test_the_bench_adapter_counts_against_every_declared_scenario():
    records = {record.subject.id: record for record in _bench_records()}

    assert len(records) == 8
    assert records["cold-dev"].evidence is None
    assert records["cold-transpile"].evidence.status is EvidenceStatus.PASSED
    assert records["edit-navigation"].evidence.status is EvidenceStatus.PASSED
    assert records["edit-navigation"].measurement.components["native"] == (1.0,) * 20
    noop = records["noop"]
    assert noop.evidence.status is EvidenceStatus.IMPLEMENTED_UNVERIFIED
    assert noop.evidence.reason == "3 of 20 required samples"
    memory = records["memory"].measurement
    assert (memory.metric, memory.unit, memory.samples) == ("peak-footprint", "bytes", (3184183936,))
    assert memory.components == {"aggregate-rss": (4000000000,)}
    provenance = records["memory"].provenance
    assert (provenance.source, provenance.build_mode, provenance.frontend) == ("budget_bench", "debug", "selfhost")
    assert provenance.recorded_at == "2026-09-24T10:00:00+00:00"


def test_bench_budgets_decide_between_passed_and_unverified():
    from tools.qualification.schema import Budget

    records = {
        record.subject.id: record
        for record in _bench_records(
            {"edit-navigation": (Budget(Statistic.MEDIAN, 10.0), Budget(Statistic.P95, 9.1))},
        )
    }

    evidence = records["edit-navigation"].evidence
    assert evidence.status is EvidenceStatus.IMPLEMENTED_UNVERIFIED
    assert evidence.reason == "p95 9.18 exceeds 9.1 s"


def test_the_bench_adapter_rejects_reports_it_cannot_vouch_for():
    from tools.qualification.adapters import BudgetBenchAdapter
    from tools.qualification.schema import Provenance

    adapter = BudgetBenchAdapter(Provenance())
    with pytest.raises(LedgerSchemaError, match="interface-edit are not budget_bench SCENARIOS"):
        adapter.records({"interface-edit": _bench_summary([1.0])})
    tampered = {"noop": {**_bench_summary([1.0, 2.0, 3.0]), "p95": 2.0}}
    with pytest.raises(LedgerSchemaError, match=r"noop\.p95: reported 2\.0, its samples give 3\.000"):
        adapter.records(tampered)


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

    report = QualificationReport([*_bench_records(), *_junit_records(tmp_path)])
    rows = {row["kind"]: row for row in report.evidence_rows()}

    assert rows["scenario"] == {
        "kind": "scenario",
        "platform": "macos",
        "frontend": "selfhost",
        "slots": 8,
        "passed": 3,
        "implemented-unverified": 1,
        "source-only": 0,
        "unavailable": 0,
        "unrecorded": 4,
        "failed": 0,
    }
    assert rows["test"]["slots"] == 7
    assert (rows["test"]["passed"], rows["test"]["implemented-unverified"], rows["test"]["unavailable"]) == (3, 3, 1)
    assert rows["test"]["failed"] == 2
    markdown = report.render_markdown()
    assert (
        "| kind | platform | frontend | slots | passed | implemented-unverified | source-only | unavailable |"
        in markdown
    )
    assert "| scenario | macos | selfhost | 8 | 3 | 1 | 0 | 0 | 4 | 0 |" in markdown
    assert (
        "| edit-navigation | macos | selfhost | wall-time | s | 20 | 9.095 | 9.180 | 9.190 | 0 | passed | - |"
        in markdown
    )
    assert "3184183936" in markdown
    assert json.loads(report.render_json())["slots"] == 15


def test_ui_catalog_slots_and_p0_rows_roll_up_against_their_inventory():
    from tools.qualification.report import QualificationReport

    platforms = ("macos", "linux", "windows", "ios", "android")
    operations = [
        LedgerRecord.from_mapping(
            {
                "schema": SCHEMA,
                "subject": {"kind": "ui-operation", "id": f"ui.op{index}", "platform": platform, "frontend": frontend},
            }
        )
        for index in range(162)
        for platform in platforms
        for frontend in ("reference", "selfhost")
    ]
    cases = [
        LedgerRecord.from_mapping(
            {"schema": SCHEMA, "subject": {"kind": "ui-case", "id": f"E{index}", "platform": p, "frontend": f}}
        )
        for index in range(47)
        for p in platforms
        for f in ("reference", "selfhost")
    ]
    inventory = [
        LedgerRecord.from_mapping(
            {
                "schema": SCHEMA,
                "subject": {"kind": "operation", "id": "Library.Tray.show", "platform": "ios"},
                "classification": {"parity": "os-restricted", "owner": "platform-ios", "decision": "D21"},
                "evidence": {"status": "source-only"},
            }
        ),
        LedgerRecord.from_mapping(
            {
                "schema": SCHEMA,
                "subject": {"kind": "operation", "id": "Library.FileSystem.readText", "platform": "ios"},
                "classification": {"parity": "equivalent", "owner": "platform-ios", "regression": "FileSystemText"},
            }
        ),
        # A later test result for the same slot keeps the inventory row's classification.
        LedgerRecord.from_mapping(
            {
                "schema": SCHEMA,
                "subject": {"kind": "operation", "id": "Library.FileSystem.readText", "platform": "ios"},
                "evidence": {"status": "passed", "observed": "passed"},
            }
        ),
    ]

    report = QualificationReport([*operations, *cases, *inventory])
    evidence = report.evidence_rows()

    assert sum(row["slots"] for row in evidence if row["kind"] == "ui-operation") == 1620
    assert sum(row["slots"] for row in evidence if row["kind"] == "ui-case") == 470
    assert all(row["unrecorded"] == row["slots"] for row in evidence if row["kind"].startswith("ui-"))
    parity = {row["kind"]: row for row in report.parity_rows()}
    assert parity["operation"]["os-restricted"] == 1 and parity["operation"]["equivalent"] == 1
    completeness = {row["kind"]: row for row in report.completeness_rows() if row["platform"] == "ios"}
    assert completeness["operation"] == {
        "kind": "operation",
        "platform": "ios",
        "frontend": None,
        "rows": 2,
        "without_owner": 0,
        "without_regression": 1,
        "without_status": 0,
    }
    operation_row = next(row for row in evidence if row["kind"] == "operation")
    assert (operation_row["passed"], operation_row["source-only"]) == (1, 1)


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
    assert len(records) == 15
    assert all(record.evidence is None or record.evidence.artifact.startswith(str(store.root)) for record in records)
    capsys.readouterr()

    assert QualificationCommand(store).run(["report", "--all-ledgers", "--format", "json"]) == 0
    rendered = json.loads(capsys.readouterr().out)
    assert {row["kind"]: row["slots"] for row in rendered["evidence"]} == {"scenario": 8, "test": 7}
    with pytest.raises(QualificationStoreError, match="run id"):
        store.ledger_path("../escape")
    assert QualificationCommand(store).run(["report", "--budget", "noop:p99<=3", "--budget-bench", str(bench)]) == 2
