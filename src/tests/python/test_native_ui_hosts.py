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
from tools.qualification.adapters import RUNNER_PLATFORMS

REPO = Path(__file__).resolve().parents[3]
HOSTS = REPO / "docs/design/native-ui-catalog/hosts.toml"
DEVICES = REPO / "docs/qualification/devices.toml"
SCRIPT = REPO / "tools/ui/linux-desktop-check.sh"
PLATFORMS = {"macos", "linux", "windows", "ios", "android"}
FRONTENDS = {"reference", "selfhost"}
EVIDENCE_CLASSES = {"automation", "accessibility-tree", "assistive-technology", "physical-input-ime", "gpu"}
# Runner identity is ledger-owned; route data cannot promote a stand-in by
# relabelling its own kind. Physical runner/device pairs are independently pinned.
RUNNERS = {
    runner: (RUNNER_PLATFORMS[runner].value, kind)
    for runner, kind in {
        "macos-hosted": "hosted",
        "macos": "physical",
        "linux-devcontainer": "cloud",
        "linux": "physical",
        "windows": "hosted",
        "ios": "simulator",
        "android": "emulator",
    }.items()
}
PHYSICAL_DEVICES = {"macos": "mac-m1-max", "linux": "linux-fractal-north"}
DEVICE_PLATFORMS = {
    "mac-host": "macos",
    "linux-desktop": "linux",
    "windows-x64": "windows",
    "windows-arm64": "windows",
    "iphone-floor": "ios",
    "iphone-current": "ios",
    "ipad-floor": "ios",
    "ipad-current": "ios",
    "android-floor": "android",
    "android-current-16k": "android",
}


def plan_items():
    # The canonical item-to-stage appendix excludes release ids and prose examples.
    appendix = (REPO / "CLAUDE.md").read_text(encoding="utf-8").split("## Appendix: every mapped item → stage", 1)[1]
    return {
        item
        for line in appendix.splitlines()
        if re.match(r"^\| \d+ \|", line)
        for item in re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", line)
    }


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
    assert document["schema"] == "btrc.ui-hosts/2"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", document["recorded_at"])
    for field, expected in (("platforms", PLATFORMS), ("frontends", FRONTENDS), ("evidence_classes", EVIDENCE_CLASSES)):
        assert set(document[field]) == expected and len(document[field]) == len(expected), field
    registry = {row["id"]: row for row in tomllib.loads(DEVICES.read_text(encoding="utf-8"))["device"]}
    items = plan_items()
    required = {"id", "platform", "frontends", "runner", "kind", "evidence_classes", "status", "note"}
    keys = set()
    ids = set()
    coverage = set()
    for route in document["routes"]:
        assert required <= route.keys()
        assert not route.keys() - required - {"blocked_by", "device_id", "provenance", "probe"}
        assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", route["id"])
        assert route["id"] not in ids, "duplicate route id"
        ids.add(route["id"])
        assert route["platform"] in PLATFORMS
        assert set(route["frontends"]) == FRONTENDS and len(route["frontends"]) == 2
        assert route["runner"] in RUNNERS or route["runner"] == "unavailable"
        if route["runner"] != "unavailable":
            assert (route["platform"], route["kind"]) == RUNNERS[route["runner"]], "runner platform/kind mismatch"
        else:
            assert route["kind"] == "physical", "unavailable runner is a missing physical device"
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
        assert (route["runner"] == "unavailable") == (route["status"] == "unavailable"), (
            "unavailable runner/status mismatch"
        )
        if route["kind"] == "physical":
            assert "device_id" in route, "physical route needs registered device"
        if "device_id" in route:
            assert route["device_id"] in registry, "unknown device"
            device = registry[route["device_id"]]
            device_status = device["status"]
            expected_platform = "macos" if route["kind"] in {"simulator", "emulator"} else route["platform"]
            assert DEVICE_PLATFORMS.get(device["class"]) == expected_platform, "device platform mismatch"
            if route["kind"] == "physical" and route["runner"] != "unavailable":
                assert route["device_id"] == PHYSICAL_DEVICES[route["runner"]], "physical runner/device mismatch"
            if route["kind"] in {"simulator", "emulator"}:
                assert route["device_id"] == "mac-m1-max", "unrecognized simulator/emulator host"
            assert route["kind"] in {"physical", "simulator", "emulator"}, "hosted/cloud runner cannot claim a device"
            if route["status"] == "available":
                assert device_status == "available", "unverified hardware promoted"
            if route["kind"] == "physical" and device_status == "unavailable":
                assert route["status"] == "unavailable", "unavailable hardware promoted"
        provenance = route.get("provenance", {})
        assert not set(provenance) - {"device_class"}
        if route["kind"] == "physical":
            assert provenance.get("device_class") == registry[route["device_id"]]["class"], (
                "physical device class mismatch"
            )
        if route["runner"] == "windows":
            assert provenance.get("device_class") in {"windows-hosted-x64", "windows-hosted-arm64"}
        if "probe" in route:
            assert route["id"] == "linux-desktop" and route["kind"] == "physical", "probe belongs to Linux desktop"
            probe = route["probe"]
            assert set(probe) == {"artifact", "sha256"}
            artifact = Path(probe["artifact"])
            assert "\\" not in probe["artifact"] and ":" not in probe["artifact"]
            assert not artifact.is_absolute() and ".." not in artifact.parts and artifact.suffix == ".json"
            assert re.fullmatch(r"[0-9a-f]{64}", probe["sha256"]), "probe digest required"
        if route["kind"] == "simulator":
            assert provenance.get("device_class") in {"iphone-simulator", "ipad-simulator"}, (
                "simulator form factor mismatch"
            )
        elif route["kind"] == "emulator":
            assert provenance.get("device_class") == "android-emulator", "emulator device class mismatch"
        elif route["kind"] != "physical" and route["runner"] != "windows":
            assert "device_class" not in provenance, "hosted/cloud runner cannot invent a device class"
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
    for device_id in (None, "mac-m1-max"):
        assert {row["provenance"]["device_class"] for row in simulators if row.get("device_id") == device_id} == {
            "iphone-simulator",
            "ipad-simulator",
        }
    budget = document["disk_budget"]
    assert budget["stage23_minimum_free_gb"] >= 150
    assert budget["historical_stage0_minimum_free_gb"] == 100
    assert budget["android_sdk_ndk_avd_estimate_gb"] == [10, 15]
    assert budget["android_platforms_closure_gb"] >= 17.75
    assert budget["ios_runtime_budget"].strip() and budget["note"].strip()


