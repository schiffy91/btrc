"""docs/qualification/devices.toml maps every physical gate to a device or an unavailable record."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
REGISTRY = REPO / "docs/qualification/devices.toml"
ROADMAP = REPO / "PLAN.md"
STATUSES = {"available", "unverified", "unavailable"}
REQUIRED_FIELDS = {"id", "class", "status", "name", "gates"}
# The device classes platform-parity.md (P6, P7) and native-ui-parity.md (UI10)
# require; deleting one from the registry must fail here, not pass silently.
REQUIRED_CLASSES = {
    "windows-x64",
    "windows-arm64",
    "iphone-floor",
    "iphone-current",
    "ipad-floor",
    "ipad-current",
    "android-floor",
    "android-current-16k",
    "refresh-120hz",
    "multi-monitor-scaled",
    "usb-audio-interface",
    "guitar-di",
    "quad-cortex",
}
# The stages the roadmap (PLAN.md) lists as carrying physical gates.
PHYSICAL_STAGES = {23, 39, 40, 41, 42, 43}


def _registry() -> dict:
    return tomllib.loads(REGISTRY.read_text(encoding="utf-8"))


def _plan_items() -> dict[str, int]:
    """Every item id in the roadmap's stage sections, with the stage that lists it."""

    items: dict[str, int] = {}
    stage = None
    for line in ROADMAP.read_text(encoding="utf-8").splitlines():
        heading = re.match(r"^### Stage (\d+):", line)
        if heading:
            stage = int(heading.group(1))
        elif line.startswith("## "):
            stage = None
        elif stage is not None and line.lstrip().startswith("- "):
            for item in re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", line):
                items.setdefault(item, stage)
    return items


REGISTRY_DATA = _registry()
DEVICES = REGISTRY_DATA["device"]


def test_registry_header() -> None:
    assert REGISTRY_DATA["schema"] == "btrc.qualification.devices/1"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", REGISTRY_DATA["recorded_at"])
    assert REGISTRY_DATA["host"] == "Apple M1 Max, 8P+2E, 64 GiB, macOS 27.0"


@pytest.mark.parametrize("device", DEVICES, ids=[device.get("id", "?") for device in DEVICES])
def test_every_device_row_is_complete(device: dict) -> None:
    missing = REQUIRED_FIELDS - device.keys()
    assert not missing, f"{device.get('id')}: missing {sorted(missing)}"
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", device["id"])
    assert device["status"] in STATUSES
    assert device["class"] in REGISTRY_DATA["device_class"]
    assert device["name"].strip()
    assert device["gates"] and len(set(device["gates"])) == len(device["gates"])
    if device["status"] in {"unavailable", "unverified"}:
        # D8: a missing device names the provisioning or account item that blocks it.
        assert device.get("blocked_by"), f"{device['id']}: no blocked_by"
        assert device.get("reason", "").strip(), f"{device['id']}: no reason"
    else:
        assert "blocked_by" not in device, f"{device['id']}: available but blocked"
    if device["status"] == "unverified":
        assert device.get("verify", "").strip(), f"{device['id']}: no read-only verify command"


def test_device_ids_are_unique() -> None:
    ids = [device["id"] for device in DEVICES]
    assert len(ids) == len(set(ids))


def test_every_referenced_gate_is_a_plan_item() -> None:
    items = _plan_items()
    referenced = set(REGISTRY_DATA["physical_gates"])
    for device in DEVICES:
        referenced |= set(device["gates"]) | set(device.get("blocked_by", []))
    unknown = sorted(referenced - items.keys())
    assert not unknown, f"not roadmap (PLAN.md) item ids: {unknown}"


def test_physical_gates_sit_in_their_recorded_stage() -> None:
    items = _plan_items()
    for gate, stage in REGISTRY_DATA["physical_gates"].items():
        assert stage in PHYSICAL_STAGES, gate
        assert items[gate] == stage, f"{gate}: PLAN.md lists it in Stage {items[gate]}, not {stage}"


def test_every_physical_gate_maps_to_a_device() -> None:
    carried = {gate for device in DEVICES for gate in device["gates"]}
    unmapped = sorted(set(REGISTRY_DATA["physical_gates"]) - carried)
    assert not unmapped, f"physical gates with no device or unavailable record: {unmapped}"


def test_every_required_device_class_has_a_row() -> None:
    classes = set(REGISTRY_DATA["device_class"])
    assert classes >= REQUIRED_CLASSES
    represented = {device["class"] for device in DEVICES}
    assert not (classes - represented), f"device classes with no row: {sorted(classes - represented)}"


def test_no_unowned_hardware_is_recorded_as_available() -> None:
    # D8: no procurement. The only hardware that exists is the Mac; everything
    # else is unavailable or still to be verified there.
    hardware = {"mac-host", "signing-identity"}
    available = {device["id"] for device in DEVICES if device["status"] == "available"}
    assert all(device["class"] in hardware for device in DEVICES if device["id"] in available), (
        f"available rows outside the Mac and its ad-hoc signing: {sorted(available)}"
    )
