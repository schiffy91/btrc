"""AppKit shell observations; native traversal gaps stay explicit in the artifact."""

import copy
import json
import math
import sys

import pytest

from src.tests.python.native_ui_shell_fixtures import ROOT, exercise_shell

CONTROL_IDS = ("field", "button", "scroll", "gpu")


def _frame(value):
    assert isinstance(value, list) and len(value) == 4, value
    assert all(type(number) in {int, float} and math.isfinite(number) for number in value), value
    assert value[2] >= 0 and value[3] >= 0, value


def _ax_nodes(tree):
    pending, nodes = [tree], []
    while pending:
        node = pending.pop()
        assert isinstance(node, dict) and not node.get("truncated") and not node.get("cycle"), node
        assert set(("role", "label", "value", "focused", "frame", "children")) <= node.keys(), node
        assert node["role"] is None or isinstance(node["role"], str)
        assert node["label"] is None or isinstance(node["label"], str)
        assert node["value"] is None or type(node["value"]) in {str, bool, int, float}
        assert node["focused"] is None or type(node["focused"]) is bool
        if node["frame"] is not None:
            _frame(node["frame"])
        assert isinstance(node["children"], list)
        pending.extend(node["children"])
        nodes.append(node)
        assert len(nodes) <= 512, "AX dump exceeded its bounded tree size"
    return nodes


def summarize_macos_shell(observations):
    """Require actual complete observations before reporting lifecycle or AX proof."""
    assert observations["cycles"] == observations["frames"] == 100, observations
    assert observations["gate_cycles"] is True
    assert observations["native_handles"] == observations["live_registrations"] == 0
    assert observations["fresh_process_restores"] == 100
    teardown = observations["teardown"]
    assert len(teardown) == 100
    assert all(len(row) == 3 and int(row[0]) == int(row[2]) == 0 and int(row[1]) >= 0 for row in teardown)
    probes = observations["probes"]
    assert len(probes) == 100
    key_views, gpu_status, subviews = [], [], []
    for probe in probes:
        assert probe["probe"] == "macos-appkit"
        assert probe["ax_frame_space"] == "AppKit screen points; origin bottom-left"
        assert probe["native_frame_space"] == "window content points; origin bottom-left"
        assert probe["provider_objects"] == 57
        assert type(probe["subview_total"]) is int and probe["subview_total"] >= 56
        nodes = _ax_nodes(probe["accessibility"])
        roles = {node["role"] for node in nodes}
        assert {"AXTextField", "AXButton", "AXScrollArea"} <= roles, roles
        controls = probe["native_controls"]
        assert [control["fixture_id"] for control in controls] == list(CONTROL_IDS)
        for control in controls:
            _frame(control["frame"])
            assert type(control["ax_exposed"]) is type(control["is_accessibility_element"]) is bool
            assert isinstance(control["native_class"], str) and control["native_class"]
        keys = probe["key_views"]
        assert keys["field_accepted"] is keys["restored"] is True
        assert type(keys["full_keyboard_access"]) is bool
        assert len(keys["tab_order"]) == 4 and keys["tab_order"][0] == "field"
        assert all(name in {*CONTROL_IDS, "other"} for name in keys["tab_order"])
        assert len(keys["responder_classes"]) == 4
        assert all(isinstance(name, str) and name for name in keys["responder_classes"])
        assert [control["fixture_id"] for control in keys["controls"]] == list(CONTROL_IDS)
        for control in keys["controls"]:
            assert type(control["accepts_first_responder"]) is type(control["can_become_key_view"]) is bool
            assert control["next_key_view"] in {*CONTROL_IDS, "other"}
            assert control["next_valid_key_view"] in {*CONTROL_IDS, "other"}
        assert type(keys["gpu_make_first_responder"]) is bool
        assert keys["gpu_responder"] in {*CONTROL_IDS, "other"}
        assert keys["gpu_make_first_responder"] == (keys["gpu_responder"] == "gpu")
        key_views.append(keys)
        gpu_status.append(
            {
                "cycle": len(gpu_status) + 1,
                "ax_exposed": controls[3]["ax_exposed"],
                "is_accessibility_element": controls[3]["is_accessibility_element"],
                "accepts_first_responder": keys["controls"][3]["accepts_first_responder"],
                "direct_focus": keys["gpu_make_first_responder"],
                "tab_reached": "gpu" in keys["tab_order"],
            }
        )
        subviews.append(probe["subview_total"])
    traversed = all(keys["tab_order"] == list(CONTROL_IDS) for keys in key_views)
    focusable = all(row["direct_focus"] and row["tab_reached"] for row in gpu_status)
    return {
        "schema": "btrc.ui1.macos-shell/1",
        "cycles": 100,
        "gpu_frames": 100,
        "fresh_process_restores": 100,
        "provider_survivors": 0,
        "registration_survivors": 0,
        "teardown": teardown,
        "private_objects": observations["private_objects"],
        "subview_totals": subviews,
        "ax_frame_space": probes[0]["ax_frame_space"],
        "native_frame_space": probes[0]["native_frame_space"],
        "accessibility": probes[0]["accessibility"],
        "native_controls": probes[0]["native_controls"],
        "key_view_traversal": {
            "status": "passed" if traversed else "gap",
            "expected": list(CONTROL_IDS),
            "cycles": key_views,
        },
        "gpu_focusability": {"status": "passed" if focusable else "gap", "cycles": gpu_status},
        "limits": "In-process AppKit observations; no external AX trust, VoiceOver, physical GPU timing or provider fix.",
    }


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_native_shell(tmp_path, request, frontend, sanitized, record_property):
    if sys.platform != "darwin":
        pytest.skip("requires macOS AppKit native shell")
    destination = ROOT / "build/ui-shell" / f"ui1-macos-{frontend}-{'sanitized' if sanitized else 'plain'}.json"
    destination.unlink(missing_ok=True)
    ledger_path = exercise_shell(tmp_path, request, frontend, sanitized, "macos")
    record = json.loads(ledger_path.read_text())
    report = summarize_macos_shell(json.loads(record["evidence"]["observed"]))
    report["provenance"] = record["provenance"]
    report["frontend"] = record["subject"]["frontend"]
    payload = json.dumps(report, sort_keys=True, ensure_ascii=False)
    destination.write_text(payload + "\n")
    # macos.yml already uploads this JUnit. Retain the actual JSON payload, not
    # a path to an unuploaded file; it includes the tree and all 100 cycle rows.
    record_property("ui1_macos_evidence", payload)
    record_property("ui1_macos_key_view_status", report["key_view_traversal"]["status"])
    record_property("ui1_macos_gpu_focusability", report["gpu_focusability"]["status"])


