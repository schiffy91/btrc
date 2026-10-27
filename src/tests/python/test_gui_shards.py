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


def evidence(
    directory: Path, selected: list[str], *, skipped: bool = False, runner: str = "linux-devcontainer"
) -> None:
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
            "runner": runner,
            "revision": HEAD,
            "invocation": {"exitstatus": 0},
            "tests": outcomes,
            "skips": skips,
            "counts": {},
        },
    )


@pytest.fixture(params=["x11", "wayland", "macos"])
def cells(tmp_path, request):
    session = request.param
    for index in range(4):
        directory = tmp_path / f"{session}-{index}"
        directory.mkdir()
        record = GUIPartition.create(NODES, session, index, 4, HEAD)
        record["status"] = "passed"
        write_json(directory / "partition.json", record)
        write_json(
            directory / "collection.json",
            {"schema": "btrc.gui-collection/1", "nodes": sorted(NODES), "exitstatus": 0, "problems": []},
        )
        evidence(
            directory,
            record["selected"],
            skipped=index == 0 and session != "macos",
            runner=GUIPartition.runner(session),
        )
    return tmp_path, session


def test_disjoint_union_and_classified_skips_are_required(cells):
    root, session = cells
    result = GUIPartition.aggregate(root, session, 4, HEAD)
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
        "wrong-runner",
    ],
)
def test_incomplete_or_contradictory_cells_never_qualify(cells, damage):
    cells, session = cells
    directory = cells / f"{session}-0"
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
        record["session"] = "macos" if session != "macos" else "x11"
    elif damage == "membership":
        record["selected"] = record["whole"][1::4]
    elif damage == "different-whole":
        record = GUIPartition.create([*NODES[:-1], NODES[-1] + "extra"], session, 0, 4, HEAD)
        record["status"] = "passed"
        evidence(directory, record["selected"], runner=GUIPartition.runner(session))
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
        elif damage == "wrong-runner":
            report["runner"] = "macos-hosted" if session != "macos" else "linux-devcontainer"
        else:
            report["skips"] = [
                {"nodeid": record["selected"][0], "when": "setup", "reason": "unexpected device failure"}
            ]
        write_json(directory / "skip-report.json", report)
    if path.exists():
        write_json(path, record)
    with pytest.raises(ValueError):
        GUIPartition.aggregate(cells, session, 4, HEAD)


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
        "import pytest\n@pytest.fixture\ndef value(request):\n"
        "    if request.param == 'c.d': pytest.skip('setup fixture skip')\n"
        "    return request.param\n"
        "@pytest.mark.parametrize('value', ['a::b', 'c.d'], indirect=True)\n"
        "def test_sample(value):\n    assert value == 'a::b'\n"
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
    skipped = [case.find("skipped") for case in cases if case.find("skipped") is not None]
    assert len(skipped) == 1 and skipped[0].get("message") == "setup fixture skip"


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
    selected = [NODES[10], NODES[2], NODES[9]]
    assert record["selected"] == selected
    assert "--collect-only" in calls[0][1]
    worker_arguments = [calls[0][1][i + 1] for i, value in enumerate(calls[0][1]) if value == "-n"]
    assert worker_arguments == ["4", "0"]
    assert calls[1][1][: len(selected)] == selected
    assert "--dist=loadgroup" in calls[1][1]
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


