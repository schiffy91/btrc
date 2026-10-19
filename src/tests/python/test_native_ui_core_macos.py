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
def test_macos_ui2_scoped_worker_signal(native_project, native_compile, gui_provider_root, sanitized):
    source, _sdk, _triple = native_project
    package = source.parent.parent
    manifest = package / "btrc.toml"
    symbols = ["CFRunLoopGetMain", "CFRunLoopAddCommonMode", "CFRunLoopRunInMode", "kCFRunLoopDefaultMode"]
    manifest.write_text(
        manifest.read_text().replace("symbols = [", "symbols = [" + "".join(f'"{symbol}", ' for symbol in symbols))
    )
    (source.parent / "Foundation.btrc").write_text("")
    root = Path(__file__).resolve().parents[3]
    source.write_text((root / "src/tests/native/gui/ui2/probes/macos/UI2MacOSSignal.btrc").read_text())
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
    ran = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "PASS: UI2 macOS scoped common-mode wake and worker signal" in ran.stdout
