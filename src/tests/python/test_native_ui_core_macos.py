"""UI2 CoreFoundation source behavior through both compilers and the real SDK."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment, run_native_executable
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_ui2_common_mode_source(native_project, native_compile, sanitized):
    source, sdk, triple = native_project
    package = source.parent.parent
    manifest = package / "btrc.toml"
    symbols = [
        "CFRunLoopGetMain",
        "CFRunLoopAddCommonMode",
        "CFRunLoopSourceContext",
        "CFRunLoopSourceCreate",
        "CFRunLoopAddSource",
        "CFRunLoopSourceSignal",
        "CFRunLoopWakeUp",
        "CFRunLoopRunInMode",
        "CFRunLoopSourceInvalidate",
        "CFRunLoopSourceIsValid",
        "kCFRunLoopCommonModes",
        "kCFRunLoopDefaultMode",
    ]
    manifest.write_text(
        manifest.read_text().replace("symbols = [", "symbols = [" + "".join(f'"{symbol}", ' for symbol in symbols))
    )
    (source.parent / "Foundation.btrc").write_text("")
    root = Path(__file__).resolve().parents[3]
    source.write_text((root / "src/tests/native/gui/ui2/probes/macos/UI2MacOSRunLoop.btrc").read_text())
    result = native_compile(source)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    ran = run_native_executable(result.c_source, package, sdk, triple, sanitized)
    assert "PASS: UI2 CoreFoundation common-mode source callbacks and teardown" in ran.stdout


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.parametrize(
    ("fixture", "marker"),
    [
        ("UI2MacOSSignal", "PASS: UI2 macOS scoped common-mode wake and worker signal"),
        ("UI2MacOSViewInput", "PASS: UI2 macOS pointer admission follows effective eligibility"),
        ("UI2MacOSButtonState", "PASS: UI2 macOS eligibility loss retires pending native button actions"),
        ("UI2MacOSViewState", "PASS: UI2 macOS native view state subtree eligibility and deferred observations"),
        ("UI2MacOSDetachFault", "PASS: UI2 macOS detach failures retain actual attachment ownership"),
        ("UI2MacOSPublisher", "PASS: UI2 macOS worker publication and cancellation drain"),
        ("UI2MacOSExecutor", "PASS: UI2 macOS executor worker delivery timers suspension and callback drain"),
        ("UI2MacOSScheduler", "PASS: UI2 macOS scheduled work uses common-mode deadlines and later turns"),
        pytest.param(
            "UI2MacOSApplicationHost",
            "PASS: UI2 macOS host attachment preserves delegate and drains application work",
            marks=pytest.mark.macos_gui,
        ),
        pytest.param(
            "UI2MacOSApplicationPublisher",
            "PASS: UI2 macOS application worker publication and shutdown",
            marks=pytest.mark.macos_gui,
        ),
    ],
)
def test_macos_ui2_scoped_worker_signal(native_project, native_compile, gui_provider_root, sanitized, fixture, marker):
    source, _sdk, _triple = native_project
    package = source.parent.parent
    manifest = package / "btrc.toml"
    symbols = ["CFRunLoopGetMain", "CFRunLoopAddCommonMode", "CFRunLoopRunInMode", "kCFRunLoopDefaultMode"]
    manifest.write_text(
        manifest.read_text().replace("symbols = [", "symbols = [" + "".join(f'"{symbol}", ' for symbol in symbols))
    )
    (source.parent / "Foundation.btrc").write_text("")
    root = Path(__file__).resolve().parents[3]
    source.write_text((root / "src/tests/native/gui/ui2/probes/macos" / f"{fixture}.btrc").read_text())
    if fixture in {"UI2MacOSButtonState", "UI2MacOSViewInput"}:
        (package / "Application.h").write_text("#import <AppKit/AppKit.h>\n")
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "Application.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[NSApplication sharedApplication]"'
            + (
                ', "+[NSWindow new]", "-[NSWindow setReleasedWhenClosed:]", "-[NSWindow setContentSize:]", '
                '"-[NSWindow setContentView:]", "-[NSWindow windowNumber]", "-[NSWindow close]", '
                '"+[NSEvent mouseEventWithType:location:modifierFlags:timestamp:windowNumber:context:eventNumber:clickCount:pressure:]", "NSEventTypeLeftMouseDown"'
                if fixture == "UI2MacOSViewInput"
                else ""
            )
            + "]\n"
        )
    if fixture == "UI2MacOSDetachFault":
        for suffix in ("h", "m"):
            name = f"{fixture}.{suffix}"
            (package / name).write_text((root / "src/tests/native/gui/ui2/probes/macos" / name).read_text())
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "UI2MacOSDetachFault.h"\n'
            'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["+[BTRCUI2DetachFault armView:after:]"]\n'
            '[[native.sources]]\npath = "UI2MacOSDetachFault.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    if fixture == "UI2MacOSApplicationHost":
        for suffix in ("h", "m"):
            name = f"{fixture}.{suffix}"
            (package / name).write_text((root / "src/tests/native/gui/ui2/probes/macos" / name).read_text())
        manifest.write_text(
            manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "UI2MacOSApplicationHost.h"\n'
            'language = "c"\nstandard = "c11"\nos = ["macos"]\n'
            'symbols = ["btrcUI2ApplicationDelegate"]\n'
            '[[native.sources]]\npath = "UI2MacOSApplicationHost.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        )
    (source.parent / "PublisherChecks.btrc").write_text(
        (root / "src/tests/native/gui/ui2/PublisherChecks.btrc").read_text()
    )
    plan = package / "Signal.link.json"
    result = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    generated = package / "Signal.c"
    generated.write_text(result.c_source)
    executable = package / "Signal"

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
    assert marker in ran.stdout


def test_macos_ui2_input_notification_bindings(native_project, native_compile, gui_provider_root):
    source, _sdk, _triple = native_project
    source.write_text("import Library.GUI.MacOS.MacOSViewInput;\nint main() { return 0; }\n")
    result = native_compile(source, data_root=gui_provider_root)
    assert result.successful, str(result.failure) + str(result.diagnostics)
