"""Actual Linux editor clipboard read failures through real SDL Ctrl+V events."""

import hashlib
import json
import shlex
import subprocess
from pathlib import Path

import pytest

from src.tests.native_bindings import NativeBindingPackage
from src.tests.process_limits import C_COMPILE_TIMEOUT, TOOL_TIMEOUT
from src.tests.python.linux_provider_fixtures import (
    provider_environment,
    require_linux_reader,
    transpile_provider_program,
)
from src.tests.runner_capabilities import linux_display_error
from tools.native_plan import NativePlanBuilder

MODES = ("empty-error", "empty-after-query", "null-control")


@pytest.fixture(scope="module", params=["python", "selfhost"])
def frontend(request):
    return request.param


@pytest.fixture(scope="module", params=[False, True], ids=["plain", "sanitized"])
def sanitized(request):
    return request.param


@pytest.mark.linux_gui
def test_linux_clipboard_read(frontend, sanitized, request, tmp_path):
    require_linux_reader()
    if error := linux_display_error():
        pytest.skip(error)
    data_root = request.getfixturevalue("gui_provider_root")
    root = Path(__file__).resolve().parents[3]
    fixture = root / "src/tests/native/gui/linux"
    source = NativeBindingPackage.write(
        fixture / "LinuxClipboardRead.btrc",
        tmp_path / "package",
        fixture / "ClipboardReadControl.h",
        ("clipboardReadArm", "clipboardReadFinish", "clipboardReadComplete"),
    )
    generated, plan = tmp_path / "Program.c", tmp_path / "Program.json"
    transpile_provider_program(source, generated, plan, frontend, request, data_root=data_root)
    flags = shlex.split(
        subprocess.check_output(["pkg-config", "--cflags", "sdl3", "wgpu-native"], text=True, timeout=TOOL_TIMEOUT)
    )
    sanitizers = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    observer = tmp_path / "ClipboardReadFaults.o"
    subprocess.run(
        [
            "cc",
            "-std=c11",
            "-pedantic-errors",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-O2",
            *sanitizers,
            *flags,
            "-c",
            str(fixture / "ClipboardReadFaults.c"),
            "-o",
            str(observer),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=C_COMPILE_TIMEOUT,
    )

    def run(command, **kwargs):
        command = list(command)
        if "-c" in command:
            command[1:1] = sanitizers
            if str(generated) in command:
                command[1:1] = ["-include", str(fixture / "ClipboardReadFaults.h")]
        elif "-o" in command:
            command.extend([str(observer), *sanitizers])
        kwargs.setdefault("timeout", C_COMPILE_TIMEOUT)
        return subprocess.run(command, **kwargs)

    executable = tmp_path / "Program"
    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    (tmp_path / "cell.json").write_text(
        json.dumps(
            {
                "frontend": frontend,
                "sanitized": sanitized,
                "modes": list(MODES),
                "cycles_per_mode": 100,
                "native_seconds": 45,
                "artifacts": {
                    path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (generated, plan, executable)
                },
            },
            indent=2,
        )
        + "\n"
    )
    failures = []
    outcomes = []
    for mode, name in enumerate(MODES):
        stem = tmp_path / f"{mode:02d}-{name}"
        try:
            result = subprocess.run(
                [str(executable), str(mode)],
                capture_output=True,
                text=True,
                timeout=45,
                env=provider_environment(sanitized, UBSAN_OPTIONS="halt_on_error=1"),
            )
        except subprocess.TimeoutExpired as error:
            for suffix, output in (("stdout", error.stdout), ("stderr", error.stderr)):
                Path(f"{stem}.{suffix}").write_bytes(output.encode() if isinstance(output, str) else output or b"")
            Path(f"{stem}.timeout").write_text("45\n")
            outcomes.append(
                {
                    "mode": mode,
                    "name": name,
                    "timeout_seconds": 45,
                    "returncode": None,
                    "passed": False,
                    "completed_cycles": None,
                    "outputs": {
                        f"{stem.name}.{suffix}": hashlib.sha256(Path(f"{stem}.{suffix}").read_bytes()).hexdigest()
                        for suffix in ("stdout", "stderr")
                    },
                }
            )
            failures.append(f"{name}: native timeout")
            continue
        Path(f"{stem}.stdout").write_text(result.stdout)
        Path(f"{stem}.stderr").write_text(result.stderr)
        Path(f"{stem}.exit").write_text(f"{result.returncode}\n")
        marker = f"PASS: Linux clipboard read mode={mode} cycles=100 selection=1 caret=1 retry=1 ownership=1"
        passed = result.returncode == 0 and marker in result.stdout
        outcomes.append(
            {
                "mode": mode,
                "name": name,
                "returncode": result.returncode,
                "passed": passed,
                "completed_cycles": 100 if passed else None,
                "outputs": {
                    f"{stem.name}.{suffix}": hashlib.sha256(Path(f"{stem}.{suffix}").read_bytes()).hexdigest()
                    for suffix in ("stdout", "stderr")
                },
            }
        )
        if not passed:
            failures.append(f"{name}: exit={result.returncode}\n{result.stdout}{result.stderr}")
    (tmp_path / "native.json").write_text(
        json.dumps(
            {"frontend": frontend, "sanitized": sanitized, "expected_cycles_per_mode": 100, "modes": outcomes},
            indent=2,
        )
        + "\n"
    )
    assert not failures, "\n".join(failures)
