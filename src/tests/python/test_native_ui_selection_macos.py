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


@pytest.mark.macos_gui
@pytest.mark.parametrize("sanitize", [False, True])
def test_native_selection_state(native_project, native_compile, gui_provider_root, sanitize):
    source, _sdk, _triple = native_project
    root = source.parent.parent
    source.write_text((PROBES / "NativeSelectionState.btrc").read_text())
    data_root = root / "provider-data"
    shutil.copytree(gui_provider_root, data_root, symlinks=True)
    manifest = data_root / "stdlib/GUI/btrc.toml"
    manifest.write_text(
        manifest.read_text().replace("exports = [", 'exports = ["ControlEventQueue", ', 1) + SELECTION_PROVIDER_BINDINGS
    )
    (root / "btrc.toml").write_text('manifest-version = 1\n[package]\nname = "ui2MacOSSelection"\n')
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
    assert "UI2 native selection owns keyed snapshots and preserves rejected models" in completed.stdout
