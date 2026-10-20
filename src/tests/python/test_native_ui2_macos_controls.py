"""Native macOS UI2 control behavior, without presenting a window."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize("fixture", ["UI2MacOSSlider", "UI2MacOSSelect"])
def test_macos_ui2_controls(native_project, native_compile, gui_provider_root, sanitized, fixture):
    source, _, _ = native_project
    package = source.parent.parent
    manifest = package / "btrc.toml"
    (package / "SliderProbe.h").write_text("#import <AppKit/AppKit.h>\n")
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "SliderProbe.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSApplication sharedApplication]", "-[NSSlider doubleValue]", "-[NSSlider setDoubleValue:]", '
        '"+[NSWindow new]", "-[NSWindow setReleasedWhenClosed:]", "-[NSWindow setContentSize:]", '
        '"-[NSWindow setContentView:]", "-[NSWindow windowNumber]", "-[NSWindow close]", '
        '"+[NSEvent mouseEventWithType:location:modifierFlags:timestamp:windowNumber:context:eventNumber:clickCount:pressure:]", '
        '"+[NSEvent keyEventWithType:location:modifierFlags:timestamp:windowNumber:context:characters:charactersIgnoringModifiers:isARepeat:keyCode:]"]\n'
    )
    root = Path(__file__).resolve().parents[3]
    for suffix in ("h", "m"):
        name = f"{fixture}.{suffix}"
        (package / name).write_text((root / "src/tests/native/gui/ui2/probes/macos" / name).read_text())
    symbols = (
        '["+[BTRCUI2SliderProbe choose:value:]", "+[BTRCUI2SliderProbe increment:]", "+[BTRCUI2SliderProbe rejectInvalid:]", "+[BTRCUI2SliderProbe decrement:]"]'
        if fixture == "UI2MacOSSlider"
        else '["+[BTRCUI2SelectProbe begin:]", "+[BTRCUI2SelectProbe highlight:index:]", '
        '"+[BTRCUI2SelectProbe choose:index:]", "+[BTRCUI2SelectProbe end:]", '
        '"+[BTRCUI2SelectProbe item:index:]", "+[BTRCUI2SelectProbe dispatchOld:button:]", "+[BTRCUI2SelectProbe presentation:title:count:selected:]"]'
    )
    manifest.write_text(
        manifest.read_text() + f'\n[[native.bindings]]\nmodule = "Main"\nheader = "{fixture}.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        f"symbols = {symbols}\n"
        f'[[native.sources]]\npath = "{fixture}.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    source.write_text((root / "src/tests/native/gui/ui2/probes/macos" / f"{fixture}.btrc").read_text())
    plan = package / "Slider.link.json"
    result = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    generated = package / "Slider.c"
    generated.write_text(result.c_source)
    executable = package / "Slider"

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
    marker = (
        "PASS: UI2 macOS slider model and semantic controls"
        if fixture == "UI2MacOSSlider"
        else "PASS: UI2 macOS keyed selection and native callback settlement"
    )
    assert marker in ran.stdout
