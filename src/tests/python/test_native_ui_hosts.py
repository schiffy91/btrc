"""UI host routing must not turn stand-ins or missing devices into evidence."""

from __future__ import annotations

import copy
import itertools
import json
import os
import re
import subprocess
import sys
import tomllib
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.tests.process_limits import TOOL_TIMEOUT

REPO = Path(__file__).resolve().parents[3]
HOSTS = REPO / "docs/design/native-ui-catalog/hosts.toml"
DEVICES = REPO / "docs/qualification/devices.toml"
SCRIPT = REPO / "tools/ui/linux-desktop-check.sh"
PLATFORMS = {"macos", "linux", "windows", "ios", "android"}
FRONTENDS = {"reference", "selfhost"}
EVIDENCE_CLASSES = {"automation", "accessibility-tree", "assistive-technology", "physical-input-ime", "gpu"}
RUNNERS = {
    "github-macos",
    "mac-m1-max",
    "linux-devcontainer",
    "github-linux",
    "linux-fractal-north",
    "github-windows-x64",
    "github-windows-arm64",
    "mac-ios-simulator",
    "github-ios-simulator",
    "mac-android-emulator",
    "github-android-emulator",
    "unavailable",
}


def plan_items():
    stage = False
    result = set()
    for line in (REPO / "PLAN.md").read_text().splitlines():
        if re.match(r"^### Stage \d+:", line):
            stage = True
        elif line.startswith("## "):
            stage = False
        elif stage and line.lstrip().startswith("- "):
            result.update(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", line))
    return result


def validate_hosts(document):
    assert set(document) == {
        "schema",
        "recorded_at",
        "platforms",
        "frontends",
        "evidence_classes",
        "disk_budget",
        "routes",
    }
    assert document["schema"] == "btrc.ui-hosts/1"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", document["recorded_at"])
    for field, expected in (("platforms", PLATFORMS), ("frontends", FRONTENDS), ("evidence_classes", EVIDENCE_CLASSES)):
        assert set(document[field]) == expected and len(document[field]) == len(expected), field
    registry = {row["id"]: row for row in tomllib.loads(DEVICES.read_text())["device"]}
    items = plan_items()
    required = {"id", "platform", "frontends", "runner", "kind", "evidence_classes", "status", "note"}
    keys = set()
    ids = set()
    coverage = set()
    for route in document["routes"]:
        assert required <= route.keys()
        assert not route.keys() - required - {"blocked_by", "device_id", "provenance"}
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", route["id"])
        assert route["id"] not in ids, "duplicate route id"
        ids.add(route["id"])
        assert route["platform"] in PLATFORMS
        assert set(route["frontends"]) == FRONTENDS and len(route["frontends"]) == 2
        assert route["runner"] in RUNNERS
        assert route["kind"] in {"hosted", "cloud", "physical", "simulator", "emulator"}
        assert route["status"] in {"available", "unverified", "blocked", "unavailable"}
        assert route["note"].strip()
        classes = route["evidence_classes"]
        assert classes and set(classes) <= EVIDENCE_CLASSES and len(classes) == len(set(classes))
        if route["status"] != "available":
            assert route.get("blocked_by"), "missing blockers"
            assert set(route["blocked_by"]) <= items, "unknown PLAN item"
        else:
            assert not route.get("blocked_by")
        assert (route["runner"] == "unavailable") == (route["status"] == "unavailable")
        if route["kind"] == "physical":
            assert "device_id" in route, "physical route needs registered device"
        if "device_id" in route:
            assert route["device_id"] in registry, "unknown device"
            device_status = registry[route["device_id"]]["status"]
            if route["status"] == "available":
                assert device_status == "available", "unverified hardware promoted"
            if route["kind"] == "physical" and device_status == "unavailable":
                assert route["status"] == "unavailable", "unavailable hardware promoted"
        provenance = route.get("provenance", {})
        assert not set(provenance) - {"device_class"}
        if route["platform"] == "ios":
            assert provenance.get("device_class"), "ios form factor is explicit"
        if route["kind"] in {"hosted", "cloud", "simulator", "emulator"}:
            assert "physical-input-ime" not in classes, "stand-in cannot qualify physical input"
            assert "assistive-technology" not in classes, "stand-in is not an observed assistive journey"
        for frontend, evidence in itertools.product(route["frontends"], classes):
            coverage.add((route["platform"], frontend, evidence))
            key = (
                route["platform"],
                route["runner"],
                provenance.get("device_class"),
                route.get("device_id"),
                frontend,
                evidence,
            )
            assert key not in keys, "duplicate evidence route"
            keys.add(key)
    assert coverage == set(itertools.product(PLATFORMS, FRONTENDS, EVIDENCE_CLASSES)), "matrix coverage"
    simulators = [route for route in document["routes"] if route["platform"] == "ios" and route["kind"] == "simulator"]
    for runner in ("mac-ios-simulator", "github-ios-simulator"):
        assert {row["provenance"]["device_class"] for row in simulators if row["runner"] == runner} == {
            "iphone-simulator",
            "ipad-simulator",
        }
    budget = document["disk_budget"]
    assert budget["stage23_minimum_free_gb"] >= 150
    assert budget["later_stage_minimum_free_gb"] >= 100
    assert budget["android_sdk_ndk_avd_estimate_gb"] == [10, 15]
    assert budget["android_platforms_closure_gb"] >= 17.75
    assert budget["ios_runtime_budget"].strip() and budget["note"].strip()


def test_host_matrix_is_complete_and_consistent_with_device_registry():
    validate_hosts(tomllib.loads(HOSTS.read_text()))


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown-device",
        "promoted-hardware",
        "no-blocker",
        "unknown-blocker",
        "duplicate",
        "missing-platform",
        "wrong-frontend",
        "invented-runner",
        "physical-stand-in",
        "missing-ipad",
    ],
)
def test_invalid_host_claims_are_rejected(mutation):
    document = copy.deepcopy(tomllib.loads(HOSTS.read_text()))
    physical = next(row for row in document["routes"] if row["id"] == "linux-desktop")
    if mutation == "unknown-device":
        physical["device_id"] = "invented-device"
    elif mutation == "promoted-hardware":
        physical["status"] = "available"
        physical.pop("blocked_by")
    elif mutation == "no-blocker":
        physical.pop("blocked_by")
    elif mutation == "unknown-blocker":
        physical["blocked_by"] = ["not-a-plan-item"]
    elif mutation == "duplicate":
        document["routes"].append(copy.deepcopy(physical))
    elif mutation == "missing-platform":
        document["routes"] = [row for row in document["routes"] if row["platform"] != "android"]
    elif mutation == "wrong-frontend":
        physical["frontends"] = ["reference"]
    elif mutation == "invented-runner":
        physical["runner"] = "magic-host"
    elif mutation == "physical-stand-in":
        document["routes"][0]["evidence_classes"].append("physical-input-ime")
    elif mutation == "missing-ipad":
        document["routes"] = [row for row in document["routes"] if row["id"] != "ios-ipad-github"]
    with pytest.raises(AssertionError):
        validate_hosts(document)


