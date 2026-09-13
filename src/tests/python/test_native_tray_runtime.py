import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.tests.python.test_native_import_consumer import apple_environment
from src.tests.python.test_native_import_consumer import native_compile as native_compile
from src.tests.python.test_native_import_consumer import native_project as native_project
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


@pytest.mark.parametrize("target", ["linux-x86_64", "windows-x86_64"])
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
