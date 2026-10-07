"""AppKit shell observations; native traversal gaps stay explicit in the artifact."""

import copy
import json
import math
import sys

import pytest

from src.tests.python.native_ui_shell_fixtures import ROOT, exercise_shell, macos_private_survivors

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
        assert (
            set(("fixture_id", "native_class", "role", "label", "value", "focused", "frame", "children")) <= node.keys()
        ), node
        assert node["fixture_id"] in {*CONTROL_IDS, "other"}
        assert isinstance(node["native_class"], str) and node["native_class"]
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
    # AppKit's retained field-editor descendants differ between OS releases.
    # A separate native process measures the same lifecycle without BTRC.
    # Neither growing control retention nor extra BTRC classes/instances is
    # allowed; counts alone cannot excuse a different private object.
    baseline = observations.get("appkit_control")
    assert isinstance(baseline, dict)
    assert baseline["kind"] == "public-appkit-only; no BTRC runtime/provider or GPU proof"
    assert len(baseline["teardown"]) == len(baseline["private_classes"]) == 100
    assert [row[0] for row in baseline["teardown"]] == list(range(1, 101))
    assert all(len(row) == 3 and row[1] == 0 for row in baseline["teardown"])
    private_classes = observations.get("private_classes")
    assert isinstance(private_classes, list) and len(private_classes) == 100
    allowance = baseline["private_classes"][0]
    for rows, counts in (
        (baseline["private_classes"], [row[2] for row in baseline["teardown"]]),
        (private_classes, [int(row[1]) for row in teardown]),
    ):
        for classes, count in zip(rows, counts, strict=True):
            assert isinstance(classes, dict)
            assert all(
                isinstance(name, str) and name and type(value) is int and value > 0 for name, value in classes.items()
            )
            assert sum(classes.values()) == count
            assert all(value <= allowance.get(name, 0) for name, value in classes.items()), (classes, allowance)
    assert type(observations["private_objects"]) is int
    assert observations["private_objects"] == int(teardown[-1][1])
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
        for identity, role in (("field", "AXTextField"), ("button", "AXButton"), ("scroll", "AXScrollArea")):
            assert any(node["fixture_id"] == identity and node["role"] == role for node in nodes), (identity, role)
        assert any(
            node["fixture_id"] == "button" and node["role"] == "AXButton" and node["label"] == "Commit"
            for node in nodes
        ), "The fixture's Commit button is absent from the accessibility tree"
        controls = probe["native_controls"]
        assert [control["fixture_id"] for control in controls] == list(CONTROL_IDS)
        for control in controls:
            _frame(control["frame"])
            assert type(control["ax_exposed"]) is type(control["is_accessibility_element"]) is bool
            assert isinstance(control["native_class"], str) and control["native_class"]
        keys = probe["key_views"]
        assert keys["field_accepted"] is keys["restored"] is True
        assert type(keys["full_keyboard_access"]) is bool
        assert len(keys["tab_context"]) == 3
        for context in keys["tab_context"]:
            assert type(context["application_active"]) is type(context["window_key"]) is bool
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
    delivery_context = all(
        context["application_active"] and context["window_key"] for keys in key_views for context in keys["tab_context"]
    )
    traversed = delivery_context and all(keys["tab_order"] == list(CONTROL_IDS) for keys in key_views)
    focusable = delivery_context and all(row["direct_focus"] and row["tab_reached"] for row in gpu_status)
    return {
        "schema": "btrc.ui1.macos-shell/1",
        "cycles": 100,
        "gpu_frames": 100,
        "fresh_process_restores": 100,
        "provider_survivors": 0,
        "registration_survivors": 0,
        "teardown": teardown,
        "private_objects": observations["private_objects"],
        "private_classes": private_classes,
        "appkit_control": baseline,
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
        "limits": (
            "In-process AppKit observations; Tab activation/key-window context is not a delivery acknowledgement "
            "or a causal explanation for unchanged focus. No external AX trust, VoiceOver, physical GPU timing or provider fix."
        ),
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
    def node(role, identity="other", native_class="NSView", label=None):
        return {
            "fixture_id": identity,
            "native_class": native_class,
            "role": role,
            "label": label,
            "value": "",
            "focused": False,
            "frame": [0, 0, 100, 20],
            "children": [],
        }

    tree = node("AXWindow")
    tree["children"] = [
        node("AXTextField", "field", "NSTextFieldCell"),
        node("AXButton", "button", "NSButtonCell", "Commit"),
        node("AXScrollArea", "scroll", "NSScrollView"),
        *[node("AXButton", native_class="NSAccessibilityScrollerPart") for _ in range(4)],
        *[
            node("AXButton", native_class=name)
            for name in ("_NSThemeCloseWidgetCell", "_NSThemeZoomWidgetCell", "_NSThemeWidgetCell")
        ],
    ]
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
        "tab_context": [{"application_active": True, "window_key": True} for _ in range(3)],
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
        "teardown": [["0", "1", "0"] for _ in range(100)],
        "probes": [copy.deepcopy(probe) for _ in range(100)],
        "private_objects": 1,
        "private_classes": [{"AppKitHelper": 1} for _ in range(100)],
        "appkit_control": {
            "kind": "public-appkit-only; no BTRC runtime/provider or GPU proof",
            "teardown": [[cycle + 1, 0, 1] for cycle in range(100)],
            "private_classes": [{"AppKitHelper": 1} for _ in range(100)],
        },
    }


def test_macos_shell_observation_keeps_native_gaps_and_private_objects_explicit():
    observed = _observation_fixture()
    report = summarize_macos_shell(observed)
    assert report["appkit_control"] == observed["appkit_control"]
    assert report["key_view_traversal"]["status"] == report["gpu_focusability"]["status"] == "gap"
    assert report["provider_survivors"] == report["registration_survivors"] == 0
    assert report["private_objects"] == 1
    assert len(report["gpu_focusability"]["cycles"]) == len(report["teardown"]) == 100


