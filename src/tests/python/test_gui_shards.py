"""Exact GUI collection, partition coverage and evidence failure regressions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.ui.gui_shards import NODE_PROPERTY, ROOT, GUIPartition, GUIShardRun

HEAD = "a" * 40
NODES = [f"src/tests/python/test_native_example.py::test_case[{i}]" for i in range(12)]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value))


def evidence(directory: Path, selected: list[str], *, skipped: bool = False) -> None:
    suite = ET.Element("testsuite")
    outcomes = {}
    skips = []
    for index, node in enumerate(selected):
        case = ET.SubElement(suite, "testcase", classname="not.reversible", name=f"case::{index}")
        properties = ET.SubElement(case, "properties")
        ET.SubElement(properties, "property", name=NODE_PROPERTY, value=node)
        outcomes[node] = "skipped" if skipped and index == 0 else "passed"
        if outcomes[node] == "skipped":
            reason = "requires macOS and the explicitly built native header reader"
            ET.SubElement(case, "skipped", message=reason)
            skips.append({"nodeid": node, "when": "setup", "reason": reason})
    ET.ElementTree(suite).write(directory / "junit.xml")
    write_json(
        directory / "skip-report.json",
        {
            "schema": "btrc.skip-report/1",
            "runner": "linux-devcontainer",
            "revision": HEAD,
            "invocation": {"exitstatus": 0},
            "tests": outcomes,
            "skips": skips,
            "counts": {},
        },
    )


@pytest.fixture
def cells(tmp_path):
    for index in range(4):
        directory = tmp_path / f"x11-{index}"
        directory.mkdir()
        record = GUIPartition.create(NODES, "x11", index, 4, HEAD)
        record["status"] = "passed"
        write_json(directory / "partition.json", record)
        write_json(
            directory / "collection.json",
            {"schema": "btrc.gui-collection/1", "nodes": sorted(NODES), "exitstatus": 0, "problems": []},
        )
        evidence(directory, record["selected"], skipped=index == 0)
    return tmp_path


def test_disjoint_union_and_classified_skips_are_required(cells):
    result = GUIPartition.aggregate(cells, "x11", 4, HEAD)
    assert result["nodes"] == len(NODES) and result["status"] == "passed"
    assert result["whole_sha256"] == GUIPartition.digest(sorted(NODES))


@pytest.mark.parametrize(
    "damage",
    [
        "missing",
        "duplicate-cell",
        "duplicate-node",
        "hash",
        "source",
        "session",
        "membership",
        "different-whole",
        "failed",
        "junit",
        "skip",
        "skip-source",
        "unexpected-skip",
    ],
)
def test_incomplete_or_contradictory_cells_never_qualify(cells, damage):
    directory = cells / "x11-0"
    path = directory / "partition.json"
    record = json.loads(path.read_text())
    if damage == "missing":
        shutil.rmtree(directory)
    elif damage == "duplicate-cell":
        shutil.copytree(directory, cells / "extra")
    elif damage == "duplicate-node":
        record["whole"].append(record["whole"][0])
    elif damage == "hash":
        record["whole_sha256"] = "0" * 64
    elif damage == "source":
        record["revision"] = "b" * 40
    elif damage == "session":
        record["session"] = "wayland"
    elif damage == "membership":
        record["selected"] = record["whole"][1::4]
    elif damage == "different-whole":
        record = GUIPartition.create([*NODES[:-1], NODES[-1] + "extra"], "x11", 0, 4, HEAD)
        record["status"] = "passed"
        evidence(directory, record["selected"])
        write_json(
            directory / "collection.json",
            {"schema": "btrc.gui-collection/1", "nodes": record["whole"], "exitstatus": 0, "problems": []},
        )
    elif damage == "failed":
        record["status"] = "failed"
    elif damage == "junit":
        tree = ET.parse(directory / "junit.xml")
        tree.getroot().append(tree.getroot()[0])
        tree.write(directory / "junit.xml")
    else:
        report = json.loads((directory / "skip-report.json").read_text())
        if damage == "skip":
            report["tests"].pop(record["selected"][0])
        elif damage == "skip-source":
            report["revision"] = "b" * 40
        else:
            report["skips"][0]["reason"] = "unexpected device failure"
        write_json(directory / "skip-report.json", report)
    if path.exists():
        write_json(path, record)
    with pytest.raises(ValueError):
        GUIPartition.aggregate(cells, "x11", 4, HEAD)


@pytest.mark.parametrize("problem", ["empty", "duplicate", "error", "collect-skip", "nonzero"])
def test_collection_cannot_silently_lose_nodes(tmp_path, problem):
    value = {"schema": "btrc.gui-collection/1", "nodes": NODES, "exitstatus": 0, "problems": []}
    if problem == "empty":
        value["nodes"] = []
    elif problem == "duplicate":
        value["nodes"] = [*NODES, NODES[0]]
    elif problem == "nonzero":
        value["exitstatus"] = 2
    else:
        value["problems"] = [{"nodeid": "test_lost.py", "outcome": problem}]
    path = tmp_path / "collection.json"
    write_json(path, value)
    with pytest.raises(ValueError):
        GUIPartition.collection(path)


@pytest.mark.parametrize("workers", [0, 2])
def test_actual_pytest_plugin_retains_exact_parameter_ids_and_setup_skips(tmp_path, workers):
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n@pytest.mark.parametrize('value', ['a::b', 'c.d'])\n"
        "def test_sample(value):\n    if value == 'c.d': pytest.skip('fixture skip')\n"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_ADDOPTS="")
    common = [sys.executable, "-m", "pytest", "-p", "tools.ui.gui_collection", "-c", "pytest.ini", "test_sample.py"]
    collected = subprocess.run(
        [*common, "--collect-only", "-n", "0", "--gui-collection=collection.json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert collected.returncode == 0, collected.stdout + collected.stderr
    nodes = GUIPartition.collection(tmp_path / "collection.json")
    assert nodes == ["test_sample.py::test_sample[a::b]", "test_sample.py::test_sample[c.d]"]
    run = subprocess.run(
        [*common, "-n", str(workers), "--junitxml=junit.xml"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    cases = list(ET.parse(tmp_path / "junit.xml").getroot().iter("testcase"))
    assert (
        sorted(
            prop.get("value")
            for case in cases
            for prop in case.findall("./properties/property")
            if prop.get("name") == NODE_PROPERTY
        )
        == nodes
    )
    assert sum(case.find("skipped") is not None for case in cases) == 1


@pytest.mark.parametrize("failure", [False, True])
def test_run_records_original_outcome_and_keeps_all_selected_evidence(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("SDL_VIDEODRIVER", "x11")
    monkeypatch.setenv("BTRC_TEST_RUNNER", "linux-devcontainer")
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: HEAD + "\n")
    output = tmp_path / "cell"
    run = GUIShardRun("x11", 1, 4, output, tmp_path / "external-skip.json", ["whole.py"], ["-n", "4"])
    calls = []

    def command(phase, arguments):
        calls.append((phase, arguments))
        if phase == "collection":
            write_json(
                output / "collection.json",
                {"schema": "btrc.gui-collection/1", "nodes": NODES, "exitstatus": 0, "problems": []},
            )
        else:
            evidence(output, run.record["selected"])
            run.skip_report.write_bytes((output / "skip-report.json").read_bytes())
        return 1 if failure and phase == "tests" else 0

    monkeypatch.setattr(run, "command", command)
    if failure:
        with pytest.raises(ValueError, match="tests exited 1"):
            run.run()
    else:
        run.run()
    record = json.loads((output / "partition.json").read_text())
    assert record["status"] == ("failed" if failure else "passed")
    selected = sorted(NODES)[1::4]
    assert record["selected"] == selected
    assert "--collect-only" in calls[0][1]
    worker_arguments = [calls[0][1][i + 1] for i, value in enumerate(calls[0][1]) if value == "-n"]
    assert worker_arguments == ["4", "0"]
    assert calls[1][1][: len(selected)] == selected
    assert (output / "skip-report.json").is_file()
    with pytest.raises(ValueError, match="already exist"):
        run.run()


def test_failed_aggregate_retains_explicit_failed_proof(tmp_path, monkeypatch):
    from tools.ui.gui_shards import main

    output = tmp_path / "proof.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gui_shards",
            "aggregate",
            "--session",
            "wayland",
            "--count",
            "4",
            "--revision",
            HEAD,
            "--input",
            str(tmp_path / "missing"),
            "--output",
            str(output),
        ],
    )
    assert main() == 1
    proof = json.loads(output.read_text())
    assert proof["status"] == "failed" and "got 0" in proof["error"]
    assert proof["revision"] == HEAD and proof["session"] == "wayland"


def test_run_cli_preserves_selectors_and_pytest_arguments(tmp_path, monkeypatch):
    from tools.ui.gui_shards import main

    seen = []
    monkeypatch.setattr(GUIShardRun, "run", lambda self: seen.append((self.selectors, self.arguments, self.count)))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gui_shards",
            "run",
            "--session",
            "x11",
            "--count",
            "4",
            "--output",
            str(tmp_path),
            "--skip-report",
            str(tmp_path / "skip.json"),
            "--selectors",
            "one.py",
            "two.py::test_x",
            "--",
            "-q",
            "-n",
            "4",
            "-m",
            "not e40_qualification",
        ],
    )
    assert main() == 0
    assert seen == [(["one.py", "two.py::test_x"], ["-q", "-n", "4", "-m", "not e40_qualification"], 4)]
