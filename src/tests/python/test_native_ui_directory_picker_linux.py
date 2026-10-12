"""Quit cancellation through the actual Linux application and SDL dialog owner."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.python.linux_provider_fixtures import (
    provider_environment,
    require_linux_reader,
    transpile_provider_program,
)
from src.tests.runner_capabilities import linux_display_error
from tools.native_plan import NativePlanBuilder


@pytest.mark.parametrize("frontend", ["python", "selfhost"])
@pytest.mark.parametrize("sanitized", [False, True], ids=["plain", "sanitized"])
@pytest.mark.linux_gui
def test_linux_directory_picker_quit(tmp_path, request, frontend, sanitized):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    root = Path(__file__).resolve().parents[3]
    fixtures = root / "src/tests/native/gui/linux"
    data_root = request.getfixturevalue("gui_provider_root")
    package = tmp_path / "fixture"
    source = NativeBindingPackage.write(
        fixtures / "LinuxDirectoryPickerQuit.btrc",
        package,
        fixtures / "DirectoryPickerDeferredControl.h",
        (
            "pickerReset",
            "pickerComplete",
            "pickerDispose",
            "pickerOpenCount",
            "pickerCallbackCount",
            "pickerOwners",
            "pickerCallbackOwners",
            "pickerFreeCount",
            "pickerFallbackCount",
            "pickerPushQuit",
        ),
    )
    native_source = package / "DirectoryPickerDeferredFaults.c"
    shutil.copyfile(fixtures / native_source.name, native_source)
    with (package / "btrc.toml").open("a") as manifest:
        manifest.write(
            '[[native.sources]]\npath = "DirectoryPickerDeferredFaults.c"\nlanguage = "c"\n'
            'standard = "c11"\nmodules = ["LinuxDirectoryPickerQuit"]\n'
            '[[native.pkg-config]]\nname = "sdl3"\nmodules = ["LinuxDirectoryPickerQuit"]\n'
        )
    generated = tmp_path / "Program.c"
    plan = tmp_path / "Program.json"
    executable = tmp_path / "Program"
    transpile_provider_program(source, generated, plan, frontend, request, data_root)
    sanitizers = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    intercepted = []

    def run(command, **kwargs):
        command = list(command)
        if "-c" in command:
            command[1:1] = sanitizers
            if str(generated) in command:
                command[1:1] = ["-include", str(fixtures / "DirectoryPickerDeferredFaults.h")]
                intercepted.append(str(generated))
            if str(native_source) in command:
                command[1:1] = ["-I", str(data_root / "stdlib")]
        elif "-o" in command:
            command.extend(sanitizers)
        return subprocess.run(command, **kwargs)

    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    assert intercepted == [str(generated)], "the delayed callback seam must instrument exactly the generated program"
    modes = (
        "invalid-request",
        "selected",
        "user-dismissal",
        "native-failure",
        "empty-selection",
        "quit-before-late-selection",
        "quit-before-open",
        "terminal-before-queued-quit",
        "terminal-and-quit-in-one-turn",
        "quit-before-late-dismissal",
        "quit-before-late-failure",
        "pump-throws",
        "native-quit-deferred",
        "native-quit-refused",
        "invalid-request-after-quit",
    )
    (tmp_path / "cell.json").write_text(
        json.dumps(
            {
                "frontend": frontend,
                "sanitized": sanitized,
                "modes": modes,
                "artifacts": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (generated, plan, executable)
                },
            },
            indent=2,
        )
        + "\n"
    )
    failures = []
    for mode, name in enumerate(modes):
        result = subprocess.run(
            [str(executable), str(mode)],
            capture_output=True,
            text=True,
            timeout=30,
            env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
        )
        (tmp_path / f"{mode:02d}-{name}.stdout").write_text(result.stdout)
        (tmp_path / f"{mode:02d}-{name}.stderr").write_text(result.stderr)
        (tmp_path / f"{mode:02d}-{name}.exit").write_text(f"{result.returncode}\n")
        marker = f"PASS: Linux directory picker mode {mode}"
        if result.returncode != 0 or marker not in result.stdout:
            failures.append(f"{mode}: {name}: exit {result.returncode}\n{result.stdout}{result.stderr}")
    assert not failures, "\n".join(failures)
