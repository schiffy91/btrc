"""AppKit window state and close transactions through both compilers."""

import pytest

from src.tests.python import test_native_ui_core_macos as core
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_ui2_window(native_project, native_compile, gui_provider_root, sanitized):
    source, _sdk, _triple = native_project
    package = source.parent.parent
    (package / "WindowProbe.h").write_text("#import <AppKit/AppKit.h>\n")
    manifest = package / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "WindowProbe.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[NSApplication sharedApplication]", "-[NSWindow performClose:]"]\n'
    )
    core.test_macos_ui2_scoped_worker_signal(
        native_project,
        native_compile,
        gui_provider_root,
        sanitized,
        "UI2MacOSWindow",
        "PASS: UI2 macOS window state and reversible close transactions",
    )