def desktop_probe(tmp_path, *arguments):
    # Run the shell's exact embedded Python portably; the separate bash -n gate
    # checks the shell wrapper. Empty PATH supplies a deterministic missing-tools host.
    body = SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    environment = {
        key: value for key, value in os.environ.items() if key not in {"DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_ID"}
    }
    environment["PATH"] = ""
    return subprocess.run(
        [sys.executable, "-", str(REPO), "--artifacts", str(tmp_path / "evidence"), *arguments],
        input=body,
        text=True,
        capture_output=True,
        env=environment,
        timeout=TOOL_TIMEOUT,
    )


def test_desktop_probe_records_missing_tools_without_inventing_evidence(tmp_path):
    result = desktop_probe(tmp_path, "--probe-only")
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["schema"] == "btrc.linux-desktop-check/1"
    assert report["status"] == "incomplete"
    assert report["physical_qualification"] is False
    assert report["btrc_revision"] is None
    assert report["trials"]["gui-correctness"]["status"] == "not-run"
    assert all(probe["status"] == "unavailable" for probe in report["probes"].values())
    for key in ("orca-button-label", "gpu-device-reset", "physical-input-ime"):
        assert report["trials"][key]["status"] == "blocked"
        assert set(report["trials"][key]["blocked_by"]) <= plan_items()
    assert report["trials"]["orca-button-label"]["atspi_event_log"] is None


