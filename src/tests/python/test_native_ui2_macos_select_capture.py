"""Native Select admission through public menu, key and accessibility actions."""

import json
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.macos_gui
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_select_capture(native_project, native_compile, gui_provider_root, sanitized):
    fixture = "UI2MacOSSelectCapture"
    source, _, _ = native_project
    package = source.parent.parent
    manifest = package / "btrc.toml"
    (package / "SelectCapture.h").write_text("#import <AppKit/AppKit.h>\n")
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "SelectCapture.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSApplication sharedApplication]"]\n'
    )
    root = Path(__file__).resolve().parents[3]
    for suffix in ("h", "m"):
        name = f"{fixture}.{suffix}"
        (package / name).write_text((root / "src/tests/native/gui/ui2/probes/macos" / name).read_text())
    symbols = [
        "+[BTRCUI2SelectCaptureProbe host:]",
        "+[BTRCUI2SelectCaptureProbe finish:]",
        "+[BTRCUI2SelectCaptureProbe choose:index:]",
        "+[BTRCUI2SelectCaptureProbe key:index:]",
        "+[BTRCUI2SelectCaptureProbe press:legacy:pick:]",
        "+[BTRCUI2SelectCaptureProbe cancel:]",
        "+[BTRCUI2SelectCaptureProbe item:index:]",
        "+[BTRCUI2SelectCaptureProbe state:index:]",
        "+[BTRCUI2SelectCaptureProbe notifications:expected:]",
        "+[BTRCUI2SelectCaptureProbe observe:]",
        "+[BTRCUI2SelectCaptureProbe refusedOpening:route:]",
        "+[BTRCUI2SelectCaptureProbe cancelledOpening:route:]",
        "+[BTRCUI2SelectCaptureProbe nestedOpening:refused:]",
        "+[BTRCUI2SelectCaptureProbe failedSuperclass:]",
    ]
    manifest.write_text(
        manifest.read_text() + f'\n[[native.bindings]]\nmodule = "Main"\nheader = "{fixture}.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        f"symbols = {json.dumps(symbols)}\n"
        f'[[native.sources]]\npath = "{fixture}.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    source.write_text((root / "src/tests/native/gui/ui2/probes/macos" / f"{fixture}.btrc").read_text())
    plan = package / "Select.link.json"
    result = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    generated = package / "Select.c"
    generated.write_text(result.c_source)
    executable = package / "Select"

    def runner(command, **kwargs):
        flags = ["-O1"] if Path(command[0]).name in {"clang", "clang++"} else []
        if flags and sanitized:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
        return subprocess.run([command[0], *flags, *command[1:]], env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=runner).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    ran = subprocess.run(
        [str(executable)],
        env=apple_environment() | {"BTRC_GUI_BACKGROUND": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "PASS: macOS native selection admission and accessibility ownership" in ran.stdout
