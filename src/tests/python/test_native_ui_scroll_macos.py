"""UI2 AppKit scroll geometry, observation pressure and scoped teardown."""

from pathlib import Path

import pytest

from src.tests.python import test_native_ui_core_macos as core
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_ui2_scroll(native_project, native_compile, gui_provider_root, sanitized):
    source, _sdk, _triple = native_project
    package = source.parent.parent
    root = Path(__file__).resolve().parents[3]
    for fixture in ("UI2MacOSDetachFault", "UI2MacOSScroll"):
        for suffix in ("h", "m"):
            name = f"{fixture}.{suffix}"
            (package / name).write_text((root / "src/tests/native/gui/ui2/probes/macos" / name).read_text())
    manifest = package / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "UI2MacOSDetachFault.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[BTRCUI2DetachFault armView:after:]", "+[NSApplication sharedApplication]", '
        '"+[NSView new]"]\n'
        '[[native.sources]]\npath = "UI2MacOSDetachFault.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '\n[[native.bindings]]\nmodule = "Main"\nheader = "UI2MacOSScroll.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["+[BTRCUI2ScrollProbe forceClip:origin:]"]\n'
        '[[native.sources]]\npath = "UI2MacOSScroll.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    core.test_macos_ui2_scoped_worker_signal(
        native_project,
        native_compile,
        gui_provider_root,
        sanitized,
        "UI2MacOSScroll",
        "PASS: UI2 macOS scroll geometry origins pressure and scoped shutdown",
    )