def _observation_fixture():
    def node(role):
        return {"role": role, "label": None, "value": "", "focused": False, "frame": [0, 0, 100, 20], "children": []}

    tree = node("AXWindow")
    tree["children"] = [node(role) for role in ("AXTextField", "AXButton", "AXScrollArea")]
    controls = [
        {
            "fixture_id": name,
            "native_class": "NSView" if name == "gpu" else "NativeControl",
            "ax_exposed": name != "gpu",
            "is_accessibility_element": name != "gpu",
            "frame": [0, 0, 100, 20],
        }
        for name in CONTROL_IDS
    ]
    keys = {
        "field_accepted": True,
        "restored": True,
        "full_keyboard_access": False,
        "tab_order": ["field", "button", "scroll", "field"],
        "responder_classes": ["NSTextView", "NSButton", "NSClipView", "NSTextView"],
        "gpu_make_first_responder": False,
        "gpu_responder": "field",
        "controls": [
            {
                "fixture_id": name,
                "accepts_first_responder": name != "gpu",
                "can_become_key_view": name != "gpu",
                "next_key_view": "field",
                "next_valid_key_view": "field",
            }
            for name in CONTROL_IDS
        ],
    }
    probe = {
        "probe": "macos-appkit",
        "ax_frame_space": "AppKit screen points; origin bottom-left",
        "native_frame_space": "window content points; origin bottom-left",
        "provider_objects": 57,
        "subview_total": 60,
        "accessibility": tree,
        "native_controls": controls,
        "key_views": keys,
    }
    return {
        "cycles": 100,
        "frames": 100,
        "gate_cycles": True,
        "native_handles": 0,
        "live_registrations": 0,
        "fresh_process_restores": 100,
        "teardown": [["0", "3", "0"] for _ in range(100)],
        "probes": [copy.deepcopy(probe) for _ in range(100)],
        "private_objects": 3,
    }


def test_macos_shell_observation_keeps_native_gaps_and_private_objects_explicit():
    report = summarize_macos_shell(_observation_fixture())
    assert report["key_view_traversal"]["status"] == report["gpu_focusability"]["status"] == "gap"
    assert report["provider_survivors"] == report["registration_survivors"] == 0
    assert report["private_objects"] == 3
    assert len(report["gpu_focusability"]["cycles"]) == len(report["teardown"]) == 100


@pytest.mark.parametrize(
    "defect",
    [
        "missing_field",
        "missing_value",
        "truncated",
        "nan_frame",
        "provider_leak",
        "callback_leak",
        "partial_cycles",
        "missing_gpu",
        "inconsistent_focus",
    ],
)
def test_macos_shell_observation_rejects_incomplete_or_contradictory_proof(defect):
    observed = _observation_fixture()
    probe = observed["probes"][37]
    if defect == "missing_field":
        probe["accessibility"]["children"].pop(0)
    elif defect == "missing_value":
        del probe["accessibility"]["value"]
    elif defect == "truncated":
        probe["accessibility"]["children"].append({"truncated": True})
    elif defect == "nan_frame":
        probe["accessibility"]["frame"][0] = float("nan")
    elif defect == "provider_leak":
        observed["teardown"][37][0] = "1"
    elif defect == "callback_leak":
        observed["teardown"][37][2] = "1"
    elif defect == "partial_cycles":
        observed["probes"].pop()
    elif defect == "missing_gpu":
        probe["native_controls"].pop()
    elif defect == "inconsistent_focus":
        probe["key_views"]["gpu_make_first_responder"] = True
    with pytest.raises(AssertionError):
        summarize_macos_shell(observed)
