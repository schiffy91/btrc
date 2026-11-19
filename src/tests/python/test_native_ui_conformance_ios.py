"""The GUI conformance suite's iOS and iPadOS rows: built on a Mac, run on simulators.

The suite (src/tests/native/gui/conformance) is compiled for the simulator
through both compilers, plain and sanitized, and linked, through its native
plan, into an app: the shim provider's UIKit entry (src/stdlib/GUI/IOS),
the suite's own probe (conformance/probes/ios) and wgpu-native's pinned
static library (tools/target_hosts/ios/gui.py; nothing fetched but that
pinned archive). Each case then runs as its own process of the installed
app on one iPhone and one iPad simulator. The probe's input is real: the
driver starts the host's injector for the device
(tools/target_hosts/ios/simhid.m), and a touch, a key and a wheel reach the
app through the simulated device's own HID service.

On the iPad the cases also run with the program's windows in a second scene
of the app, and in a scene made as narrow as a phone's (a compact width,
which is what a split view gives an app): the probe drags the corner of the
scene's window, as a person would, while the first of an app's cases with a
window shows it, and the app's other cases run in the scene that left. Simulator results are never
physical-device evidence, and the installed runtime is not the iOS 17 floor,
which the build targets.

The rows boot simulators and send them input, so they run where they are
asked for: BTRC_IOS_UI_DEVICES names the device classes ("iphone,ipad").
BTRC_IOS_UI_EVIDENCE names a directory that receives every case's output.
"""

import os
import re
import tomllib
from pathlib import Path

import pytest

from src.tests.python import test_native_ui_shell_windows as shell
from src.tests.python.ios_simulator_fixtures import FRONTENDS, MODES, simulators  # noqa: F401

REPO = Path(__file__).resolve().parents[3]
SUITE = REPO / "src/tests/native/gui/conformance"
CASES = tomllib.loads((SUITE / "cases.toml").read_text(encoding="utf-8"))["case"]
NAMES = [case["name"] for case in CASES]
NEEDS = {case["name"]: case["needs"] for case in CASES if "needs" in case}
# What the UIKit provider has of what a case may need: a web view and a probe
# that answers a modal, and no FreeType (the iOS SDK does not carry it). A
# tablet has a pointer and its wheel; a phone has neither.
HAS = {"iphone": {"web", "modal"}, "ipad": {"web", "modal", "wheel"}}
# One worker owns the simulator: a device is booted, installed on and sent input by one process.
pytestmark = pytest.mark.xdist_group(name="ios_ui")
# Cases that put no window on show, and so have no scene to speak of: every other case's
# scene is the one its row asks for, and the provider and the probe say so.
WINDOWLESS = {
    "app.host",
    "app.post",
    "app.postAfter",
    "app.publisher",
    "app.run",
    "app.schedule",
    "button.state",
    "container.tree",
    "indicator.state",
    "label.text",
    "select.items",
    "select.options",
    "slider.state",
    "text.raster",
    "textfield.state",
    "view.fitting",
}


def applicable(device_class):
    return [name for name in NAMES if name not in NEEDS or NEEDS[name] in HAS[device_class]]


def rows():
    """Every case of every device class it applies to, the phone's first: one simulator is booted at a time."""
    return [
        pytest.param(name, device_class, id=f"{name}-{device_class}")
        for device_class in ("iphone", "ipad")
        for name in applicable(device_class)
    ]