def test_host_matrix_is_complete_and_consistent_with_device_registry():
    validate_hosts(tomllib.loads(HOSTS.read_text(encoding="utf-8")))


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
    document = copy.deepcopy(tomllib.loads(HOSTS.read_text(encoding="utf-8")))
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
    body = SCRIPT.read_text(encoding="utf-8").split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
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
    assert result.returncode == 3, result.stderr
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
    assert result.returncode == 3, result.stderr
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
    body = SCRIPT.read_text(encoding="utf-8").split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
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
    assert result["status"] == {"valid": "passed", "skipped": "unavailable", "cleanup-failed": "cleanup-failed"}.get(
        mutation, "failed"
    )


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


@pytest.mark.parametrize(
    ("route_id", "updates", "reason"),
    [
        ("macos-owner", {"runner": "unavailable"}, "unavailable runner/status mismatch"),
        (
            "windows-physical-x64",
            {
                "runner": "macos",
                "device_id": "mac-m1-max",
                "status": "available",
                "provenance": {"device_class": "mac-host"},
                "blocked_by": [],
            },
            "runner platform/kind mismatch",
        ),
        (
            "linux-devcontainer-automation",
            {
                "kind": "physical",
                "device_id": "mac-m1-max",
                "provenance": {"device_class": "mac-host"},
                "evidence_classes": ["assistive-technology", "physical-input-ime"],
            },
            "runner platform/kind mismatch",
        ),
        (
            "linux-desktop",
            {
                "runner": "macos-hosted",
                "device_id": "mac-m1-max",
                "kind": "hosted",
                "status": "available",
                "blocked_by": [],
                "provenance": {"device_class": "mac-host"},
            },
            "runner platform/kind mismatch",
        ),
        ("linux-desktop", {"device_id": "mac-m1-max"}, "device platform mismatch"),
        ("ios-iphone-current", {"provenance": {"device_class": "ipad-current"}}, "physical device class mismatch"),
        (
            "android-api29-vendor-a",
            {"provenance": {"device_class": "android-api29-vendor-a"}},
            "physical device class mismatch",
        ),
        ("ios-iphone-owner", {"device_id": "iphone-current"}, "device platform mismatch"),
        (
            "linux-devcontainer-automation",
            {"device_id": "linux-fractal-north"},
            "hosted/cloud runner cannot claim a device",
        ),
        ("linux-desktop", {"blocked_by": ["ui0-source-inventory-2026-09-21"]}, "unknown PLAN item"),
    ],
)
def test_runner_device_and_platform_relabelling_cannot_promote_evidence(route_id, updates, reason):
    document = tomllib.loads(HOSTS.read_text(encoding="utf-8"))
    next(route for route in document["routes"] if route["id"] == route_id).update(updates)
    with pytest.raises(AssertionError, match=reason):
        validate_hosts(document)


