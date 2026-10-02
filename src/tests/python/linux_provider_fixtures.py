"""Build Linux stdlib provider programs through either compiler and the native plan."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.process_limits import C_COMPILE_TIMEOUT
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]


TARGET = "linux-x86_64" if platform.machine() in ("x86_64", "AMD64") else "linux-aarch64"


def require_linux_reader():
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")


def transpile_provider_program(source: Path, generated: Path, plan: Path, frontend: str, request) -> None:
    environment = {**os.environ, "BTRC_HOME": str(ROOT / "src")}
    if frontend == "python":
        command = [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            TARGET,
            str(source),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ]
    else:
        command = [
            str(request.getfixturevalue("immutable_btrcc")),
            "--target",
            TARGET,
            "--emit-link-plan",
            str(plan),
            str(source),
        ]
    compiled = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=600)
    assert compiled.returncode == 0, compiled.stderr
    if frontend == "selfhost":
        generated.write_text(compiled.stdout)


def build_provider_program(
    source: Path, tmp_path: Path, frontend: str, sanitized: bool, request, faults: Path | None = None
) -> Path:
    """Compile through the chosen frontend and link; `faults` names an SDK fixture
    (Faults.h forced into the generated unit, Faults.c linked in) that replaces the real library."""
    generated = tmp_path / "Program.c"
    plan = tmp_path / "Program.json"
    transpile_provider_program(source, generated, plan, frontend, request)
    executable = tmp_path / "Program"
    sanitizers = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"] if sanitized else []
    objects = []
    if faults is not None:
        fixture = tmp_path / f"{faults.name}.o"
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
                "-c",
                str(faults.with_suffix(".c")),
                "-o",
                str(fixture),
            ],
            check=True,
            timeout=C_COMPILE_TIMEOUT,
        )
        objects.append(str(fixture))

    def run(command, **kwargs):
        command = list(command)
        if "-c" in command:
            command[1:1] = sanitizers
            if faults is not None and str(generated) in command:
                command[1:1] = ["-include", str(faults.with_suffix(".h"))]
        elif "-o" in command:
            command[1:1] = objects
            command.extend(sanitizers)
        return subprocess.run(command, **kwargs)

    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    return executable


def provider_environment(sanitized: bool, **extra: str) -> dict[str, str]:
    environment = {**os.environ, "ASAN_OPTIONS": "detect_leaks=0", **extra}
    # libasan intercepts dlopen, so wgpu-native's own runpath no longer reaches
    # the Vulkan loader; NixOS keeps it under the driver prefix.
    driver = Path("/run/opengl-driver/lib")
    if sanitized and driver.is_dir():
        environment["LD_LIBRARY_PATH"] = ":".join(filter(None, [os.environ.get("LD_LIBRARY_PATH"), str(driver)]))
    return environment
