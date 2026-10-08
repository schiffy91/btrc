"""Native keyed selection model and semantic callback ownership."""

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
SELECTION_PROVIDER_BINDINGS = """
[[native.bindings]]
module = "MacOS.MacOSSelect"
header = "MacOS/Select.h"
language = "objective-c"
standard = "c11"
os = ["macos"]
symbols = [
    "+[BTRCMacOSSelect selection]",
    "-[BTRCMacOSSelect setSemanticEvents:]", "-[BTRCMacOSSelect semanticEvents]",
    "-[BTRCMacOSSelect cancelMenu]", "-[NSView superview]",
    "-[BTRCMacOSSelectEvents shouldBegin]", "-[BTRCMacOSSelectEvents opened]",
    "-[BTRCMacOSSelectEvents candidate:]", "-[BTRCMacOSSelectEvents accepted:]",
    "-[BTRCMacOSSelectEvents ended:]"
]
[native.bindings.callbacks."-[BTRCMacOSSelect setSemanticEvents:].events"]
interface = "IAppKitSelectionEvents"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[BTRCMacOSSelect setSemanticEvents:]"
slot-getter = "-[BTRCMacOSSelect semanticEvents]"
methods = ["-[BTRCMacOSSelectEvents shouldBegin]", "-[BTRCMacOSSelectEvents opened]", "-[BTRCMacOSSelectEvents candidate:]", "-[BTRCMacOSSelectEvents accepted:]", "-[BTRCMacOSSelectEvents ended:]"]
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.sources]]
path = "MacOS/Select.m"
language = "objective-c"
standard = "c11"
modules = ["MacOS.MacOSSelect"]
os = ["macos"]
"""

SELECTION_PROBE_BINDINGS = """
# Test package fragment; GUI already supplies AppKit. No framework row here.
[[native.bindings]]
module = "SelectProbe"
header = "SelectProbe.h"
language = "objective-c"
standard = "c11"
symbols = [
 "+[UI2SelectProbe create]", "-[UI2SelectProbe parent]",
 "-[UI2SelectProbe setTrackingReceiver:]", "-[UI2SelectProbe trackingReceiver]",
 "-[UI2SelectProbe journey:mode:terminal:]", "-[UI2SelectProbe printable:]",
 "-[UI2SelectProbe inside]", "-[UI2SelectProbe timedOut]", "-[UI2SelectProbe opened]",
 "-[UI2SelectProbe highlights]", "-[UI2SelectProbe actions]", "-[UI2SelectProbe close]",
 "-[UI2SelectTrackingReceiver highlighted]"
]
[native.bindings.callbacks."-[UI2SelectProbe setTrackingReceiver:].receiver"]
interface = "IUI2SelectTrackingReceiver"
lifetime = "stored"
failure = "abort"
executor = "caller"
unregister = "-[UI2SelectProbe setTrackingReceiver:]"
slot-getter = "-[UI2SelectProbe trackingReceiver]"
methods = ["-[UI2SelectTrackingReceiver highlighted]"]
activation-failure = "abort"
cancellation = "entry-barrier"
[[native.sources]]
path = "SelectProbe.m"
language = "objective-c"
standard = "c11"
"""


@pytest.mark.macos_gui
@pytest.mark.parametrize("sanitize", [False, True])
@pytest.mark.parametrize(
    "program, expected",
    [
        ("NativeSelectionState", "UI2 native selection owns keyed snapshots and preserves rejected models"),
        ("NativeSelectionEvents", "PASS: native popup input preserves ordered selection and cancellation ownership"),
    ],
)
def test_native_selection_state(native_project, native_compile, gui_provider_root, sanitize, program, expected):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((PROBES / f"{program}.btrc").read_text())
    bindings = ""
    if program == "NativeSelectionEvents":
        shutil.copyfile(PROBES / "SelectProbe.btrc", source.parent / "SelectProbe.btrc")
        for name in ("SelectProbe.h", "SelectProbe.m"):
            shutil.copyfile(PROBES / name, root / name)
        bindings = SELECTION_PROBE_BINDINGS
    data_root = root / "provider-data"
    shutil.copytree(gui_provider_root, data_root, symlinks=True)
    manifest = data_root / "stdlib/GUI/btrc.toml"
    manifest.write_text(
        manifest.read_text().replace("exports = [", 'exports = ["ControlEventQueue", ', 1) + SELECTION_PROVIDER_BINDINGS
    )
    (root / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "ui2MacOSSelection"\n' + bindings)
    plan = root / "Selection.link.json"
    compiled = native_compile(source, data_root=data_root, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = root / "Selection.c"
    generated.write_text(compiled.c_source)
    executable = root / "Selection"

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