@pytest.mark.parametrize(
    "defect",
    [
        "missing_field",
        "missing_scroll",
        "wrong_control_identity",
        "wrong_control_role",
        "wrong_button_label",
        "missing_value",
        "truncated",
        "nan_frame",
        "provider_leak",
        "callback_leak",
        "private_survivor_growth",
        "private_summary_mismatch",
        "missing_control",
        "partial_control",
        "control_owned_leak",
        "control_growth",
        "unknown_private_class",
        "extra_private_instance",
        "missing_private_classes",
        "private_class_count_mismatch",
        "partial_cycles",
        "missing_gpu",
        "inconsistent_focus",
        "missing_tab_context",
        "invalid_tab_context",
    ],
)
def test_macos_shell_observation_rejects_incomplete_or_contradictory_proof(defect):
    observed = _observation_fixture()
    probe = observed["probes"][37]
    if defect == "missing_field":
        probe["accessibility"]["children"].pop(0)
    elif defect == "missing_scroll":
        probe["accessibility"]["children"].pop(2)
    elif defect == "wrong_control_identity":
        probe["accessibility"]["children"][1]["fixture_id"] = "other"
    elif defect == "wrong_control_role":
        probe["accessibility"]["children"][1]["role"] = "AXGroup"
    elif defect == "wrong_button_label":
        probe["accessibility"]["children"][1]["label"] = "Unrelated"
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
    elif defect == "private_survivor_growth":
        observed["teardown"] = [["0", str(cycle + 1), "0"] for cycle in range(100)]
        observed["private_objects"] = 100
    elif defect == "private_summary_mismatch":
        observed["private_objects"] = 0
    elif defect == "missing_control":
        del observed["appkit_control"]
    elif defect == "partial_control":
        observed["appkit_control"]["teardown"].pop()
    elif defect == "control_owned_leak":
        observed["appkit_control"]["teardown"][37][1] = 1
    elif defect == "control_growth":
        observed["appkit_control"]["teardown"][37][2] = 2
        observed["appkit_control"]["private_classes"][37]["AppKitHelper"] = 2
    elif defect == "unknown_private_class":
        observed["private_classes"][37] = {"UnexpectedHelper": 1}
    elif defect == "extra_private_instance":
        observed["teardown"][37][1] = "2"
        observed["private_classes"][37]["AppKitHelper"] = 2
    elif defect == "missing_private_classes":
        del observed["private_classes"]
    elif defect == "private_class_count_mismatch":
        observed["private_classes"][37] = {}
    elif defect == "partial_cycles":
        observed["probes"].pop()
    elif defect == "missing_gpu":
        probe["native_controls"].pop()
    elif defect == "inconsistent_focus":
        probe["key_views"]["gpu_make_first_responder"] = True
    elif defect == "missing_tab_context":
        probe["key_views"]["tab_context"].pop()
    elif defect == "invalid_tab_context":
        probe["key_views"]["tab_context"][0]["window_key"] = "true"
    with pytest.raises(AssertionError):
        summarize_macos_shell(observed)


@pytest.mark.parametrize("count", [0, 1, 7])
def test_macos_shell_private_allowance_comes_from_native_control(count):
    observed = _observation_fixture()
    classes = {f"AppKitHelper{index}": 1 for index in range(count)}
    observed["private_objects"] = count
    observed["teardown"] = [["0", str(count), "0"] for _ in range(100)]
    observed["private_classes"] = [classes.copy() for _ in range(100)]
    observed["appkit_control"]["teardown"] = [[cycle + 1, 0, count] for cycle in range(100)]
    observed["appkit_control"]["private_classes"] = [classes.copy() for _ in range(100)]
    assert summarize_macos_shell(observed)["private_objects"] == count


def test_macos_private_survivors_keeps_multiplicity_and_cycle_boundaries():
    stderr = "unrelated framework diagnostic\n" + "\n".join(
        f"SHELL survivor scope=appkit-private class={name} identity=0x{index:x}"
        for index, name in enumerate(["Editor", "Editor", "Clip", "Clip"])
    )
    assert macos_private_survivors(stderr, [0, 3, 1]) == [{}, {"Editor": 2, "Clip": 1}, {"Clip": 1}]
    for counts in ([3], [3, 2], [-1, 5]):
        with pytest.raises(AssertionError):
            macos_private_survivors(stderr, counts)


def test_macos_shell_observation_rejects_missing_commit_among_window_and_scroller_buttons():
    observed = _observation_fixture()
    tree = observed["probes"][37]["accessibility"]
    tree["children"] = [node for node in tree["children"] if node["fixture_id"] != "button"]
    buttons = [node for node in _ax_nodes(tree) if node["role"] == "AXButton"]
    assert len(buttons) == 7 and all(node["fixture_id"] == "other" for node in buttons)
    with pytest.raises(AssertionError):
        summarize_macos_shell(observed)


@pytest.mark.parametrize("context_field", ["application_active", "window_key"])
def test_macos_shell_observation_keeps_inactive_tab_context_a_gap(context_field):
    observed = _observation_fixture()
    for probe in observed["probes"]:
        probe["key_views"].update(tab_order=list(CONTROL_IDS), gpu_make_first_responder=True, gpu_responder="gpu")
    assert summarize_macos_shell(observed)["key_view_traversal"]["status"] == "passed"
    observed["probes"][37]["key_views"]["tab_context"][1][context_field] = False
    report = summarize_macos_shell(observed)
    assert report["key_view_traversal"]["status"] == report["gpu_focusability"]["status"] == "gap"
