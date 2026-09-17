import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.test_native_import_consumer import apple_environment
from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
from src.tests.runner_capabilities import linux_tray_backend_error
from tools.native_plan import NativePlanBuilder

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_tray_lifecycle(native_project, native_compile, tmp_path, sanitized):
    source = ROOT / "src/tests/native/tray/TrayNative.btrc"
    plan = tmp_path / "Tray.json"
    compiled = native_compile(source, plan_path=plan)
    assert compiled.successful, (compiled.failure, compiled.diagnostics)
    generated = tmp_path / "Tray.c"
    generated.write_text(compiled.c_source)
    executable = tmp_path / "Tray"

    def run(command, **kwargs):
        if sanitized and "-o" in command:
            command = [*command, "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        return subprocess.run(command, env=apple_environment(), **kwargs)

    NativePlanBuilder(runner=run).build(
        plan_path=plan, generated_c=generated, output=executable, cc="/usr/bin/clang", cxx="/usr/bin/clang++"
    )
    result = subprocess.run([str(executable)], env=apple_environment(), capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: test_tray_native\n"


@pytest.mark.parametrize("sanitized", [False, True])
def test_native_tray_lifecycle_linux(tmp_path, sanitized):
    """The D-Bus provider hosts the same lifecycle on a live StatusNotifierWatcher."""
    if sys.platform != "linux" or not os.environ.get("BTRC_NATIVE_HEADER_READER"):
        pytest.skip("requires Linux and the explicitly built native header reader")
    if error := linux_tray_backend_error():
        pytest.skip(error)
    generated = tmp_path / "Tray.c"
    plan = tmp_path / "Tray.json"
    compiled = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            "linux-x86_64" if platform.machine() in ("x86_64", "AMD64") else "linux-aarch64",
            str(ROOT / "src/tests/native/tray/TrayNative.btrc"),
            "-o",
            str(generated),
            "--emit-link-plan",
            str(plan),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert compiled.returncode == 0, compiled.stderr
    executable = tmp_path / "Tray"

    def run(command, **kwargs):
        if sanitized and "-o" in command:
            command = [*command, "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
        return subprocess.run(command, **kwargs)

    NativePlanBuilder(runner=run).build(plan_path=plan, generated_c=generated, output=executable, cc="cc", cxx="c++")
    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASS: test_tray_native\n"


@pytest.mark.parametrize("target", ["windows-x86_64"])
def test_native_tray_unsupported_target(target, tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.compiler.python.main",
            "--no-cache",
            "--target",
            target,
            str(ROOT / "src/tests/native/tray/TrayNative.btrc"),
            "-o",
            str(tmp_path / "Tray.c"),
        ],
        cwd=ROOT,
        env={**os.environ, "BTRC_HOME": str(ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0
    assert "provider" in result.stderr.lower()