def test_linux_provider_groups_build_each_configuration_once_and_preserve_nodes(tmp_path):
    """Exercise the real provider marks with cheap build stand-ins on four workers."""
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    linux_gui: native GUI fixture\n")
    (tmp_path / "conftest.py").write_text(
        "from src.tests.skip_ledger import SkipLedger\n"
        "def pytest_addoption(parser): SkipLedger.add_options(parser)\n"
        "def pytest_configure(config): SkipLedger.install(config)\n"
    )
    (tmp_path / "test_grouped.py").write_text(
        "from pathlib import Path\n"
        "import os\n"
        "import pytest\n"
        "from src.tests.python import test_native_ui_linux_spike as provider\n"
        "frontend = provider.frontend\n"
        "sanitized = provider.sanitized\n"
        "def build(family, frontend, sanitized):\n"
        "    key = f'{family}-{frontend}-{sanitized}'\n"
        "    path = Path(f'build-{key}-{os.environ[\"PYTEST_XDIST_WORKER\"]}.txt')\n"
        "    with path.open('a') as stream: stream.write(key + '\\n')\n"
        "    return key\n"
        "@pytest.fixture(scope='module')\n"
        "def boundary(frontend, sanitized): return build('boundary', frontend, sanitized)\n"
        "@pytest.fixture(scope='module')\n"
        "def repair(frontend, sanitized): return build('repair', frontend, sanitized)\n"
        "@pytest.mark.parametrize('repeat', range(8))\n"
        "def test_boundary(boundary, repeat): assert boundary.startswith('boundary-')\n"
        "@pytest.mark.parametrize('repeat', range(8))\n"
        "def test_repair(repair, repeat): assert repair.startswith('repair-')\n"
        "test_boundary.pytestmark += [m for m in provider.test_linux_event_boundary.pytestmark if m.name == 'xdist_group']\n"
        "test_repair.pytestmark += [m for m in provider.test_linux_input_repair.pytestmark if m.name == 'xdist_group']\n"
        "@pytest.mark.parametrize('repeat', range(4))\n"
        "def test_unrelated(repeat): assert repeat < 4\n"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTEST_ADDOPTS="", BTRC_TEST_RUNNER="linux-devcontainer")
    common = [sys.executable, "-m", "pytest", "-p", "tools.ui.gui_collection", "-c", "pytest.ini", "test_grouped.py"]
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
    assert len(nodes) == 68
    run = subprocess.run(
        [*common, "-n", "4", "--dist=loadgroup", "--junitxml=junit.xml", "--skip-report=skip-report.json"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    cases = list(ET.parse(tmp_path / "junit.xml").getroot().iter("testcase"))
    observed = [
        prop.get("value")
        for case in cases
        for prop in case.findall("./properties/property")
        if prop.get("name") == NODE_PROPERTY
    ]
    assert sorted(observed) == nodes
    partitions = [GUIPartition.create(nodes, "x11", index, 4, HEAD)["selected"] for index in range(4)]
    assert sorted(node for part in partitions for node in part) == nodes
    assert len(set(observed)) == len(nodes)
    ledger = json.loads((tmp_path / "skip-report.json").read_text())
    assert ledger["tests"] == dict.fromkeys(nodes, "passed")
    GUIPartition.outcomes(tmp_path, nodes, ledger["revision"], "x11")
    builds = [line for path in tmp_path.glob("build-*.txt") for line in path.read_text().splitlines()]
    assert sorted(builds) == sorted(
        f"{family}-{frontend}-{sanitized}"
        for family in ("boundary", "repair")
        for frontend in ("python", "selfhost")
        for sanitized in (False, True)
    )


def test_repeated_parameter_matrices_do_not_pin_each_configuration_to_one_cell():
    variants = ["plain-python", "plain-selfhost", "sanitized-python", "sanitized-selfhost"]
    nodes = [f"test_controls.py::test_control_{family}[{variant}]" for family in range(4) for variant in variants]
    partitions = [GUIPartition.create(nodes, "wayland", index, 4, HEAD)["selected"] for index in range(4)]
    assert sorted(node for selected in partitions for node in selected) == sorted(nodes)
    for selected in partitions:
        assert len(selected) == 4
        assert sorted(node.split("[")[1][:-1] for node in selected) == variants


@pytest.mark.parametrize("count,size", [(1, 1), (2, 19), (3, 20), (4, 19), (8, 19)])
def test_rotated_cells_cover_irregular_collections_once(count, size):
    nodes = [f"test_cases.py::test_value[{index:03}]" for index in range(size)]
    parts = [GUIPartition.create(list(reversed(nodes)), "x11", index, count, HEAD) for index in range(count)]
    assert all(part["schema"] == "btrc.gui-partition/2" for part in parts)
    selected = [part["selected"] for part in parts]
    assert sorted(node for part in selected for node in part) == nodes
    assert all(part == sorted(part) for part in selected)
    assert max(map(len, selected)) - min(map(len, selected)) <= 1


def test_complete_historical_stride_receipts_remain_verifiable(cells):
    cells, session = cells
    for path in cells.glob("*/partition.json"):
        record = json.loads(path.read_text())
        record["schema"] = "btrc.gui-partition/1"
        record["selected"] = record["whole"][record["index"] :: record["count"]]
        write_json(path, record)
        evidence(
            path.parent,
            record["selected"],
            skipped=record["index"] == 0 and session != "macos",
            runner=GUIPartition.runner(session),
        )
    assert GUIPartition.aggregate(cells, session, 4, HEAD)["status"] == "passed"


def test_partition_schemas_cannot_be_mixed_in_one_session(cells):
    cells, session = cells
    path = cells / f"{session}-0/partition.json"
    record = json.loads(path.read_text())
    record["schema"] = "btrc.gui-partition/1"
    write_json(path, record)
    with pytest.raises(ValueError, match="mix partition assignment"):
        GUIPartition.aggregate(cells, session, 4, HEAD)


@pytest.mark.parametrize("schema", ["btrc.gui-partition/999", None, [], {}])
def test_unknown_partition_assignment_schema_is_not_guessed(schema):
    record = GUIPartition.create(NODES, "x11", 0, 4, HEAD)
    record.update(schema=schema, status="passed")
    with pytest.raises(ValueError, match="Unsupported"):
        GUIPartition.validate(record, "x11", 4, HEAD)


@pytest.mark.parametrize(
    ("session", "platform", "runner", "driver", "allowed"),
    [
        ("macos", "darwin", "macos-hosted", "", True),
        ("macos", "linux", "macos-hosted", "", False),
        ("macos", "darwin", "macos", "", False),
        ("macos", "darwin", "linux-devcontainer", "", False),
        ("x11", "linux", "linux-devcontainer", "x11", True),
        ("wayland", "linux", "linux-devcontainer", "wayland", True),
        ("x11", "linux", "linux-devcontainer", "wayland", False),
        ("x11", "darwin", "linux-devcontainer", "x11", False),
        ("invalid", "linux", "linux-devcontainer", "invalid", False),
    ],
)
def test_runner_admission_precedes_evidence_or_execution(
    tmp_path, monkeypatch, session, platform, runner, driver, allowed
):
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setenv("BTRC_TEST_RUNNER", runner)
    monkeypatch.setenv("SDL_VIDEODRIVER", driver)
    output = tmp_path / "cell"
    run = GUIShardRun(session, 0, 2, output, tmp_path / "skip.json", ["test_sample.py"], [])
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: HEAD)
    calls = []

    def command(phase, arguments):
        calls.append(phase)
        raise RuntimeError("admitted collection")

    monkeypatch.setattr(run, "command", command)
    if allowed:
        with pytest.raises(RuntimeError, match="admitted collection"):
            run.run()
        assert calls == ["collection"]
        assert json.loads((output / "partition.json").read_text())["status"] == "failed"
    else:
        with pytest.raises(ValueError):
            run.run()
        assert not calls and not output.exists()


@pytest.mark.parametrize("count", [2, 4])
def test_macos_cells_execute_real_grouped_pytest_and_prove_union(tmp_path, monkeypatch, count):
    """Only synthetic arithmetic runs; no AppKit application or system input."""
    from src.tests.process_limits import TOOL_TIMEOUT
    from tools.ui import gui_shards

    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, timeout=TOOL_TIMEOUT).strip()
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "conftest.py").write_text(
        "from src.tests.skip_ledger import SkipLedger\n"
        "def pytest_addoption(parser): SkipLedger.add_options(parser)\n"
        "def pytest_configure(config): SkipLedger.install(config)\n"
    )
    (tmp_path / "test_sample.py").write_text(
        "import pytest\n"
        "@pytest.mark.xdist_group(name='macos_gui')\n"
        "@pytest.mark.parametrize('value', range(8), ids=lambda value: f'case::{value}@literal')\n"
        "def test_arithmetic(value): assert value + 1 > value\n"
    )
    monkeypatch.setattr(gui_shards, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: revision)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setenv("PYTEST_ADDOPTS", "")
    monkeypatch.setenv("BTRC_TEST_RUNNER", "macos-hosted")
    evidence_root = tmp_path / "evidence"
    for index in range(count):
        output = evidence_root / f"macos-{index}"
        GUIShardRun(
            "macos", index, count, output, tmp_path / f"skip-{index}.json", ["test_sample.py"], ["-n", "3", "-q"]
        ).run()
        record = json.loads((output / "partition.json").read_text())
        assert record["status"] == "passed" and len(record["selected"]) == 8 // count
        assert all("@literal" in node and "@macos_gui" not in node for node in record["selected"])
    proof = GUIPartition.aggregate(evidence_root, "macos", count, revision)
    assert proof["status"] == "passed" and proof["nodes"] == 8
    report = evidence_root / "macos-1" / "skip-report.json"
    value = json.loads(report.read_text())
    value["runner"] = "linux-devcontainer"
    write_json(report, value)
    with pytest.raises(ValueError, match="skip report identity"):
        GUIPartition.aggregate(evidence_root, "macos", count, revision)