def run(simulators, device_class, frontend, sanitized, request, argument, scene="first"):  # noqa: F811
    """One process of the suite's app on the simulator of this class: (status, stdout, stderr)."""
    compact = scene == "compact"
    runner = simulators.runner(
        device_class,
        "conformance",
        SUITE / "Main.btrc",
        frontend,
        sanitized,
        request,
        variant="compact" if compact else "",
        windowed=compact,
    )
    if not hasattr(runner, "web"):
        runner.web = runner.put(SUITE / "web", "web")
    environment = {
        "BTRC_UI_PRIVATE_SESSION": "1",
        "BTRC_CONFORMANCE_HID": str(simulators.port),
        "BTRC_CONFORMANCE_WEB": runner.web,
        "ASAN_OPTIONS": "detect_leaks=0",
        "UBSAN_OPTIONS": "halt_on_error=1",
    }
    if scene == "second":
        environment["BTRC_SHIM_SCENE"] = "second"
    if device_class == "ipad":
        # A tablet keeps the size a scene was left at: every row says which it runs in.
        environment["BTRC_CONFORMANCE_SCENE"] = "compact" if compact else "whole"
    # A finger a failed case left down would be down for this one too.
    assert simulators.inject("RELEASE").startswith("OK"), "simhid could not lift the finger"
    if compact and not hasattr(runner, "changes"):
        # The system keeps the size an app's scene was left at, by the app's name, beyond the
        # app itself. An app's compact rows start from the whole screen, so that the first of
        # them with a window sees its size class change while that window shows (check).
        whole = runner.run(["window.state"], environment | {"BTRC_CONFORMANCE_SCENE": "whole"}, 180)
        assert "probe: the scene is the whole screen" in whole[2], "".join(whole[1:])
        runner.changes = 0
    result = runner.run([argument], environment, 180)
    if compact and argument not in WINDOWLESS:
        dragged = re.search(r"probe: the scene is compact \(.*\) after (\d+) drags", result[2])
        runner.changes += 1 if dragged and int(dragged.group(1)) else 0
        # Every row after the first runs in the scene that row left compact.
        assert runner.changes == 1, (
            f"the scene's size class did not change once, in the first of the app's rows: {result[2]}"
        )
    return result


def check(simulators, request, name, device_class, frontend, sanitized, scene):  # noqa: F811
    status, stdout, stderr = run(simulators, device_class, frontend, sanitized, request, name, scene)
    where = simulators.host.provenance()
    report = f"{name} on {where['device']}, {where['os_build']}, {scene} scene ({frontend}, {MODES[sanitized]})\n"
    report += stdout + stderr
    evidence = os.environ.get("BTRC_IOS_UI_EVIDENCE")
    if evidence:
        Path(evidence).mkdir(parents=True, exist_ok=True)
        label = f"{device_class}-{scene}-{shell.FRONTENDS[frontend]}-{MODES[sanitized]}-{name}.txt"
        (Path(evidence) / label).write_text(report, encoding="utf-8")
    assert status == 0, report
    assert "ERROR: AddressSanitizer" not in stderr and "runtime error:" not in stderr, report
    assert stdout.splitlines()[-2:] == [f"CASE {name} PASS", "CONFORMANCE ran=1 failed=0"], report
    # The probe ends a program whose scene is not the one asked for.
    assert "probe: the scene would not become" not in stderr, report
    if name in WINDOWLESS:
        return
    if scene == "second":
        # The provider says so when the system gave the program a second scene to live in.
        assert "the program's windows live in a second scene (2 connected)" in stderr, report
    if device_class == "ipad":
        wanted = "compact" if scene == "compact" else "the whole screen"
        assert f"probe: the scene is {wanted}" in stderr, report


def test_the_ios_program_lists_exactly_the_recorded_cases(simulators, request):  # noqa: F811
    status, stdout, stderr = run(simulators, "iphone", "python", False, request, "--list")
    assert status == 0, stderr
    # The font face case is FreeType's, which this platform's build leaves out (btrc.toml, Fonts.NoCases).
    assert sorted(stdout.split()) == sorted(name for name in NAMES if NEEDS.get(name) != "freetype")


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize(("name", "device_class"), rows())
def test_ios_conformance_case(simulators, request, name, device_class, frontend, sanitized):  # noqa: F811
    check(simulators, request, name, device_class, frontend, sanitized, "first")


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
@pytest.mark.parametrize("name", applicable("ipad"))
def test_ipad_conformance_case_in_a_second_scene(simulators, request, name, frontend, sanitized):  # noqa: F811
    check(simulators, request, name, "ipad", frontend, sanitized, "second")


# One app's rows at a time: one app's scene is a window at a time (ios_simulator_fixtures.Simulators.runner).
@pytest.mark.parametrize("name", applicable("ipad"))
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("frontend", FRONTENDS)
def test_ipad_conformance_case_in_a_compact_scene(simulators, request, name, frontend, sanitized):  # noqa: F811
    check(simulators, request, name, "ipad", frontend, sanitized, "compact")