def test_desktop_probe_does_not_substitute_headless_for_a_missing_desktop(tmp_path):
    result = desktop_probe(tmp_path)
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["trials"]["gui-correctness"]["status"] == "unavailable"
    assert "passed" not in {trial["status"] for trial in report["trials"].values()}


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "3601"])
def test_desktop_probe_rejects_unbounded_or_invalid_timeouts(tmp_path, value):
    result = desktop_probe(tmp_path, "--probe-timeout", value)
    assert result.returncode == 2
    assert "timeout must be finite" in result.stderr
    assert not result.stdout


@pytest.fixture
def desktop_module():
    body = SCRIPT.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    module = types.ModuleType("desktop_check_test")
    exec(compile(body, str(SCRIPT), "exec"), module.__dict__)
    return module


def gui_junit(module, path, names=None, skipped=False):
    suite = ET.Element("testsuite")
    for index, name in enumerate(sorted(module.GUI_CASES) if names is None else names):
        case = ET.SubElement(suite, "testcase", classname=module.GUI_MODULE, name=name)
        if skipped and index == 0:
            ET.SubElement(case, "skipped", message="no native provider")
    ET.ElementTree(suite).write(path)


def test_desktop_probe_rejects_stale_junit_when_zero_exit_writes_no_report(tmp_path, desktop_module):
    junit = tmp_path / "gui.xml"
    gui_junit(desktop_module, junit)

    def execute(name, command, timeout):
        assert not junit.exists(), "the previous report must be removed before launching pytest"
        return {"status": "observed", "returncode": 0}

    result = desktop_module.gui_trial(REPO, tmp_path, 1, execute)
    assert result["status"] == "failed"
    assert "missing or invalid GUI JUnit" in result["reason"]


@pytest.mark.parametrize(
    "mutation",
    ["unrelated", "duplicate", "missing", "wrong-classname", "failed-process", "cleanup-failed", "skipped", "valid"],
)
def test_desktop_gui_proof_requires_fresh_exact_fixture_identities(tmp_path, desktop_module, mutation):
    def execute(name, command, timeout):
        names = sorted(desktop_module.GUI_CASES)
        if mutation == "unrelated":
            names = [f"unrelated-test-{index}" for index in range(8)]
        elif mutation == "duplicate":
            names[-1] = names[0]
        elif mutation == "missing":
            names.pop()
        path = Path(command[-1])
        gui_junit(desktop_module, path, names, skipped=mutation == "skipped")
        if mutation == "wrong-classname":
            tree = ET.parse(path)
            tree.getroot()[0].set("classname", "unrelated.module")
            tree.write(path)
        return {
            "status": "cleanup-failed" if mutation == "cleanup-failed" else "observed",
            "returncode": 1 if mutation == "failed-process" else 0,
        }

    result = desktop_module.gui_trial(REPO, tmp_path, 1, execute)
    assert result["status"] == {"valid": "passed", "skipped": "unavailable"}.get(mutation, "failed")


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_desktop_command_timeout_and_cleanup_remain_serializable(tmp_path, desktop_module, monkeypatch, cleanup_fails):
    waits = []

    class StuckChild:
        pid = 999999999

        def wait(self, timeout):
            waits.append(timeout)
            if len(waits) == 1 or cleanup_fails:
                raise subprocess.TimeoutExpired("probe", timeout)
            return 0

        def poll(self):
            return None

        def terminate(self):
            pass

        def kill(self):
            pass

    monkeypatch.setattr(desktop_module.shutil, "which", lambda executable: sys.executable)
    monkeypatch.setattr(desktop_module.subprocess, "Popen", lambda *args, **kwargs: StuckChild())
    monkeypatch.setattr(desktop_module.os, "killpg", lambda *args: None, raising=False)
    result = desktop_module.run("timeout", ["probe"], 0.1, repo=REPO, artifacts=tmp_path)
    assert result["status"] == ("cleanup-failed" if cleanup_fails else "timeout")
    assert waits == [0.1, 2, 2]
    assert json.loads(json.dumps(result))["status"] == result["status"]
