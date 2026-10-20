"""Text capture reservations precede real AppKit focus and editing."""

import json
import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_ui2_text_capture(native_project, native_compile, gui_provider_root, sanitized):
    source, _, _ = native_project
    package = source.parent.parent
    root = Path(__file__).resolve().parents[3]
    fixtures = root / "src/tests/native/gui/ui2/probes/macos"
    for fixture in ("UI2MacOSTextField", "UI2MacOSTextCapture"):
        for suffix in ("h", "m"):
            name = f"{fixture}.{suffix}"
            (package / name).write_text((fixtures / name).read_text())
    symbols = [
        "+[BTRCUI2TextProbe prepare]",
        "+[BTRCUI2TextProbe host:]",
        "+[BTRCUI2TextProbe blur:]",
        "+[BTRCUI2TextProbe replace:value:]",
        "+[BTRCUI2TextProbe finish:]",
        "+[BTRCUI2TextCaptureProbe host:second:]",
        "+[BTRCUI2TextCaptureProbe focus:route:]",
        "+[BTRCUI2TextCaptureProbe failFocus:]",
    ]
    manifest = package / "btrc.toml"
    manifest.write_text(
        manifest.read_text() + '\n[[native.bindings]]\nmodule = "Main"\nheader = "UI2MacOSTextCapture.h"\n'
        'language = "objective-c"\nstandard = "c11"\nos = ["macos"]\n'
        f"symbols = {json.dumps(symbols)}\n"
        '[[native.sources]]\npath = "UI2MacOSTextField.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
        '[[native.sources]]\npath = "UI2MacOSTextCapture.m"\nlanguage = "objective-c"\nstandard = "c11"\n'
    )
    source.write_text((fixtures / "UI2MacOSTextCapture.btrc").read_text())
    plan = package / "TextCapture.link.json"
    result = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    generated = package / "TextCapture.c"
    generated.write_text(result.c_source)
    executable = package / "TextCapture"

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
    assert "PASS: UI2 macOS text capture before native focus and editing" in ran.stdout
