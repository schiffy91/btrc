"""Native authoritative range model and captured AppKit input."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]
PROBES = ROOT / "src/tests/native/gui/ui2/probes/macos"
RANGE_PROVIDER_BINDINGS = """
# Integrator fragment, append alongside retained NSSlider AppKit declarations.
[[native.bindings]]
module = "MacOS.MacOSSlider"
header = "MacOS/Range.h"
language = "objective-c"
standard = "c11"
symbols = ["+[BTRCMacOSRange range]", "-[BTRCMacOSRange setEventSink:]", "-[BTRCMacOSRange eventSink]", "-[BTRCMacOSRange invalidateTracking]", "-[BTRCMacOSRange projectValue:]", "-[NSView superview]", "-[BTRCMacOSRangeEvents rangeBegin]", "-[BTRCMacOSRangeEvents rangePreview:]", "-[BTRCMacOSRangeEvents rangeEnd:released:]", "-[BTRCMacOSRangeEvents rangeAdjust:count:]", "-[BTRCMacOSRangeEvents rangeAssistive:]", "-[BTRCMacOSRangeEvents rangeEscape]"]
os = ["macos"]

[native.bindings.callbacks."-[BTRCMacOSRange setEventSink:].eventSink"]
interface = "IAppKitRangeEvents"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[BTRCMacOSRange setEventSink:]"
slot-getter = "-[BTRCMacOSRange eventSink]"
methods = ["-[BTRCMacOSRangeEvents rangeBegin]", "-[BTRCMacOSRangeEvents rangePreview:]", "-[BTRCMacOSRangeEvents rangeEnd:released:]", "-[BTRCMacOSRangeEvents rangeAdjust:count:]", "-[BTRCMacOSRangeEvents rangeAssistive:]", "-[BTRCMacOSRangeEvents rangeEscape]"]
activation-failure = "abort"
cancellation = "entry-barrier"

[[native.sources]]
path = "MacOS/Range.m"
language = "objective-c"
standard = "c11"
modules = ["MacOS.MacOSSlider"]
os = ["macos"]
"""


@pytest.mark.macos_gui
@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("NativeRangeState", "PASS: native slider authoritative range and validation"),
        ("NativeRangeEvents", "PASS: native slider captures ordered intents and pointer terminals"),
    ],
)
def test_native_range(native_project, native_compile, gui_provider_root, sanitize, fixture, expected):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((PROBES / f"{fixture}.btrc").read_text())
    data_root = root / "provider-data"
    shutil.copytree(gui_provider_root, data_root, symlinks=True)
    manifest = data_root / "stdlib/GUI/btrc.toml"
    manifest.write_text(
        manifest.read_text().replace("exports = [", 'exports = ["ControlEventQueue", ', 1) + RANGE_PROVIDER_BINDINGS
    )
    (root / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "ui2MacOSRange"\n')
    probe = "RangeProbe" if fixture == "NativeRangeEvents" else "RunLoopProbe"
    shutil.copyfile(PROBES / f"{probe}.btrc", source.parent / f"{probe}.btrc")
    for suffix in ("h", "m"):
        shutil.copyfile(PROBES / f"{probe}.{suffix}", root / f"{probe}.{suffix}")
    symbols = (
        [
            "+[UI2RangeProbe open]",
            "+[UI2RangeProbe close]",
            "+[UI2RangeProbe key:code:repeat:]",
            "+[UI2RangeProbe increment:]",
            "+[UI2RangeProbe decrement:]",
            "+[UI2RangeProbe assistive:value:]",
            "+[UI2RangeProbe drag:fraction:]",
            "+[UI2RangeProbe projected:]",
            "+[UI2RangeProbe probe]",
            "-[UI2RangeProbe setEvents:]",
            "-[UI2RangeProbe events]",
            "-[UI2RangeProbe dragWithEvents:fraction:]",
            "+[UI2RangeProbe escape:]",
            "-[UI2RangeIntervention rangeAction]",
        ]
        if probe == "RangeProbe"
        else ["ui2InitializeAppKit"]
    )
    language = "objective-c" if probe == "RangeProbe" else "c"
    with (root / "btrc.toml").open("a") as manifest:
        manifest.write(
            f'[[native.bindings]]\nmodule = "{probe}"\nheader = "{probe}.h"\nlanguage = "{language}"\nstandard = "c11"\n'
            f"symbols = {json.dumps(symbols)}\n"
        )
    if probe == "RangeProbe":
        with (root / "btrc.toml").open("a") as manifest:
            manifest.write("""
[native.bindings.callbacks."-[UI2RangeProbe setEvents:].events"]
interface = "IUI2RangeIntervention"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[UI2RangeProbe setEvents:]"
slot-getter = "-[UI2RangeProbe events]"
methods = ["-[UI2RangeIntervention rangeAction]"]
activation-failure = "abort"
cancellation = "entry-barrier"
""")
    with (root / "btrc.toml").open("a") as manifest:
        manifest.write(f'[[native.sources]]\npath = "{probe}.m"\nlanguage = "objective-c"\nstandard = "c11"\n')
    plan = root / "Range.link.json"
    compiled = native_compile(source, data_root=data_root, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Range.c"
    generated.write_text(compiled.c_source)
    executable = root / "Range"

    def runner(command, **kwargs):
        flags = ["-O2"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    try:
        completed = subprocess.run(
            [str(executable)], cwd=root, env=apple_environment(), capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired as error:
        for suffix, output in (("stdout", error.stdout), ("stderr", error.stderr)):
            (root / f"run.{suffix}").write_bytes(output if isinstance(output, bytes) else (output or "").encode())
        raise
    (root / "run.stdout").write_text(completed.stdout)
    (root / "run.stderr").write_text(completed.stderr)
    assert completed.returncode == 0, (completed.returncode, completed.stdout, completed.stderr)
    assert expected in completed.stdout
