"""Run-loop context ownership composed with the managed CoreText provider."""

import subprocess
from pathlib import Path

import pytest

from src.tests.python.native_import_fixtures import apple_environment
from src.tests.python.native_import_fixtures import native_compile as native_compile
from src.tests.python.native_import_fixtures import native_project as native_project
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
def test_macos_run_loop_and_core_text_ownership(native_project, native_compile, gui_provider_root, sanitized):
    source, _, _ = native_project
    package = source.parent.parent
    (package / "btrc.toml").write_text(
        'manifest-version = 1\n[package]\nname = "runLoopOwnership"\n'
        '[[native.bindings]]\nmodule = "Foundation"\nheader = "Foundation.h"\n'
        'language = "c"\nstandard = "c11"\nos = ["macos"]\n'
        'symbols = ["CFStringRef", "CFTypeRef", "CFRetain", "CFRelease", "CFGetTypeID", "CFStringGetTypeID", '
        '"CFRunLoopRunInMode", "kCFRunLoopDefaultMode"]\n'
        'borrowed-parameters = ["CFGetTypeID.cf", "CFRunLoopRunInMode.mode"]\n'
        'static-globals = ["kCFRunLoopDefaultMode"]\n'
        '[native.bindings.resources.CFTypeRef]\nownership = "reference-counted"\n'
        'retain = "CFRetain"\nrelease = "CFRelease"\n'
        '[native.bindings.resources.CFStringRef]\nownership = "reference-counted"\n'
        'retain = "CFRetain"\nrelease = "CFRelease"\n'
        'type-query = "CFGetTypeID"\ntype-tag = "CFStringGetTypeID"\n'
    )
    (source.parent / "Foundation.btrc").write_text("")
    root = Path(__file__).resolve().parents[3]
    source.write_text((root / "src/tests/native/gui/ui2/probes/macos/UI2MacOSRunLoopOwnership.btrc").read_text())
    plan = package / "Ownership.link.json"
    result = native_compile(source, data_root=gui_provider_root, plan_path=plan)
    assert result.successful, str(result.failure) + str(result.diagnostics)
    generated = package / "Ownership.c"
    generated.write_text(result.c_source)
    executable = package / "Ownership"

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
    assert "PASS: UI2 run-loop contexts compose with managed CoreText and close during delivery" in ran.stdout