def test_route_blockers_follow_the_actual_host_lane():
    routes = {route["id"]: route for route in tomllib.loads(HOSTS.read_text(encoding="utf-8"))["routes"]}
    assert set(routes["android-emulator-owner"]["blocked_by"]) == {"tooling-android-sdk-ndk", "ui-1-android-shell"}
    assert set(routes["android-emulator-github"]["blocked_by"]) == {"tooling-android-ci-emulator", "ui-1-android-shell"}
    for form_factor in ("iphone", "ipad"):
        assert set(routes[f"ios-{form_factor}-github"]["blocked_by"]) == {
            "platforms-p1-host-ios",
            "qualification-ci-ios",
            "ui-1-ios-shell",
        }
        assert set(routes[f"ios-{form_factor}-owner"]["blocked_by"]) == {
            "tooling-ios-simulator-runtimes",
            "ui-1-ios-shell",
        }
    assert "platforms-p1-host-windows" in routes["windows-x64-ci"]["blocked_by"]
    assert "16 KiB" not in routes["android-emulator-github"]["note"]


@pytest.mark.parametrize("mutation", [None, "absolute", "escape", "wrong-extension", "invalid-digest", "extra-key"])
def test_linux_probe_reference_has_a_bounded_artifact_identity_without_promoting_results(mutation):
    document = tomllib.loads(HOSTS.read_text(encoding="utf-8"))
    desktop = next(route for route in document["routes"] if route["id"] == "linux-desktop")
    probe = {"artifact": "build/linux-desktop-check/report.json", "sha256": "a" * 64}
    if mutation == "absolute":
        probe["artifact"] = "/tmp/report.json"
    elif mutation == "escape":
        probe["artifact"] = "../report.json"
    elif mutation == "wrong-extension":
        probe["artifact"] = "build/report.txt"
    elif mutation == "invalid-digest":
        probe["sha256"] = "unverified"
    elif mutation == "extra-key":
        probe["passed"] = True
    desktop["probe"] = probe
    if mutation is None:
        validate_hosts(document)
        assert desktop["status"] == "unverified"
    else:
        with pytest.raises(AssertionError):
            validate_hosts(document)


@pytest.mark.parametrize("status", ["timeout", "cleanup-failed", "unavailable"])
def test_gui_execution_failure_keeps_its_primary_reason_without_junit(tmp_path, desktop_module, status):
    def execute(name, command, timeout):
        return {"status": status, "reason": "original execution failure"}

    result = desktop_module.gui_trial(REPO, tmp_path, 1, execute)
    assert result["status"] == status
    assert result["reason"] == "original execution failure"


def test_missing_pytest_is_an_unavailable_tool_not_a_failed_gui_trial(tmp_path, desktop_module, monkeypatch):
    monkeypatch.setattr(desktop_module.importlib.util, "find_spec", lambda module: None)

    def unexpected_execution(*args):
        pytest.fail("GUI process must not start without pytest")

    result = desktop_module.gui_trial(REPO, tmp_path, 1, unexpected_execution)
    assert result == {"status": "unavailable", "reason": "missing Python module: pytest"}


def test_kde_probes_preserve_per_output_and_global_scale_observations(tmp_path, desktop_module, monkeypatch, capsys):
    commands = {}

    def execute(name, command, timeout, **kwargs):
        commands[name] = command
        return {"status": "observed", "returncode": 0, "excerpt": "Scale: 1.5"}

    monkeypatch.setattr(desktop_module, "run", execute)
    monkeypatch.setattr(desktop_module.platform, "system", lambda: "Linux")
    monkeypatch.setenv("QT_SCREEN_SCALE_FACTORS", "DP-1=1.5;HDMI-1=2")
    monkeypatch.setattr(sys, "argv", ["probe", str(REPO), "--probe-only", "--artifacts", str(tmp_path)])
    assert desktop_module.main() == 3
    report = json.loads(capsys.readouterr().out)
    assert report["session"]["QT_SCREEN_SCALE_FACTORS"] == "DP-1=1.5;HDMI-1=2"
    assert commands["kde-output-scales"] == ["kscreen-doctor", "-o"]
    for version in (5, 6):
        assert commands[f"kde{version}-global-scale"] == [
            f"kreadconfig{version}",
            "--file",
            "kdeglobals",
            "--group",
            "KScreen",
            "--key",
            "ScaleFactor",
        ]
        assert report["probes"][f"kde{version}-global-scale"]["excerpt"] == "Scale: 1.5"
    assert report["physical_qualification"] is False
