"""A qualification cell cannot pass with a partial denominator or evidence set."""

import json
import xml.etree.ElementTree as ET

import pytest

from tools.ui.e40 import E40Run, LinuxE40Cases

NODES = LinuxE40Cases.nodes("python", "plain")
METADATA = {"frontend": "python", "variant": "plain", "session": "x11", "revision": "a" * 40, "source_changes": []}


def junit(path, nodes, status=None):
    suite = ET.Element("testsuite")
    for node in nodes:
        source, name = node.split("::")
        case = ET.SubElement(suite, "testcase", classname=source.removesuffix(".py").replace("/", "."), name=name)
        if status:
            ET.SubElement(case, status)
    ET.ElementTree(suite).write(path)


def evidence(root):
    common = {
        "frontend": "python",
        "sanitized": False,
        "backend": "x11",
        "returncode": 0,
        "revision": METADATA["revision"],
        "source_changes": [],
    }
    for terminal in range(4):
        for count in (4095, 4096, 4097, 8193):
            directory = root / "pytest" / f"burst-{count}-{terminal}"
            directory.mkdir(parents=True)
            (directory / "e40-bursts.json").write_text(
                json.dumps(
                    {
                        **common,
                        "count": count,
                        "terminal": terminal,
                        "repetitions": 100,
                        "trials": [{}] * 100,
                        "admission": [{}] * 100,
                    }
                )
            )
            (directory / "stdout.txt").write_text("native output")
            (directory / "stderr.txt").write_text("")
    directory = root / "pytest" / "load"
    directory.mkdir()
    (directory / "e40-load.json").write_text(
        json.dumps(
            {
                **common,
                "requested_seconds": 600,
                "qualifying": True,
                "native": [{"duration_ns": 600_000_000_000, "qualifying": True}],
            }
        )
    )
    (directory / "stdout.txt").write_text("native output")
    (directory / "stderr.txt").write_text("")
    (directory / "presentations.csv").write_text("window,ns\n0,1\n1,2\n")


def test_complete_cell_evidence(tmp_path):
    assert len(NODES) == len(set(NODES)) == 17
    E40Run.validate_collection("\n".join(NODES), NODES)
    path = tmp_path / "junit.xml"
    junit(path, NODES)
    E40Run.validate_junit(path, NODES)
    evidence(tmp_path)
    LinuxE40Cases.validate_evidence(tmp_path, METADATA)


@pytest.mark.parametrize("nodes", [NODES[:-1], [*NODES, NODES[0]], [*NODES[:-1], NODES[0]]])
def test_collection_rejects_missing_extra_and_duplicate_cases(nodes):
    with pytest.raises(RuntimeError, match="collection differs"):
        E40Run.validate_collection("\n".join(nodes), NODES)


@pytest.mark.parametrize("status", ["skipped", "failure", "error"])
def test_junit_rejects_nonpassing_cases(tmp_path, status):
    path = tmp_path / "junit.xml"
    junit(path, NODES, status)
    with pytest.raises(RuntimeError, match="without skips"):
        E40Run.validate_junit(path, NODES)


@pytest.mark.parametrize("nodes", [NODES[:-1], [*NODES, NODES[0]], [*NODES[:-1], NODES[0]]])
def test_junit_requires_each_identity_exactly_once(tmp_path, nodes):
    path = tmp_path / "junit.xml"
    junit(path, nodes)
    with pytest.raises(RuntimeError, match="exactly once"):
        E40Run.validate_junit(path, NODES)


@pytest.mark.parametrize(
    "missing", ["burst-4095-0/e40-bursts.json", "load/e40-load.json", "load/presentations.csv", "load/stderr.txt"]
)
def test_evidence_requires_all_reports_and_native_outputs(tmp_path, missing):
    evidence(tmp_path)
    (tmp_path / "pytest" / missing).unlink()
    with pytest.raises(RuntimeError):
        LinuxE40Cases.validate_evidence(tmp_path, METADATA)


@pytest.mark.parametrize(
    "field,value", [("requested_seconds", 10), ("qualifying", False), ("frontend", "selfhost"), ("backend", "wayland")]
)
def test_short_or_wrong_cell_evidence_cannot_qualify(tmp_path, field, value):
    evidence(tmp_path)
    path = tmp_path / "pytest/load/e40-load.json"
    report = json.loads(path.read_text())
    report[field] = value
    path.write_text(json.dumps(report))
    with pytest.raises(RuntimeError):
        LinuxE40Cases.validate_evidence(tmp_path, METADATA)


@pytest.mark.parametrize("field,value", [("revision", "b" * 40), ("source_changes", [" M changed.btrc"])])
def test_report_identity_must_match_the_qualification_run(tmp_path, field, value):
    evidence(tmp_path)
    path = tmp_path / "pytest/burst-4095-0/e40-bursts.json"
    report = json.loads(path.read_text())
    report[field] = value
    path.write_text(json.dumps(report))
    with pytest.raises(RuntimeError, match="provenance/outcome differs"):
        LinuxE40Cases.validate_evidence(tmp_path, METADATA)
